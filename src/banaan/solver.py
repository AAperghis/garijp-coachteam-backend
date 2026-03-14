"""CP-SAT solver for the banana-boat scheduling problem.

Groups banana-wanting students into sequential boat rides, assigns transport
instructors, and ensures non-banana students always have discipline coverage.
Discipline phase ordering (jz → zb/ws/cat → kb) is a soft preference.
"""

from __future__ import annotations

from ortools.sat.python import cp_model

from .models import (
    NonBananaAssignment,
    Student,
    Instructor,
    BanaanConfig,
    BanaanGroup,
    BanaanSolution,
)

# Occupation window: an instructor transporting group g is busy for
# 4 consecutive slots [g-2, g+1] (transport out, prep, ride, transport back).
OCCUPATION_SLOTS = 4

# Cross-discipline coverage: which disciplines' instructors can supervise
# non-banana students of a given discipline.  JZ ↔ ZB and ZB ↔ CAT.
COVERAGE_MAP: dict[str, set[str]] = {
    "jz":  {"jz", "zb"},
    "zb":  {"jz", "zb", "cat"},
    "ws":  {"ws"},
    "cat": {"zb", "cat"},
    "kb":  {"kb"},
}


class BanaanSolver:            
    """Solver for the banana-boat scheduling problem using OR-Tools CP-SAT."""

    def __init__(
        self,
        students: list[Student],
        instructors: list[Instructor],
        config: BanaanConfig,
    ):
        self.all_students = students
        self.banana_students = [s for s in students if s.wants_banana]
        self.non_banana_students = [s for s in students if not s.wants_banana]
        self.instructors = instructors
        self.config = config

        # Index lookups
        self.student_idx = {s.name: i for i, s in enumerate(self.banana_students)}
        self.instructor_idx = {inst.name: i for i, inst in enumerate(self.instructors)}

        # Parse time window
        h, m = map(int, self.config.start_time.split(":"))
        self.start_time_min = h * 60 + m
        h2, m2 = map(int, self.config.end_time.split(":"))
        self.end_time_min = h2 * 60 + m2

        # Upper bound on groups: bounded by time slots and student count.
        # The solver decides the actual number via group_active variables.
        n_banana = len(self.banana_students)
        max_time_slots = (self.end_time_min - self.start_time_min) // self.config.slot_duration_min
        self.max_groups = min(n_banana, max_time_slots) if n_banana > 0 else 0

    def solve(self) -> BanaanSolution | None:
        """Run the CP-SAT solver.  Returns a BanaanSolution or None if infeasible."""
        if not self.banana_students:
            return BanaanSolution(
                groups=[],
                non_banana_assignments={},
                config=self.config,
                start_time_minutes=self.start_time_min,
            )

        if self.max_groups == 0:
            return None

        model = cp_model.CpModel()
        n_students_nb = len(self.non_banana_students)
        n_students_banana = len(self.banana_students)
        n_instructors = len(self.instructors)
        G = self.max_groups

        # ── Decision variables ───────────────────────────────────────────
        # cover[ns, i, t]: non-banana student ns is covered by instructor i at time t
        cover: dict[tuple[int, int, int], cp_model.IntVar] = {}
        for nbs_idx in range(n_students_nb):
            for i_idx in range(n_instructors):
                for t in range(G):
                    cover[nbs_idx, i_idx, t] = model.NewBoolVar(f"c_{nbs_idx}_{i_idx}_{t}")

        # assign[s, g]: banana student s is in group g
        assign: dict[tuple[int, int], cp_model.IntVar] = {}
        for bs_idx in range(n_students_banana):
            for g in range(G):
                assign[bs_idx, g] = model.NewBoolVar(f"a_{bs_idx}_{g}")

        # transport[i, g]: instructor i transports group g
        transport: dict[tuple[int, int], cp_model.IntVar] = {}
        for i_idx in range(n_instructors):
            for g in range(G):
                transport[i_idx, g] = model.NewBoolVar(f"t_{i_idx}_{g}")

        # group_active[g]: whether group g is used
        group_active: dict[int, cp_model.IntVar] = {}
        for g in range(G):
            group_active[g] = model.NewBoolVar(f"ga_{g}")

        # group_size[g]: number of students in group g (0 if inactive)
        group_size: dict[int, cp_model.IntVar] = {}
        for g in range(G):
            group_size[g] = model.NewIntVar(0, self.config.boat_capacity, f"gs_{g}")
            model.Add(
                group_size[g]
                == sum(assign[bs_idx, g] for bs_idx in range(n_students_banana))
            )
            model.Add(group_size[g] >= 1).OnlyEnforceIf(group_active[g])
            model.Add(group_size[g] == 0).OnlyEnforceIf(group_active[g].Not())

        # ── Constraints ──────────────────────────────────────────────────

        # C1: each banana student → exactly 1 group
        for bs_idx in range(n_students_banana):
            model.Add(sum(assign[bs_idx, g] for g in range(G)) == 1)

        # C2: active groups form a global prefix (group index = time slot)
        for g in range(G - 1):
            model.Add(group_active[g] >= group_active[g + 1])

        # C3: each active group has exactly 1 transport instructor;
        #     inactive groups have none
        for g in range(G):
            model.Add(
                sum(transport[i_idx, g] for i_idx in range(n_instructors)) == 1
            ).OnlyEnforceIf(group_active[g])
            for i_idx in range(n_instructors):
                model.Add(transport[i_idx, g] == 0).OnlyEnforceIf(
                    group_active[g].Not()
                )

        # C4: transport instructor capacity ≥ group size
        for g in range(G):
            for i_idx, inst in enumerate(self.instructors):
                model.Add(
                    group_size[g] <= inst.transport_capacity
                ).OnlyEnforceIf(transport[i_idx, g])

        # C5: same instructor can't transport groups whose slots differ by < 4
        #     (since active groups form a prefix, group index = actual slot)
        for i_idx in range(n_instructors):
            for g1 in range(G):
                for g2 in range(g1 + 1, G):
                    if g2 - g1 < OCCUPATION_SLOTS:
                        model.Add(
                            transport[i_idx, g1] + transport[i_idx, g2] <= 1
                        )

        # C6: friend hard constraint
        self._add_friend_constraints(model, assign)

        # C7: non-banana coverage
        self._add_coverage_constraints(model, transport, cover, group_active)

        # ── Objective ────────────────────────────────────────────────────
        obj_terms = self._build_objective(model, assign, transport, group_active, cover)
        model.Maximize(sum(obj_terms))

        # ── Solve ────────────────────────────────────────────────────────
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 30
        status = solver.Solve(model)

        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return self._extract_solution(solver, assign, transport, group_active, cover)
        return None

    # ── Constraint helpers ───────────────────────────────────────────────
    def _add_friend_constraints(self, model, assign):
        """
        Hard: Each student with at least one friend (who also wants banana) must be in a group with at least one of their friends.
        Soft: Reward for each additional friend in the same group.
        """
        self.friend_pairs = []  # For use in the objective
        n_groups = self.max_groups
        for s_idx, s in enumerate(self.banana_students):
            # Find all friends of s who are also banana students
            friend_indices = [self.student_idx[f] for f in s.friends if f in self.student_idx] if s.friends else []
            if not friend_indices:
                continue
            # Hard: at least one group where s and a friend are together
            together_vars = []
            for f_idx in friend_indices:
                for g in range(n_groups):
                    v = model.NewBoolVar(f"friend_{s_idx}_{f_idx}_{g}")
                    model.AddBoolAnd([assign[s_idx, g], assign[f_idx, g]]).OnlyEnforceIf(v)
                    model.AddBoolOr([assign[s_idx, g].Not(), assign[f_idx, g].Not()]).OnlyEnforceIf(v.Not())
                    together_vars.append(v)
                    self.friend_pairs.append((s_idx, f_idx, g, v))
            model.Add(sum(together_vars) >= 1)

    def _add_coverage_constraints(self, model, transport, cover, group_active):
        """
        For each time slot, any non-banana student must be covered by exactly one valid instructor who is not busy transporting a group at that slot (or during their occupation window).
        """
        G = self.max_groups
        for t in range(G):
            for nbs_idx, nbs in enumerate(self.non_banana_students):
                disc = nbs.discipline
                valid_instructors = [
                    i_idx for i_idx, inst in enumerate(self.instructors)
                    if inst.discipline in COVERAGE_MAP.get(disc, set())
                ]
                invalid_instructors = set(range(len(self.instructors))) - set(valid_instructors)
                # Cannot be covered by invalid instructors
                for i_idx in invalid_instructors:
                    model.Add(cover[nbs_idx, i_idx, t] == 0)

                # Exactly one valid instructor must cover this student at this time
                model.Add(sum(cover[nbs_idx, i_idx, t] for i_idx in valid_instructors) == 1)
                for i_idx in valid_instructors:
                    # Instructor cannot cover if busy transporting a group whose occupation window includes t
                    busy_slots = []
                    for g in range(G):
                        # Group g occupies slots [g-2, g+1]
                        occ_start = g - 2
                        occ_end = g + 1
                        if occ_start <= t <= occ_end:
                            busy_slots.append(transport[i_idx, g])
                    if busy_slots:
                        # If instructor is busy at t, cannot cover
                        model.Add(sum(busy_slots) == 0).OnlyEnforceIf(cover[nbs_idx, i_idx, t])

    # ── Objective ────────────────────────────────────────────────────────

    def _build_objective(self, model, assign, transport, group_active, cover) -> list[cp_model.IntVar]:
        # Soft reward 
        """Build objective terms to maximize.

        Components (all additive; we maximize the sum):
        - Large penalty per active group  → minimise group count
        - Bonus for own-instructor match  → keep instructor groups intact
        - Bonus for same-discipline match → keep discipline groups intact
        - Phase ordering preference       → jz early, kb late
        - Penalty for frequent instructor switches for non-banana students
        """
        w = self.config.weights
        G = self.max_groups
        terms: list = []
        # Penalty for frequent instructor switches for non-banana students
        COVER_SWITCH_PENALTY = w.get("cover_switch_penalty", 10)
        for nbs_idx, nbs in enumerate(self.non_banana_students):
            for t in range(G - 1):
                for i_idx in range(len(self.instructors)):
                    # cover[nbs_idx, i_idx, t] and cover[nbs_idx, j_idx, t+1] for j_idx != i_idx
                    for j_idx in range(len(self.instructors)):
                        if j_idx == i_idx:
                            continue
                        switch = model.NewBoolVar(f"cover_switch_{nbs_idx}_{i_idx}_{j_idx}_{t}")
                        model.AddBoolAnd([cover[nbs_idx, i_idx, t], cover[nbs_idx, j_idx, t+1]]).OnlyEnforceIf(switch)
                        model.AddBoolOr([cover[nbs_idx, i_idx, t].Not(), cover[nbs_idx, j_idx, t+1].Not()]).OnlyEnforceIf(switch.Not())
                        terms.append(-COVER_SWITCH_PENALTY * switch)

        # Penalty for every active group (minimise group count)
        GROUP_PENALTY = self.config.weights.get("banana_group", 100)
        for g in range(G):
            terms.append(-GROUP_PENALTY * group_active[g])

        # Soft penalty for instructors covering more than a set number of non-banana students at any time slot
        COVER_OVER_PENALTY = self.config.weights.get("cover_over_penalty", 10)  # penalty per extra student
        n_students_nb = len(self.non_banana_students)
        n_instructors = len(self.instructors)
        for t in range(G):
            for i_idx in range(n_instructors):
                # Number of non-banana students covered by instructor i at time t
                covered_count = model.NewIntVar(0, n_students_nb, f"covered_{i_idx}_{t}")
                model.Add(covered_count == sum(cover[nbs_idx, i_idx, t] for nbs_idx in range(n_students_nb)))
                # Penalize if covered_count > COVER_LIMIT
                over = model.NewIntVar(0, n_students_nb, f"cover_over_{i_idx}_{t}")
                model.AddMaxEquality(over, [covered_count - self.instructors[i_idx].cover_capacity, 0])
                terms.append(-COVER_OVER_PENALTY * over)

        # Phase ordering preference: phase-0 students get bonus for low group
        # index, phase-2 for high group index. This encourages the preferred
        # jz → zb/ws/cat → kb ordering without making it mandatory.
        PHASE_ORDER_WEIGHT = w.get("phase_order", 3)
        for s_idx, s in enumerate(self.banana_students):
            for g in range(G):
                if s.phase == 0:
                    terms.append(PHASE_ORDER_WEIGHT * (G - g) * assign[s_idx, g])
                elif s.phase == 2:
                    terms.append(PHASE_ORDER_WEIGHT * g * assign[s_idx, g])
                # Phase 1 is neutral

        # Bonus per student for keeping their original instructor / discipline
        for s_idx, s in enumerate(self.banana_students):
            orig_i = self.instructor_idx.get(s.instructor)
            same_disc_is = [
                i for i, inst in enumerate(self.instructors)
                if inst.discipline == s.discipline
            ]

            for g in range(G):
                # Bonus: transported by own instructor
                if orig_i is not None:
                    own = model.NewBoolVar(f"own_{s_idx}_{g}")
                    model.Add(own <= assign[s_idx, g])
                    model.Add(own <= transport[orig_i, g])
                    model.Add(own >= assign[s_idx, g] + transport[orig_i, g] - 1)
                    terms.append(w["instructor_switch"] * own)

                # Bonus: transported by same-discipline instructor
                for i_idx in same_disc_is:
                    dm = model.NewBoolVar(f"dm_{s_idx}_{g}_{i_idx}")
                    model.Add(dm <= assign[s_idx, g])
                    model.Add(dm <= transport[i_idx, g])
                    model.Add(dm >= assign[s_idx, g] + transport[i_idx, g] - 1)
                    terms.append(w["discipline_switch"] * dm)
        
        # Bonus for covering non-banana students with original instructor / discipline
        for nbs_idx, nbs in enumerate(self.non_banana_students):
            orig_i = self.instructor_idx.get(nbs.instructor)
            same_disc_is = [
                i for i, inst in enumerate(self.instructors)
                if inst.discipline == nbs.discipline
            ]
            for t in range(G):
                # Bonus: covered by own instructor at time t
                if orig_i is not None:
                    own_cov = model.NewBoolVar(f"own_cov_{nbs_idx}_{t}")
                    model.Add(own_cov <= cover[nbs_idx, orig_i, t])
                    terms.append(w["instructor_switch"] * own_cov)
                # Bonus: covered by same-discipline instructor at time t
                for i_idx in same_disc_is:
                    dm_cov = model.NewBoolVar(f"dm_cov_{nbs_idx}_{i_idx}_{t}")
                    model.Add(dm_cov <= cover[nbs_idx, i_idx, t])
                    terms.append(w["discipline_switch"] * dm_cov)

        # Bonus for each friend pair together in a group
        FRIEND_REWARD = w.get("friend_reward", 10)
        if hasattr(self, "friend_pairs"):
            for s_idx, f_idx, g, v in self.friend_pairs:
                terms.append(FRIEND_REWARD * v)
        
        # Bonus for groups (banana and covered) with similar age and cwo
        AGE_SIMILARITY_REWARD = w.get("age_similarity_reward", 5)
        CWO_SIMILARITY_REWARD = w.get("cwo_similarity_reward", 5)
        # Banana groups: reward if all students in a group are close in age
        for g in range(G):
            group_students = [s_idx for s_idx in range(len(self.banana_students))]
            for s1 in group_students:
                for s2 in group_students:
                    if s1 >= s2:
                        continue
                    # Both in group g
                    both_in_group = model.NewBoolVar(f"both_banana_{s1}_{s2}_{g}")
                    model.AddBoolAnd([assign[s1, g], assign[s2, g]]).OnlyEnforceIf(both_in_group)
                    model.AddBoolOr([assign[s1, g].Not(), assign[s2, g].Not()]).OnlyEnforceIf(both_in_group.Not())
                    # Reward if ages are close
                    age_diff = abs(self.banana_students[s1].age - self.banana_students[s2].age)
                    if age_diff <= 1:
                        terms.append(AGE_SIMILARITY_REWARD * both_in_group)

        # Covered (non-banana) students: reward if covered by same instructor at same time and are similar in age/cwo
        for t in range(G):
            for i_idx in range(n_instructors):
                nb_students = [nbs_idx for nbs_idx in range(len(self.non_banana_students))]
                for s1 in nb_students:
                    for s2 in nb_students:
                        if s1 >= s2:
                            continue
                        both_covered = model.NewBoolVar(f"both_cov_{s1}_{s2}_{i_idx}_{t}")
                        model.AddBoolAnd([cover[s1, i_idx, t], cover[s2, i_idx, t]]).OnlyEnforceIf(both_covered)
                        model.AddBoolOr([cover[s1, i_idx, t].Not(), cover[s2, i_idx, t].Not()]).OnlyEnforceIf(both_covered.Not())
                        age_diff = abs(self.non_banana_students[s1].age - self.non_banana_students[s2].age)
                        if age_diff <= 1:
                            terms.append(AGE_SIMILARITY_REWARD * both_covered)
                        cwo_diff = abs(self.non_banana_students[s1].cwo - self.non_banana_students[s2].cwo)
                        if cwo_diff <= 1:
                            terms.append(CWO_SIMILARITY_REWARD * both_covered)
        # Bonus/penalty for non-banana students: cwo match with covering instructor
        CWO_MATCH_BONUS = w.get("instructor_cwo_match_bonus", 5)
        for nbs_idx, nbs in enumerate(self.non_banana_students):
            for t in range(G):
                for i_idx, inst in enumerate(self.instructors):
                    cwo_match = model.NewBoolVar(f"cwo_match_nonbanana_{nbs_idx}_{t}_{i_idx}")
                    model.Add(cwo_match <= cover[nbs_idx, i_idx, t])
                    if abs(nbs.cwo - inst.cwo) <= 1:
                        terms.append(CWO_MATCH_BONUS * cwo_match)
                    else:
                        terms.append(-CWO_MATCH_BONUS * cwo_match)

        # Bonus for non-banana students who have the same original instructor and are covered by the same instructor in a slot
        STICK_WITH_GROUP_BONUS = w.get("stick_with_group_bonus", 5)
        # Non-banana students
        for t in range(G):
            for s1 in range(len(self.non_banana_students)):
                for s2 in range(s1+1, len(self.non_banana_students)):
                    nbs1 = self.non_banana_students[s1]
                    nbs2 = self.non_banana_students[s2]
                    if nbs1.instructor == nbs2.instructor:
                        for i_idx in range(len(self.instructors)):
                            both_covered = model.NewBoolVar(f"stick_orig_instr_{t}_{s1}_{s2}_{i_idx}")
                            model.AddBoolAnd([cover[s1, i_idx, t], cover[s2, i_idx, t]]).OnlyEnforceIf(both_covered)
                            model.AddBoolOr([cover[s1, i_idx, t].Not(), cover[s2, i_idx, t].Not()]).OnlyEnforceIf(both_covered.Not())
                            terms.append(STICK_WITH_GROUP_BONUS * both_covered)

        # Banana groups: bonus if students from the same original group are assigned to the same group and covered by the same instructor
        for t in range(G):
            for s1 in range(len(self.banana_students)):
                for s2 in range(s1+1, len(self.banana_students)):
                    bs1 = self.banana_students[s1]
                    bs2 = self.banana_students[s2]
                    # Assuming banana_students have an 'orig_group' attribute
                    if hasattr(bs1, 'orig_group') and hasattr(bs2, 'orig_group') and bs1.orig_group == bs2.orig_group:
                        for i_idx in range(len(self.instructors)):
                            both_covered = model.NewBoolVar(f"stick_banana_group_{t}_{s1}_{s2}_{i_idx}")
                            model.AddBoolAnd([cover[s1, i_idx, t], cover[s2, i_idx, t]]).OnlyEnforceIf(both_covered)
                            model.AddBoolOr([cover[s1, i_idx, t].Not(), cover[s2, i_idx, t].Not()]).OnlyEnforceIf(both_covered.Not())
                            terms.append(STICK_WITH_GROUP_BONUS * both_covered)
        return terms

    # ── Helpers ──────────────────────────────────────────────────────────

    def _extract_solution(self, solver, assign, transport, group_active, cover) -> BanaanSolution:
        groups: list[BanaanGroup] = []
        slot = 0
        for g in range(self.max_groups):
            if not solver.Value(group_active[g]):
                continue
            students = [
                self.banana_students[s_idx]
                for s_idx in range(len(self.banana_students))
                if solver.Value(assign[s_idx, g])
            ]
            inst = None
            for i_idx, instructor in enumerate(self.instructors):
                if solver.Value(transport[i_idx, g]):
                    inst = instructor
                    break
            # Determine the dominant phase of this group
            phase_counts: dict[int, int] = {}
            for s in students:
                phase_counts[s.phase] = phase_counts.get(s.phase, 0) + 1
            phase = max(phase_counts, key=phase_counts.get) if phase_counts else 0
            groups.append(
                BanaanGroup(
                    index=slot,
                    slot=slot,
                    phase=phase,
                    students=students,
                    transport_instructor=inst,
                )
            )
            slot += 1

        # Extract non-banana coverage assignments: (student_name, slot) -> [instructor_name, ...]
        non_banana_assignments = []
        n_students_nb = len(self.non_banana_students)
        n_instructors = len(self.instructors)
        G = self.max_groups
        for t in range(G):
            for nbs_idx, nbs in enumerate(self.non_banana_students):
                covered_by = []
                for i_idx, inst in enumerate(self.instructors):
                    # Only include if this instructor covers this student at this slot
                    try:
                        v = cover[nbs_idx, i_idx, t]
                    except KeyError:
                        continue
                    if solver.Value(v):
                        covered_by.append(inst.name)
                if covered_by and len(covered_by) == 1:
                    non_banana_assignments.append(NonBananaAssignment(
                        student=nbs,
                        slot=t,
                        instructor_name=covered_by[0],
                    ))
                else:
                    raise ValueError(f"Expected exactly one instructor covering non-banana student {nbs.name} at slot {t}, but got: {covered_by}")

        # Debug: Cover assignments and their reasons
        debug_lines = []
        debug_lines.append("==== BANANA SOLVER DEBUG OUTPUT ====")
        debug_lines.append(f"Weights: {self.config.weights}")
        debug_lines.append("")
        for group in groups:
            debug_lines.append(f"Group {group.index}: phase={group.phase}, instructor={group.transport_instructor.name if group.transport_instructor else None}, students={[s.name for s in group.students]}")
            group_penalty = -self.config.weights.get("banana_group", 100)
            debug_lines.append(f"  Penalty: group active = {group_penalty}")
            for s in group.students:
                if group.transport_instructor and s.instructor == group.transport_instructor.name:
                    debug_lines.append(f"    Bonus: {s.name} with own instructor {group.transport_instructor.name} (+{self.config.weights.get('instructor_switch', 0)})")
                if group.transport_instructor and s.discipline == group.transport_instructor.discipline:
                    debug_lines.append(f"    Bonus: {s.name} with same discipline {group.transport_instructor.discipline} (+{self.config.weights.get('discipline_switch', 0)})")
        for nba in non_banana_assignments:
            debug_lines.append(f"Non-banana {nba.student.name} at slot {nba.slot} covered by {nba.instructor_name}")
        debug_lines.append("\n-- Cover assignments by slot --")
        for t in range(G):
            debug_lines.append(f"Slot {t}:")
            for nbs_idx, nbs in enumerate(self.non_banana_students):
                for i_idx, inst in enumerate(self.instructors):
                    v = cover[nbs_idx, i_idx, t]
                    if solver.Value(v):
                        reasons = []
                        # Instructor switch penalty
                        if t > 0:
                            for j_idx in range(n_instructors):
                                if j_idx != i_idx and solver.Value(cover[nbs_idx, j_idx, t-1]):
                                    reasons.append(f"switch from {self.instructors[j_idx].name} (penalty {self.config.weights.get('cover_switch_penalty', 10)})")
                        # CWO match bonus/penalty
                        cwo_diff = abs(nbs.cwo - inst.cwo)
                        cwo_bonus = self.config.weights.get('instructor_cwo_match_bonus', 5)
                        if cwo_diff <= 1:
                            reasons.append(f"cwo match (bonus {cwo_bonus})")
                        else:
                            reasons.append(f"cwo mismatch (penalty {cwo_bonus})")
                        # Instructor/discipline bonus
                        if inst.name == nbs.instructor:
                            reasons.append(f"own instructor (bonus {self.config.weights.get('instructor_switch', 0)})")
                        if inst.discipline == nbs.discipline:
                            reasons.append(f"same discipline (bonus {self.config.weights.get('discipline_switch', 0)})")
                        # Stick with group bonus
                        stick_bonus = self.config.weights.get('stick_with_group_bonus', 5)
                        for t_prev in range(max(0, t-1), t):
                            for other_idx, other in enumerate(self.non_banana_students):
                                if other_idx != nbs_idx and solver.Value(cover[other_idx, i_idx, t]) and solver.Value(cover[other_idx, i_idx, t_prev]):
                                    reasons.append(f"stick with group (bonus {stick_bonus})")
                        # Age/cwo similarity bonus
                        age_sim = self.config.weights.get('age_similarity_reward', 5)
                        cwo_sim = self.config.weights.get('cwo_similarity_reward', 5)
                        for other_idx, other in enumerate(self.non_banana_students):
                            if other_idx != nbs_idx and solver.Value(cover[other_idx, i_idx, t]):
                                if abs(nbs.age - other.age) <= 1:
                                    reasons.append(f"age similarity with {other.name} (bonus {age_sim})")
                                if abs(nbs.cwo - other.cwo) <= 1:
                                    reasons.append(f"cwo similarity with {other.name} (bonus {cwo_sim})")
                        debug_lines.append(f"  {nbs.name} covered by {inst.name}: {', '.join(reasons) if reasons else 'no special reason'}")
        debug_lines.append("==== END DEBUG OUTPUT ====")
        # Save debug output to a log file instead of printing
        log_path = "banaan_cover_debug.log"
        with open(log_path, "w") as f:
            f.write("\n".join(debug_lines))

        return BanaanSolution(
            groups=groups,
            non_banana_assignments=non_banana_assignments,
            config=self.config,
            start_time_minutes=self.start_time_min,
        )
