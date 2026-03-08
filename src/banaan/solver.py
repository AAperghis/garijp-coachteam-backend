"""CP-SAT solver for the banana-boat scheduling problem.

Groups banana-wanting students into sequential boat rides, assigns transport
instructors, and ensures non-banana students always have discipline coverage.
Discipline phase ordering (jz → zb/ws/cat → kb) is a soft preference.
"""

from __future__ import annotations

from ortools.sat.python import cp_model

from .models import (
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
                non_banana_assignments=self._assign_non_banana(),
                config=self.config,
                start_time_minutes=self.start_time_min,
            )

        if self.max_groups == 0:
            return None

        model = cp_model.CpModel()
        n_students = len(self.banana_students)
        n_instructors = len(self.instructors)
        G = self.max_groups

        # ── Decision variables ───────────────────────────────────────────

        # assign[s, g]: banana student s is in group g
        assign: dict[tuple[int, int], cp_model.IntVar] = {}
        for s_idx in range(n_students):
            for g in range(G):
                assign[s_idx, g] = model.NewBoolVar(f"a_{s_idx}_{g}")

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
                == sum(assign[s_idx, g] for s_idx in range(n_students))
            )
            model.Add(group_size[g] >= 1).OnlyEnforceIf(group_active[g])
            model.Add(group_size[g] == 0).OnlyEnforceIf(group_active[g].Not())

        # ── Constraints ──────────────────────────────────────────────────

        # C1: each banana student → exactly 1 group
        for s_idx in range(n_students):
            model.Add(sum(assign[s_idx, g] for g in range(G)) == 1)

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

        # C7: non-banana coverage — at least 1 instructor per discipline free
        self._add_coverage_constraints(model, transport)

        # ── Objective ────────────────────────────────────────────────────
        obj_terms = self._build_objective(model, assign, transport, group_active)
        model.Maximize(sum(obj_terms))

        # ── Solve ────────────────────────────────────────────────────────
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 30
        status = solver.Solve(model)

        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return self._extract_solution(solver, assign, transport, group_active)
        return None

    # ── Constraint helpers ───────────────────────────────────────────────

    def _add_friend_constraints(self, model, assign):
        """Hard: if A lists B as friend and both want banana → same group."""
        seen: set[tuple[int, int]] = set()
        for s_idx, s in enumerate(self.banana_students):
            if s.friend is None or s.friend not in self.student_idx:
                continue
            f_idx = self.student_idx[s.friend]
            pair = (min(s_idx, f_idx), max(s_idx, f_idx))
            if pair in seen:
                continue
            seen.add(pair)
            for g in range(self.max_groups):
                model.Add(assign[s_idx, g] == assign[f_idx, g])

    def _add_coverage_constraints(self, model, transport):
        """At every time slot during the banana program, each discipline that
        has non-banana students must have ≥ 1 instructor NOT transporting.

        Cross-discipline coverage is allowed per COVERAGE_MAP:
        JZ ↔ ZB and ZB ↔ CAT.
        """
        disc_insts: dict[str, list[int]] = {}
        for i_idx, inst in enumerate(self.instructors):
            disc_insts.setdefault(inst.discipline, []).append(i_idx)

        need_coverage = {s.discipline for s in self.non_banana_students}

        # Occupation window for group g: time slots [g-2, g+1].
        # Transport vars for inactive groups are forced to 0, so they
        # don't contribute to the sum.
        G = self.max_groups
        min_t = -2
        max_t = G  # (last group index) + 1
        for t in range(min_t, max_t + 1):
            overlapping = [g for g in range(G) if g - 2 <= t <= g + 1]
            if not overlapping:
                continue
            for d in need_coverage:
                # Pool = all instructors whose discipline can cover d
                pool = []
                for cov_d in COVERAGE_MAP.get(d, {d}):
                    pool.extend(disc_insts.get(cov_d, []))
                if not pool:
                    continue
                model.Add(
                    sum(transport[i, g] for i in pool for g in overlapping)
                    <= len(pool) - 1
                )

    # ── Objective ────────────────────────────────────────────────────────

    def _build_objective(self, model, assign, transport, group_active):
        """Build objective terms to maximize.

        Components (all additive; we maximize the sum):
        - Large penalty per active group  → minimise group count
        - Bonus for own-instructor match  → keep instructor groups intact
        - Bonus for same-discipline match → keep discipline groups intact
        - Phase ordering preference       → jz early, kb late
        """
        w = self.config.weights
        G = self.max_groups
        terms: list = []

        # Penalty for every active group (minimise group count)
        GROUP_PENALTY = 1000
        for g in range(G):
            terms.append(-GROUP_PENALTY * group_active[g])

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

        return terms

    # ── Helpers ──────────────────────────────────────────────────────────

    def _assign_non_banana(self) -> dict[str, str]:
        """Non-banana students stay with their original instructor."""
        return {s.name: s.instructor for s in self.non_banana_students}

    def _extract_solution(self, solver, assign, transport, group_active) -> BanaanSolution:
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
        return BanaanSolution(
            groups=groups,
            non_banana_assignments=self._assign_non_banana(),
            config=self.config,
            start_time_minutes=self.start_time_min,
        )
