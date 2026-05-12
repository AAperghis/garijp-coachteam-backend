"""CP-SAT solver v2 for the banana-boat scheduling problem.

Simplified model: keeps only the core scheduling decisions (ride slots,
transport assignments, instructor trips) and a lightweight per-trip
backup assignment.  Per-slot coverage tracking — which was ~80% of v1's
variables — is eliminated entirely and assigned deterministically in
post-processing.

Coverage is switch-free by construction: each student is with their own
instructor whenever available, and with a single designated backup
instructor for the entire duration their instructor is away.

Variable count comparison (example: 21 banana, 9 non-banana, 14 inst, 24 slots):
  v1: ~13,000 variables, ~10,000 constraints
  v2: ~1,100 variables, ~1,500 constraints
"""

from __future__ import annotations

import math
import os
import time
from collections.abc import Callable

from ortools.sat.python import cp_model

from backend.banaan.models import (
    Student,
    Instructor,
    BanaanConfig,
    BananaRide,
    BananaSolution,
    StudentScheduleEntry,
    InstructorScheduleEntry,
    StudentState,
    InstructorState,
    normalise_discipline,
)
from backend.banaan.solver import SolveProgress, _ProgressCallback, SolveError, check_feasibility


class BanaanSolverV2:
    """Simplified solver — scheduling + backup assignment, coverage post-processed."""

    def __init__(
        self,
        students: list[Student],
        instructors: list[Instructor],
        config: BanaanConfig,
    ) -> None:
        self.students = students
        self.banana_students = [s for s in students if s.wants_banana]
        self.non_banana_students = [s for s in students if not s.wants_banana]
        self.instructors = instructors
        self.config = config
        self.instructor_idx = {inst.name: i for i, inst in enumerate(instructors)}

        T = config.total_slots
        self.T = T
        n_banana = len(self.banana_students)
        self.max_rides = min(n_banana, T) if n_banana else 0

    # ── Public API ───────────────────────────────────────────────────────

    def solve(
        self,
        timeout: int = 120,
        on_progress: Callable[[SolveProgress], None] | None = None,
        callback: _ProgressCallback | None = None,
    ) -> BananaSolution | None:
        if not self.banana_students:
            return self._empty_solution()
        if self.max_rides == 0:
            return None

        check_feasibility(self.students, self.instructors, self.config)

        model = cp_model.CpModel()
        T = self.T
        cfg = self.config
        n_bs = len(self.banana_students)
        n_inst = len(self.instructors)
        transit = cfg.transit_slots
        prep = cfg.prep_slots

        # ── Pre-compute backup compatibility ─────────────────────────────
        # For instructor i, backup j must be able to cover ALL of i's students.
        # j's discipline must be in coverage_map[student.discipline] for every
        # student that belongs to instructor i.
        inst_backup_compat: dict[int, list[int]] = {}
        for i in range(n_inst):
            own_students = [s for s in self.students
                           if s.instructor == self.instructors[i].name]
            if not own_students:
                inst_backup_compat[i] = [j for j in range(n_inst) if j != i]
                continue
            # Intersect coverage sets across all of i's students
            valid_discs: set[str] | None = None
            for s in own_students:
                disc = normalise_discipline(s.discipline)
                s_valid = cfg.coverage_map.get(disc, {disc})
                valid_discs = set(s_valid) if valid_discs is None else valid_discs & s_valid
            inst_backup_compat[i] = [
                j for j in range(n_inst)
                if j != i and normalise_discipline(self.instructors[j].discipline) in (valid_discs or set())
            ]

        # Student counts per instructor (for capacity objective)
        inst_student_count: dict[int, int] = {}
        for i in range(n_inst):
            inst_student_count[i] = sum(
                1 for s in self.students
                if s.instructor == self.instructors[i].name
            )

        # ── Decision variables ───────────────────────────────────────────

        # ride_slot[s]: which time slot banana-student s rides
        ride_slot: dict[int, cp_model.IntVar] = {}
        for s in range(n_bs):
            ride_slot[s] = model.NewIntVar(0, T - 1, f"ride_{s}")

        # banana_used[t]: whether any student rides at slot t
        banana_used: dict[int, cp_model.IntVar] = {}
        for t in range(T):
            banana_used[t] = model.NewBoolVar(f"bu_{t}")

        # ride_at[s, t]: student s rides at slot t (channeling of ride_slot)
        ride_at: dict[tuple[int, int], cp_model.IntVar] = {}
        for s in range(n_bs):
            for t in range(T):
                ride_at[s, t] = model.NewBoolVar(f"ra_{s}_{t}")
                model.Add(ride_slot[s] == t).OnlyEnforceIf(ride_at[s, t])
                model.Add(ride_slot[s] != t).OnlyEnforceIf(ride_at[s, t].Not())

        # Link banana_used to ride_at
        for t in range(T):
            riders = [ride_at[s, t] for s in range(n_bs)]
            model.AddMaxEquality(banana_used[t], riders + [model.NewConstant(0)])

        # goes[i]: does instructor i go to the island?
        goes: dict[int, cp_model.IntVar] = {}
        for i in range(n_inst):
            goes[i] = model.NewBoolVar(f"goes_{i}")

        # depart_slot[i], return_depart[i]: instructor trip timing
        depart_slot: dict[int, cp_model.IntVar] = {}
        return_depart: dict[int, cp_model.IntVar] = {}
        for i in range(n_inst):
            depart_slot[i] = model.NewIntVar(0, T - 1, f"dep_{i}")
            return_depart[i] = model.NewIntVar(0, T - 1, f"ret_{i}")

        # transported_by[s, i]: instructor i transports banana-student s
        transported_by: dict[tuple[int, int], cp_model.IntVar] = {}
        for s in range(n_bs):
            for i in range(n_inst):
                transported_by[s, i] = model.NewBoolVar(f"tb_{s}_{i}")

        # backup[i, j]: instructor j covers i's students while i is away
        backup: dict[tuple[int, int], cp_model.IntVar] = {}
        for i in range(n_inst):
            for j in inst_backup_compat[i]:
                backup[i, j] = model.NewBoolVar(f"bk_{i}_{j}")

        # ── Hard constraints ─────────────────────────────────────────────

        # C1: Each banana student rides exactly once
        for s in range(n_bs):
            model.Add(sum(ride_at[s, t] for t in range(T)) == 1)

        # C2: Banana capacity — at most boat_capacity per slot
        for t in range(T):
            model.Add(sum(ride_at[s, t] for s in range(n_bs)) <= cfg.boat_capacity)

        # C3: Contiguous banana slots
        first_ride = model.NewIntVar(0, T - 1, "first_ride")
        last_ride = model.NewIntVar(0, T - 1, "last_ride")
        model.Add(first_ride <= last_ride)
        for t in range(T):
            model.Add(first_ride <= t).OnlyEnforceIf(banana_used[t])
            model.Add(last_ride >= t).OnlyEnforceIf(banana_used[t])
            in_range = model.NewBoolVar(f"ir_{t}")
            b_af = model.NewBoolVar(f"af_{t}")
            model.Add(first_ride <= t).OnlyEnforceIf(b_af)
            model.Add(first_ride > t).OnlyEnforceIf(b_af.Not())
            b_bl = model.NewBoolVar(f"bl_{t}")
            model.Add(last_ride >= t).OnlyEnforceIf(b_bl)
            model.Add(last_ride < t).OnlyEnforceIf(b_bl.Not())
            model.AddBoolAnd([b_af, b_bl]).OnlyEnforceIf(in_range)
            model.AddBoolOr([b_af.Not(), b_bl.Not()]).OnlyEnforceIf(in_range.Not())
            model.Add(banana_used[t] == 1).OnlyEnforceIf(in_range)

        # C4: Each banana student transported by exactly 1 instructor
        for s in range(n_bs):
            model.Add(sum(transported_by[s, i] for i in range(n_inst)) == 1)

        # C5: Transport capacity; no transport if instructor doesn't go
        for i in range(n_inst):
            model.Add(
                sum(transported_by[s, i] for s in range(n_bs))
                <= self.instructors[i].transport_capacity
            )
            for s in range(n_bs):
                model.Add(transported_by[s, i] == 0).OnlyEnforceIf(goes[i].Not())

        # C6: Trip ordering — depart + transit + prep ≤ return
        for i in range(n_inst):
            model.Add(
                depart_slot[i] + transit + prep <= return_depart[i]
            ).OnlyEnforceIf(goes[i])

        # C7: Student ride within transporter's island window
        #     ride ≥ depart + transit + prep  (arrived + prepped)
        #     ride < return_depart            (before return transit)
        for s in range(n_bs):
            for i in range(n_inst):
                model.Add(
                    ride_slot[s] >= depart_slot[i] + transit + prep
                ).OnlyEnforceIf(transported_by[s, i])
                model.Add(
                    ride_slot[s] + 1 <= return_depart[i]
                ).OnlyEnforceIf(transported_by[s, i])

        # C8: Instructor must return before end of day
        for i in range(n_inst):
            model.Add(return_depart[i] + transit <= T).OnlyEnforceIf(goes[i])

        # C9: Friends ride in the same slot
        friend_map: dict[int, list[int]] = {}
        for s, stud in enumerate(self.banana_students):
            if stud.friends:
                for fname in stud.friends:
                    f_idx = next(
                        (j for j, st in enumerate(self.banana_students)
                         if st.name == fname),
                        None,
                    )
                    if f_idx is not None:
                        model.Add(ride_slot[s] == ride_slot[f_idx])
                        friend_map.setdefault(s, []).append(f_idx)

        # C10: Minimum banana group size (≥2 per slot)
        if n_bs >= 2:
            for t in range(T):
                model.Add(
                    sum(ride_at[s, t] for s in range(n_bs)) >= 2
                ).OnlyEnforceIf(banana_used[t])

        # C11: Instructor ride span ≤ 1 (kids ride in at most 2 consecutive slots)
        for i in range(n_inst):
            inst_min_ride = model.NewIntVar(0, T - 1, f"imr_{i}")
            inst_max_ride = model.NewIntVar(0, T - 1, f"ixr_{i}")
            for s in range(n_bs):
                model.Add(inst_min_ride <= ride_slot[s]).OnlyEnforceIf(transported_by[s, i])
                model.Add(inst_max_ride >= ride_slot[s]).OnlyEnforceIf(transported_by[s, i])
            model.Add(inst_max_ride - inst_min_ride <= 1).OnlyEnforceIf(goes[i])

        # C12: Instructor student grouping — compact ride window
        for i, inst in enumerate(self.instructors):
            own_students = [
                s for s in range(n_bs)
                if self.banana_students[s].instructor == inst.name
            ]
            if len(own_students) < 2:
                continue
            min_slots_needed = math.ceil(len(own_students) / cfg.boat_capacity)
            max_spread = min_slots_needed + 2
            ig_min = model.NewIntVar(0, T - 1, f"igmin_{i}")
            ig_max = model.NewIntVar(0, T - 1, f"igmax_{i}")
            for s in own_students:
                model.Add(ig_min <= ride_slot[s])
                model.Add(ig_max >= ride_slot[s])
            model.Add(ig_max - ig_min <= max_spread)

        # C13: Each going instructor has exactly one backup
        for i in range(n_inst):
            compat = inst_backup_compat[i]
            if compat:
                model.Add(
                    sum(backup[i, j] for j in compat) == 1
                ).OnlyEnforceIf(goes[i])
                model.Add(
                    sum(backup[i, j] for j in compat) == 0
                ).OnlyEnforceIf(goes[i].Not())
            else:
                # No compatible backup → instructor can't go
                model.Add(goes[i] == 0)

        # C14: Backup must not be on island while covering
        #      (relaxed: backup CAN go, but their trip must not overlap)
        for i in range(n_inst):
            for j in inst_backup_compat[i]:
                # If backup[i,j] and goes[j], their trips must not overlap.
                # Non-overlap: j returns before i departs, OR j departs after i returns.
                j_before = model.NewBoolVar(f"jb_{i}_{j}")
                j_after = model.NewBoolVar(f"ja_{i}_{j}")
                model.Add(
                    return_depart[j] + transit <= depart_slot[i]
                ).OnlyEnforceIf(j_before)
                model.Add(
                    depart_slot[j] >= return_depart[i] + transit
                ).OnlyEnforceIf(j_after)
                # At least one must hold when both backup and goes are active
                model.AddBoolOr([
                    j_before, j_after,
                    backup[i, j].Not(), goes[j].Not(),
                ])

        # C15: Maximum trip length (limits island wait time)
        max_island_slots = 2 * transit + prep + 2 + 3
        for i in range(n_inst):
            model.Add(
                return_depart[i] + transit - depart_slot[i] <= max_island_slots
            ).OnlyEnforceIf(goes[i])

        # ── Soft objectives ──────────────────────────────────────────────
        w = cfg.weights
        obj_terms: list = []

        # O1: Minimize banana slots used
        for t in range(T):
            obj_terms.append(-w["group_penalty"] * banana_used[t])

        # O2: Earlier is better
        for s in range(n_bs):
            obj_terms.append(-w["early_bonus"] * ride_slot[s])

        # O3: Phase ordering
        phase_groups: dict[int, list[int]] = {}
        for s in range(n_bs):
            phase_groups.setdefault(self.banana_students[s].phase, []).append(s)
        sorted_phases = sorted(phase_groups.keys())
        for pidx in range(len(sorted_phases) - 1):
            p_cur = sorted_phases[pidx]
            p_next = sorted_phases[pidx + 1]
            cur_students = phase_groups[p_cur]
            next_students = phase_groups[p_next]
            max_cur = model.NewIntVar(0, T - 1, f"max_p{p_cur}")
            model.AddMaxEquality(max_cur, [ride_slot[s] for s in cur_students])
            min_next = model.NewIntVar(0, T - 1, f"min_p{p_next}")
            model.AddMinEquality(min_next, [ride_slot[s] for s in next_students])
            overlap = model.NewIntVar(0, T, f"poverlap_{p_cur}_{p_next}")
            model.AddMaxEquality(overlap, [max_cur - min_next, model.NewConstant(0)])
            multiplier = max(1, int(math.sqrt(len(cur_students) * len(next_students))))
            obj_terms.append(-w["phase_order"] * multiplier * overlap)

        # O4: Minimize trip length (squared) — covers both instructor trip
        #     compactness and student island wait time.
        for i in range(n_inst):
            trip_len = model.NewIntVar(0, T + transit, f"tl_{i}")
            model.Add(
                trip_len == return_depart[i] + transit - depart_slot[i]
            ).OnlyEnforceIf(goes[i])
            model.Add(trip_len == 0).OnlyEnforceIf(goes[i].Not())
            trip_len_sq = model.NewIntVar(0, (T + transit) ** 2, f"tl_sq_{i}")
            model.AddMultiplicationEquality(trip_len_sq, trip_len, trip_len)
            combined_w = w["instructor_trip_penalty"] + w["island_wait_penalty"]
            obj_terms.append(-combined_w * trip_len_sq)

        # O5: Prefer own instructor for transport
        for s in range(n_bs):
            own_i = self.instructor_idx.get(self.banana_students[s].instructor)
            if own_i is not None:
                obj_terms.append(w["own_instructor_bonus"] * transported_by[s, own_i])

        # O6: Prefer same-discipline transport
        for s in range(n_bs):
            s_disc = normalise_discipline(self.banana_students[s].discipline)
            for i in range(n_inst):
                if normalise_discipline(self.instructors[i].discipline) == s_disc:
                    obj_terms.append(w["same_disc_bonus"] * transported_by[s, i])

        # O7: Cover capacity — penalize backup overload (aggregate, not per-slot)
        for j in range(n_inst):
            extras = []
            for i in range(n_inst):
                if (i, j) in backup:
                    ex = model.NewIntVar(0, 50, f"ex_{i}_{j}")
                    model.Add(ex == inst_student_count[i]).OnlyEnforceIf(backup[i, j])
                    model.Add(ex == 0).OnlyEnforceIf(backup[i, j].Not())
                    extras.append(ex)
            if extras:
                total_load = model.NewIntVar(0, 50, f"load_{j}")
                model.Add(total_load == inst_student_count[j] + sum(extras))
                over = model.NewIntVar(0, 50, f"over_{j}")
                model.AddMaxEquality(
                    over, [total_load - self.instructors[j].cover_capacity, 0]
                )
                obj_terms.append(-w["cover_over_penalty"] * over)

        # O8: Backup quality — prefer same-discipline backup
        for i in range(n_inst):
            i_disc = normalise_discipline(self.instructors[i].discipline)
            for j in inst_backup_compat[i]:
                if normalise_discipline(self.instructors[j].discipline) == i_disc:
                    obj_terms.append(w["cover_disc_bonus"] * backup[i, j])

        # O9: Multi-trip penalty
        for i in range(n_inst):
            obj_terms.append(-w["multi_trip_penalty"] * goes[i])

        # O10: Friend bonus (constant since it's a hard constraint)
        for s, friends in friend_map.items():
            for f in friends:
                if f > s:
                    obj_terms.append(w["friend_bonus"])

        model.Maximize(sum(obj_terms))

        # ── Search hints ─────────────────────────────────────────────────
        sorted_by_phase = sorted(
            range(n_bs), key=lambda s: (self.banana_students[s].phase, s)
        )
        for rank, s in enumerate(sorted_by_phase):
            hint_slot = min(rank // max(1, cfg.boat_capacity), T - 1)
            model.AddHint(ride_slot[s], hint_slot)

        # ── Solve ────────────────────────────────────────────────────────
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = timeout
        available_cores = os.cpu_count() or 2
        solver.parameters.num_workers = min(available_cores, 8)
        solver.parameters.linearization_level = 2
        solver.parameters.log_search_progress = True

        if callback is None and on_progress is not None:
            callback = _ProgressCallback(timeout, on_progress)
        status = solver.Solve(model, callback)

        status_name = solver.StatusName(status)
        print(f"  V2 Status: {status_name}, time: {solver.WallTime():.1f}s")
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return self._extract_solution(
                solver, ride_slot, ride_at, banana_used,
                goes, depart_slot, return_depart,
                transported_by, backup,
            )
        if status == cp_model.INFEASIBLE:
            raise SolveError(
                "The solver proved the schedule is infeasible — no valid "
                "arrangement exists with the current students, instructors, "
                "and settings. Try relaxing constraints: increase the time "
                "window, add more instructors, or reduce banana students."
            )
        raise SolveError(
            f"Solver finished with status '{status_name}' after "
            f"{solver.WallTime():.0f}s without finding a solution. "
            f"Try increasing the timeout or simplifying the problem."
        )

    # ── Solution extraction ──────────────────────────────────────────────

    def _extract_solution(
        self, solver, ride_slot, ride_at, banana_used,
        goes, depart_slot, return_depart,
        transported_by, backup,
    ) -> BananaSolution:
        cfg = self.config
        T = self.T
        n_bs = len(self.banana_students)
        n_nbs = len(self.non_banana_students)
        n_inst = len(self.instructors)
        transit = cfg.transit_slots

        # ── Extract raw decisions ────────────────────────────────────────

        inst_goes: dict[int, bool] = {}
        inst_dep: dict[int, int] = {}
        inst_ret: dict[int, int] = {}
        for i in range(n_inst):
            inst_goes[i] = bool(solver.Value(goes[i]))
            if inst_goes[i]:
                inst_dep[i] = solver.Value(depart_slot[i])
                inst_ret[i] = solver.Value(return_depart[i])

        student_transporter: dict[int, int] = {}
        for s in range(n_bs):
            for i in range(n_inst):
                if solver.Value(transported_by[s, i]):
                    student_transporter[s] = i
                    break

        inst_backup: dict[int, int] = {}
        for (i, j), var in backup.items():
            if solver.Value(var):
                inst_backup[i] = j

        # ── Derived helpers ──────────────────────────────────────────────

        def is_on_island(i: int, t: int) -> bool:
            if not inst_goes[i]:
                return False
            return inst_dep[i] <= t <= inst_ret[i] + transit - 1

        def student_is_on_island(s: int, t: int) -> bool:
            return is_on_island(student_transporter[s], t)

        # ── Assign coverage (deterministic) ──────────────────────────────
        # Rule: student stays with own instructor when available.
        #       When own instructor is away, use that instructor's backup.
        #       Fallback: first available compatible instructor.

        def _cover_for_student(stud: Student, t: int) -> str | None:
            own_i = self.instructor_idx.get(stud.instructor)
            if own_i is not None and not is_on_island(own_i, t):
                return self.instructors[own_i].name
            if own_i is not None and own_i in inst_backup:
                bk = inst_backup[own_i]
                if not is_on_island(bk, t):
                    return self.instructors[bk].name
            # Fallback
            disc = normalise_discipline(stud.discipline)
            valid = cfg.coverage_map.get(disc, {disc})
            for j in range(n_inst):
                if not is_on_island(j, t):
                    if normalise_discipline(self.instructors[j].discipline) in valid:
                        return self.instructors[j].name
            return None

        # ── Build rides ──────────────────────────────────────────────────

        rides: list[BananaRide] = []
        for t in range(T):
            if not solver.Value(banana_used[t]):
                continue
            students_on_ride: list[str] = []
            st_transport: dict[str, str] = {}
            transport_insts: set[str] = set()
            for s in range(n_bs):
                if solver.Value(ride_at[s, t]):
                    sname = self.banana_students[s].name
                    students_on_ride.append(sname)
                    i = student_transporter[s]
                    iname = self.instructors[i].name
                    st_transport[sname] = iname
                    transport_insts.add(iname)
            rides.append(BananaRide(
                slot=t,
                students=students_on_ride,
                transport_instructors=sorted(transport_insts),
                student_transport=st_transport,
            ))

        # ── Build student schedules ──────────────────────────────────────

        student_schedules: dict[str, list[StudentScheduleEntry]] = {}

        for s in range(n_bs):
            stud = self.banana_students[s]
            entries = []
            for t in range(T):
                if student_is_on_island(s, t):
                    if solver.Value(ride_at[s, t]):
                        state = StudentState.ON_BANANA
                    else:
                        ti = student_transporter[s]
                        dep = inst_dep[ti]
                        ret = inst_ret[ti]
                        if t < dep + transit:
                            state = StudentState.TRANSIT_TO
                        elif t >= ret:
                            state = StudentState.TRANSIT_FROM
                        else:
                            student_ride = solver.Value(ride_slot[s])
                            if student_ride - cfg.prep_slots <= t < student_ride:
                                state = StudentState.PREP
                            else:
                                state = StudentState.ON_ISLAND
                    entries.append(StudentScheduleEntry(slot=t, state=state))
                else:
                    covering = _cover_for_student(stud, t)
                    entries.append(StudentScheduleEntry(
                        slot=t, state=StudentState.SAILING, instructor=covering,
                    ))
            student_schedules[stud.name] = entries

        for nbs in range(n_nbs):
            stud = self.non_banana_students[nbs]
            entries = []
            for t in range(T):
                covering = _cover_for_student(stud, t)
                entries.append(StudentScheduleEntry(
                    slot=t, state=StudentState.SAILING, instructor=covering,
                ))
            student_schedules[stud.name] = entries

        # ── Build instructor schedules ───────────────────────────────────

        instructor_schedules: dict[str, list[InstructorScheduleEntry]] = {}
        for i in range(n_inst):
            inst = self.instructors[i]
            entries = []
            for t in range(T):
                if is_on_island(i, t):
                    dep = inst_dep[i]
                    ret = inst_ret[i]
                    if t < dep + transit:
                        state = InstructorState.TRANSPORTING_TO
                    elif t >= ret:
                        state = InstructorState.TRANSPORTING_FROM
                    else:
                        state = InstructorState.ON_ISLAND
                    kids = [
                        self.banana_students[s].name
                        for s in range(n_bs)
                        if student_transporter.get(s) == i
                        and student_is_on_island(s, t)
                    ]
                    entries.append(InstructorScheduleEntry(
                        slot=t, state=state,
                        details=f"with {', '.join(kids)}" if kids else "",
                    ))
                else:
                    # Count students this instructor covers at slot t
                    covered: list[str] = []
                    for nbs in range(n_nbs):
                        if _cover_for_student(self.non_banana_students[nbs], t) == inst.name:
                            covered.append(self.non_banana_students[nbs].name)
                    for s in range(n_bs):
                        if not student_is_on_island(s, t):
                            if _cover_for_student(self.banana_students[s], t) == inst.name:
                                covered.append(self.banana_students[s].name)
                    entries.append(InstructorScheduleEntry(
                        slot=t, state=InstructorState.INSTRUCTING,
                        details=f"{len(covered)} kids" if covered else "free",
                    ))
            instructor_schedules[inst.name] = entries

        return BananaSolution(
            rides=rides,
            student_schedules=student_schedules,
            instructor_schedules=instructor_schedules,
            config=cfg,
        )

    def _empty_solution(self) -> BananaSolution:
        cfg = self.config
        T = self.T
        student_schedules = {}
        for s in self.students:
            student_schedules[s.name] = [
                StudentScheduleEntry(slot=t, state=StudentState.SAILING, instructor=s.instructor)
                for t in range(T)
            ]
        instructor_schedules = {}
        for inst in self.instructors:
            instructor_schedules[inst.name] = [
                InstructorScheduleEntry(slot=t, state=InstructorState.INSTRUCTING)
                for t in range(T)
            ]
        return BananaSolution(
            rides=[],
            student_schedules=student_schedules,
            instructor_schedules=instructor_schedules,
            config=cfg,
        )
