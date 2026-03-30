"""CP-SAT solver for the banana-boat scheduling problem.

State-based model: decides where every student and instructor is at every
15-min time slot.  Supports flexible transport (multiple instructors can
supply kids to the same banana ride; one instructor can span multiple rides).
"""

from __future__ import annotations

import math

from ortools.sat.python import cp_model

from .models import (
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


class BanaanSolver:
    """Solver for the banana-boat scheduling problem using OR-Tools CP-SAT.

    Core idea: instead of assigning students to groups and then assigning
    instructors, we decide *per student* which slot they ride and *per
    instructor* when they go to the island.  This allows multiple
    instructors to jointly supply a single ride and one instructor to
    transport kids who ride in different (but nearby) slots.
    """

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
        self.T = T  # total available time slots
        n_banana = len(self.banana_students)
        self.max_rides = min(n_banana, T) if n_banana else 0

    # ── Public API ───────────────────────────────────────────────────────

    def solve(self, timeout: int = 120) -> BananaSolution | None:
        if not self.banana_students:
            return self._empty_solution()
        if self.max_rides == 0:
            return None

        model = cp_model.CpModel()
        T = self.T
        cfg = self.config
        n_bs = len(self.banana_students)
        n_nbs = len(self.non_banana_students)
        n_inst = len(self.instructors)
        transit = cfg.transit_slots  # slots for transit to/from island
        prep = cfg.prep_slots        # slots waiting on island before ride

        # ── Decision variables ───────────────────────────────────────────

        # ride_slot[s]: which time slot banana-student s rides the banana
        ride_slot: dict[int, cp_model.IntVar] = {}
        for s in range(n_bs):
            ride_slot[s] = model.NewIntVar(0, T - 1, f"ride_{s}")

        # banana_used[t]: whether any student rides at slot t
        banana_used: dict[int, cp_model.IntVar] = {}
        for t in range(T):
            banana_used[t] = model.NewBoolVar(f"bu_{t}")

        # ride_at[s, t]: student s rides at slot t
        ride_at: dict[tuple[int, int], cp_model.IntVar] = {}
        for s in range(n_bs):
            for t in range(T):
                ride_at[s, t] = model.NewBoolVar(f"ra_{s}_{t}")
                # Link to ride_slot
                model.Add(ride_slot[s] == t).OnlyEnforceIf(ride_at[s, t])
                model.Add(ride_slot[s] != t).OnlyEnforceIf(ride_at[s, t].Not())

        # Link banana_used to ride_at
        for t in range(T):
            riders = [ride_at[s, t] for s in range(n_bs)]
            model.AddMaxEquality(banana_used[t], riders + [model.NewConstant(0)])

        # goes[i]: does instructor i go to the island at all?
        goes: dict[int, cp_model.IntVar] = {}
        for i in range(n_inst):
            goes[i] = model.NewBoolVar(f"goes_{i}")

        # depart_slot[i]: slot when instructor i starts transit TO island
        depart_slot: dict[int, cp_model.IntVar] = {}
        for i in range(n_inst):
            depart_slot[i] = model.NewIntVar(0, T - 1, f"dep_{i}")

        # return_depart[i]: slot when instructor i starts transit back FROM island
        return_depart: dict[int, cp_model.IntVar] = {}
        for i in range(n_inst):
            return_depart[i] = model.NewIntVar(0, T - 1, f"ret_{i}")

        # transported_by[s, i]: instructor i transports banana-student s
        transported_by: dict[tuple[int, int], cp_model.IntVar] = {}
        for s in range(n_bs):
            for i in range(n_inst):
                transported_by[s, i] = model.NewBoolVar(f"tb_{s}_{i}")

        # on_island[i, t]: instructor i is on/around the island at slot t
        # (transit_to, on_island, or transit_from)
        on_island: dict[tuple[int, int], cp_model.IntVar] = {}
        for i in range(n_inst):
            for t in range(T):
                on_island[i, t] = model.NewBoolVar(f"oi_{i}_{t}")

        # Pre-compute discipline-compatible instructor indices
        nbs_compat: dict[int, list[int]] = {}
        for nbs in range(n_nbs):
            disc = normalise_discipline(self.non_banana_students[nbs].discipline)
            valid = cfg.coverage_map.get(disc, {disc})
            nbs_compat[nbs] = [
                i for i in range(n_inst)
                if normalise_discipline(self.instructors[i].discipline) in valid
            ]
        bs_compat: dict[int, list[int]] = {}
        for s in range(n_bs):
            disc = normalise_discipline(self.banana_students[s].discipline)
            valid = cfg.coverage_map.get(disc, {disc})
            bs_compat[s] = [
                i for i in range(n_inst)
                if normalise_discipline(self.instructors[i].discipline) in valid
            ]
        # Reverse: which students can instructor i cover?
        inst_compat_nbs: dict[int, list[int]] = {i: [] for i in range(n_inst)}
        for nbs, insts in nbs_compat.items():
            for i in insts:
                inst_compat_nbs[i].append(nbs)
        inst_compat_bs: dict[int, list[int]] = {i: [] for i in range(n_inst)}
        for s, insts in bs_compat.items():
            for i in insts:
                inst_compat_bs[i].append(s)

        # cover[nbs, i, t]: instructor i covers non-banana student nbs at slot t
        cover: dict[tuple[int, int, int], cp_model.IntVar] = {}
        for nbs in range(n_nbs):
            for i in nbs_compat[nbs]:
                for t in range(T):
                    cover[nbs, i, t] = model.NewBoolVar(f"c_{nbs}_{i}_{t}")

        # student_on_island[s, t]: banana student s is away from sailing at slot t
        student_on_island: dict[tuple[int, int], cp_model.IntVar] = {}
        for s in range(n_bs):
            for t in range(T):
                student_on_island[s, t] = model.NewBoolVar(f"soi_{s}_{t}")

        # cover_banana[s, i, t]: instructor i covers banana student s at slot t
        # (when the student is sailing, not on island)
        cover_banana: dict[tuple[int, int, int], cp_model.IntVar] = {}
        for s in range(n_bs):
            for i in bs_compat[s]:
                for t in range(T):
                    cover_banana[s, i, t] = model.NewBoolVar(f"cb_{s}_{i}_{t}")

        # ── Hard constraints ─────────────────────────────────────────────

        # C1: Each banana student rides exactly once (already by ride_slot domain)
        for s in range(n_bs):
            model.Add(sum(ride_at[s, t] for t in range(T)) == 1)

        # C2: Banana capacity — at most boat_capacity kids ride per slot
        for t in range(T):
            model.Add(sum(ride_at[s, t] for s in range(n_bs)) <= cfg.boat_capacity)

        # C3: Contiguous banana slots — used slots form a single consecutive block.
        #     Use first_ride and last_ride to define the block, then force all
        #     slots in [first_ride, last_ride] to be used.
        first_ride = model.NewIntVar(0, T - 1, "first_ride")
        last_ride = model.NewIntVar(0, T - 1, "last_ride")
        model.Add(first_ride <= last_ride)

        # Link first_ride/last_ride to banana_used
        for t in range(T):
            # If banana_used[t], then first_ride <= t and last_ride >= t
            model.Add(first_ride <= t).OnlyEnforceIf(banana_used[t])
            model.Add(last_ride >= t).OnlyEnforceIf(banana_used[t])

            # If first_ride <= t <= last_ride, then banana_used[t]
            in_range = model.NewBoolVar(f"in_range_{t}")
            b_after_first = model.NewBoolVar(f"af_{t}")
            model.Add(first_ride <= t).OnlyEnforceIf(b_after_first)
            model.Add(first_ride > t).OnlyEnforceIf(b_after_first.Not())
            b_before_last = model.NewBoolVar(f"bl_{t}")
            model.Add(last_ride >= t).OnlyEnforceIf(b_before_last)
            model.Add(last_ride < t).OnlyEnforceIf(b_before_last.Not())
            model.AddBoolAnd([b_after_first, b_before_last]).OnlyEnforceIf(in_range)
            model.AddBoolOr([b_after_first.Not(), b_before_last.Not()]).OnlyEnforceIf(in_range.Not())
            model.Add(banana_used[t] == 1).OnlyEnforceIf(in_range)

        # C4: Each banana student transported by exactly 1 instructor
        for s in range(n_bs):
            model.Add(sum(transported_by[s, i] for i in range(n_inst)) == 1)

        # C5: Transport capacity — per instructor
        for i in range(n_inst):
            model.Add(
                sum(transported_by[s, i] for s in range(n_bs))
                <= self.instructors[i].transport_capacity
            )
            # Also: if instructor doesn't go, they transport nobody
            for s in range(n_bs):
                model.Add(transported_by[s, i] == 0).OnlyEnforceIf(goes[i].Not())

        # C6: Instructor island presence — on_island[i,t] iff goes[i] and
        #     depart_slot[i] <= t <= return_depart[i] + transit - 1
        for i in range(n_inst):
            for t in range(T):
                # on_island[i,t] => goes[i]
                model.Add(goes[i] == 1).OnlyEnforceIf(on_island[i, t])
                # on_island[i,t] => depart_slot[i] <= t
                model.Add(depart_slot[i] <= t).OnlyEnforceIf(on_island[i, t])
                # on_island[i,t] => t <= return_depart[i] + transit - 1
                model.Add(t <= return_depart[i] + transit - 1).OnlyEnforceIf(on_island[i, t])
                # NOT on_island[i,t] if any of the above fail
                # We use indicator: on_island[i,t] <=> goes[i] AND depart[i]<=t AND t<=ret[i]+transit-1
                b_goes = goes[i]
                b_after_depart = model.NewBoolVar(f"ad_{i}_{t}")
                model.Add(depart_slot[i] <= t).OnlyEnforceIf(b_after_depart)
                model.Add(depart_slot[i] > t).OnlyEnforceIf(b_after_depart.Not())
                b_before_return = model.NewBoolVar(f"br_{i}_{t}")
                model.Add(return_depart[i] + transit - 1 >= t).OnlyEnforceIf(b_before_return)
                model.Add(return_depart[i] + transit - 1 < t).OnlyEnforceIf(b_before_return.Not())
                # on_island[i,t] <=> b_goes AND b_after_depart AND b_before_return
                model.AddBoolAnd([b_goes, b_after_depart, b_before_return]).OnlyEnforceIf(on_island[i, t])
                model.AddBoolOr([b_goes.Not(), b_after_depart.Not(), b_before_return.Not()]).OnlyEnforceIf(on_island[i, t].Not())

            # Ordering: depart before return
            model.Add(depart_slot[i] + transit + prep <= return_depart[i]).OnlyEnforceIf(goes[i])

        # C7: Student on-island timing — if transported_by[s,i], student must
        #     be on island from instructor's depart through instructor's return+transit-1
        #     Student rides during ride_slot[s].
        #     student_on_island[s,t] <=> exists i: transported_by[s,i] AND on_island[i,t]
        for s in range(n_bs):
            for t in range(T):
                on_island_via = []
                for i in range(n_inst):
                    both = model.NewBoolVar(f"tb_oi_{s}_{i}_{t}")
                    model.AddBoolAnd([transported_by[s, i], on_island[i, t]]).OnlyEnforceIf(both)
                    model.AddBoolOr([transported_by[s, i].Not(), on_island[i, t].Not()]).OnlyEnforceIf(both.Not())
                    on_island_via.append(both)
                model.AddMaxEquality(student_on_island[s, t], on_island_via + [model.NewConstant(0)])

        # Student can only ride when they're on the island
        for s in range(n_bs):
            for t in range(T):
                model.Add(student_on_island[s, t] >= ride_at[s, t])

        # C8: Coverage — every student not on the island must have a
        #     compatible instructor supervising them at every slot.
        #
        #     Non-banana students: hard-locked to own instructor when
        #     available.  When own instructor is on island, any compatible
        #     instructor (who isn't on island) covers.  We still create
        #     cover variables so O7 (capacity) can reference them.
        for nbs in range(n_nbs):
            own_i = self.instructor_idx.get(self.non_banana_students[nbs].instructor)
            for t in range(T):
                model.Add(sum(cover[nbs, i, t] for i in nbs_compat[nbs]) == 1)
                for i in nbs_compat[nbs]:
                    model.Add(cover[nbs, i, t] == 0).OnlyEnforceIf(on_island[i, t])
                if own_i is not None:
                    model.Add(cover[nbs, own_i, t] == 1).OnlyEnforceIf(on_island[own_i, t].Not())

        # Banana students while they're sailing (not on island):
        # Hard-lock to own instructor when available.  When own instructor
        # is on island, a backup covers — we add a switch penalty (O13)
        # to keep the backup stable.
        for s in range(n_bs):
            own_i = self.instructor_idx.get(self.banana_students[s].instructor)
            for t in range(T):
                model.Add(
                    sum(cover_banana[s, i, t] for i in bs_compat[s]) == 1
                ).OnlyEnforceIf(student_on_island[s, t].Not())
                model.Add(
                    sum(cover_banana[s, i, t] for i in bs_compat[s]) == 0
                ).OnlyEnforceIf(student_on_island[s, t])
                for i in bs_compat[s]:
                    model.Add(cover_banana[s, i, t] == 0).OnlyEnforceIf(on_island[i, t])
                if own_i is not None:
                    both_avail = model.NewBoolVar(f"ba_{s}_{t}")
                    model.AddBoolAnd([student_on_island[s, t].Not(), on_island[own_i, t].Not()]).OnlyEnforceIf(both_avail)
                    model.AddBoolOr([student_on_island[s, t], on_island[own_i, t]]).OnlyEnforceIf(both_avail.Not())
                    model.Add(cover_banana[s, own_i, t] == 1).OnlyEnforceIf(both_avail)

        # C9: Friends ride in the same slot (hard)
        friend_map = {}
        for s, stud in enumerate(self.banana_students):
            if stud.friends:
                for fname in stud.friends:
                    f_idx = next(
                        (j for j, st in enumerate(self.banana_students) if st.name == fname),
                        None,
                    )
                    if f_idx is not None:
                        model.Add(ride_slot[s] == ride_slot[f_idx])
                        friend_map.setdefault(s, []).append(f_idx)

        # C10: Time window — rides must happen within [0, T-1] (already by domain)
        #      But also: instructor must return before end of day
        for i in range(n_inst):
            model.Add(return_depart[i] + transit <= T).OnlyEnforceIf(goes[i])

        # C11: Minimum banana group size — no kid alone on the banana
        #      (only applies when there are enough banana students)
        if n_bs >= 2:
            for t in range(T):
                model.Add(
                    sum(ride_at[s, t] for s in range(n_bs)) >= 2
                ).OnlyEnforceIf(banana_used[t])

        # C12: Instructor ride span — all kids transported by the same
        #      instructor must ride in at most 2 consecutive banana slots.
        #      This prevents instructors from being parked on the island for
        #      many slots and naturally limits instructors-per-banana.
        for i in range(n_inst):
            inst_min_ride = model.NewIntVar(0, T - 1, f"imr_{i}")
            inst_max_ride = model.NewIntVar(0, T - 1, f"ixr_{i}")
            for s in range(n_bs):
                model.Add(inst_min_ride <= ride_slot[s]).OnlyEnforceIf(transported_by[s, i])
                model.Add(inst_max_ride >= ride_slot[s]).OnlyEnforceIf(transported_by[s, i])
            # Span <= 1 means at most 2 consecutive slots
            model.Add(inst_max_ride - inst_min_ride <= 1).OnlyEnforceIf(goes[i])

        # ── Soft objectives ──────────────────────────────────────────────
        w = cfg.weights
        obj_terms: list = []

        # O1: Minimize banana slots used (highest weight)
        for t in range(T):
            obj_terms.append(-w["group_penalty"] * banana_used[t])

        # O2: Earlier is better
        for s in range(n_bs):
            obj_terms.append(-w["early_bonus"] * ride_slot[s])

        # O3: Phase ordering (almost-hard) — penalize phase-order violations
        for s1 in range(n_bs):
            for s2 in range(s1 + 1, n_bs):
                p1 = self.banana_students[s1].phase
                p2 = self.banana_students[s2].phase
                if p1 < p2:
                    # s1 should ride before or same as s2
                    violation = model.NewBoolVar(f"pv_{s1}_{s2}")
                    model.Add(ride_slot[s1] > ride_slot[s2]).OnlyEnforceIf(violation)
                    model.Add(ride_slot[s1] <= ride_slot[s2]).OnlyEnforceIf(violation.Not())
                    obj_terms.append(-w["phase_order"] * violation)
                elif p1 > p2:
                    violation = model.NewBoolVar(f"pv_{s1}_{s2}")
                    model.Add(ride_slot[s1] < ride_slot[s2]).OnlyEnforceIf(violation)
                    model.Add(ride_slot[s1] >= ride_slot[s2]).OnlyEnforceIf(violation.Not())
                    obj_terms.append(-w["phase_order"] * violation)

        # O4: Minimize island waiting — quadratic penalty on total slots each
        #     student spends on the island.  Quadratic makes many-slot waits
        #     disproportionately expensive (4 slots → cost 16 vs 4 linear).
        for s in range(n_bs):
            island_slots = model.NewIntVar(0, T, f"is_{s}")
            model.Add(island_slots == sum(student_on_island[s, t] for t in range(T)))
            island_slots_sq = model.NewIntVar(0, T * T, f"is_sq_{s}")
            model.AddMultiplicationEquality(island_slots_sq, island_slots, island_slots)
            obj_terms.append(-w["island_wait_penalty"] * island_slots_sq)

        # O4b: Instructor trip compactness — quadratic penalty on trip length.
        #      trip_len² makes a 6-slot trip cost 36 vs 6, strongly pushing
        #      toward short, compact trips.
        for i in range(n_inst):
            trip_len = model.NewIntVar(0, T + transit, f"tl_{i}")
            model.Add(
                trip_len == return_depart[i] + transit - depart_slot[i]
            ).OnlyEnforceIf(goes[i])
            model.Add(trip_len == 0).OnlyEnforceIf(goes[i].Not())
            trip_len_sq = model.NewIntVar(0, (T + transit) ** 2, f"tl_sq_{i}")
            model.AddMultiplicationEquality(trip_len_sq, trip_len, trip_len)
            obj_terms.append(-w["instructor_trip_penalty"] * trip_len_sq)

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

        # O7: Cover capacity (soft) — penalize overloaded instructors
        for t in range(T):
            for i in range(n_inst):
                total_covered = model.NewIntVar(0, n_nbs + n_bs, f"tc_{i}_{t}")
                model.Add(
                    total_covered == (
                        sum(cover[nbs, i, t] for nbs in inst_compat_nbs[i])
                        + sum(cover_banana[s, i, t] for s in inst_compat_bs[i])
                    )
                )
                over = model.NewIntVar(0, n_nbs + n_bs, f"co_{i}_{t}")
                model.AddMaxEquality(over, [total_covered - self.instructors[i].cover_capacity, 0])
                obj_terms.append(-w["cover_over_penalty"] * over)

        # O8: Cover own instructor bonus (non-banana students)
        for nbs in range(n_nbs):
            own_i = self.instructor_idx.get(self.non_banana_students[nbs].instructor)
            if own_i is not None:
                for t in range(T):
                    obj_terms.append(w["cover_own_bonus"] * cover[nbs, own_i, t])

        # O9: Cover same-discipline bonus (non-banana students)
        for nbs in range(n_nbs):
            nbs_disc = normalise_discipline(self.non_banana_students[nbs].discipline)
            for i in nbs_compat[nbs]:
                if normalise_discipline(self.instructors[i].discipline) == nbs_disc:
                    for t in range(T):
                        obj_terms.append(w["cover_disc_bonus"] * cover[nbs, i, t])

        # O10: Cover own instructor bonus (banana students while sailing)
        for s in range(n_bs):
            own_i = self.instructor_idx.get(self.banana_students[s].instructor)
            if own_i is not None:
                for t in range(T):
                    obj_terms.append(w["cover_own_bonus"] * cover_banana[s, own_i, t])

        # O11: Multi-trip penalty — fixed cost for each instructor who goes
        #      to the island.  Fewer trips = simpler schedule.
        for i in range(n_inst):
            obj_terms.append(-w["multi_trip_penalty"] * goes[i])

        # O12: Friend bonus (on top of the hard constraint, reward proximity)
        for s, friends in friend_map.items():
            for f in friends:
                if f > s:  # avoid double counting
                    obj_terms.append(w["friend_bonus"])  # constant bonus since it's hard

        # O13: Cover switch penalty — penalize backup instructor changes for
        #      banana students between consecutive sailing slots.  Non-banana
        #      students are hard-locked to own instructor so no penalty needed.
        for s in range(n_bs):
            for t in range(T - 1):
                # Only between consecutive sailing slots
                both_sailing = model.NewBoolVar(f"bs_{s}_{t}")
                model.AddBoolAnd([student_on_island[s, t].Not(), student_on_island[s, t + 1].Not()]).OnlyEnforceIf(both_sailing)
                model.AddBoolOr([student_on_island[s, t], student_on_island[s, t + 1]]).OnlyEnforceIf(both_sailing.Not())
                for i in bs_compat[s]:
                    lost = model.NewBoolVar(f"lc_{s}_{i}_{t}")
                    model.AddBoolAnd([cover_banana[s, i, t], cover_banana[s, i, t + 1].Not()]).OnlyEnforceIf(lost)
                    model.AddBoolOr([cover_banana[s, i, t].Not(), cover_banana[s, i, t + 1]]).OnlyEnforceIf(lost.Not())
                    switched = model.NewBoolVar(f"cbsw_{s}_{i}_{t}")
                    model.AddBoolAnd([both_sailing, lost]).OnlyEnforceIf(switched)
                    model.AddBoolOr([both_sailing.Not(), lost.Not()]).OnlyEnforceIf(switched.Not())
                    obj_terms.append(-w["cover_switch_penalty"] * switched)

        # C13: Instructor student grouping — each instructor's banana students
        #      must ride within a compact window.  The minimum slots needed
        #      is ceil(n/capacity); we allow some buffer beyond minimum.
        for i, inst in enumerate(self.instructors):
            own_students = [
                s for s in range(n_bs)
                if self.banana_students[s].instructor == inst.name
            ]
            if len(own_students) < 2:
                continue
            min_slots_needed = math.ceil(len(own_students) / cfg.boat_capacity)
            # spread = max_slot - min_slot; allow some buffer beyond minimum
            max_spread = min_slots_needed + 2
            ig_min = model.NewIntVar(0, T - 1, f"igmin_{i}")
            ig_max = model.NewIntVar(0, T - 1, f"igmax_{i}")
            for s in own_students:
                model.Add(ig_min <= ride_slot[s])
                model.Add(ig_max >= ride_slot[s])
            model.Add(ig_max - ig_min <= max_spread)

        # C14: Maximum student island time — no student should be stuck on
        #      the island for an unreasonable amount of time.
        #      min trip = ~3 slots; allow up to 8 (= 2 hours).
        max_island_slots = 2 * transit + prep + 2 + 3  # e.g. 2+1+2+3=8

        # C15: Mandatory prep — each banana student must be on the island
        #      for at least prep_slots before their ride.  Enforced by
        #      requiring ride_slot >= depart_slot + transit + prep for the
        #      transporting instructor.
        if prep > 0:
            for s in range(n_bs):
                for i in range(n_inst):
                    model.Add(
                        ride_slot[s] >= depart_slot[i] + transit + prep
                    ).OnlyEnforceIf(transported_by[s, i])
        for s in range(n_bs):
            model.Add(
                sum(student_on_island[s, t] for t in range(T)) <= max_island_slots
            )

        model.Maximize(sum(obj_terms))

        # ── Solve ────────────────────────────────────────────────────────
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = timeout
        solver.parameters.num_workers = 8
        solver.parameters.log_search_progress = True
        status = solver.Solve(model)

        print(f"  Status: {solver.StatusName(status)}, time: {solver.WallTime():.1f}s")
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return self._extract_solution(solver, ride_slot, ride_at, banana_used,
                                          goes, depart_slot, return_depart,
                                          transported_by, on_island,
                                          student_on_island, cover, cover_banana)
        return None

    # ── Solution extraction ──────────────────────────────────────────────

    def _extract_solution(self, solver, ride_slot, ride_at, banana_used,
                          goes, depart_slot, return_depart,
                          transported_by, on_island,
                          student_on_island, cover, cover_banana) -> BananaSolution:
        cfg = self.config
        T = self.T
        n_bs = len(self.banana_students)
        n_nbs = len(self.non_banana_students)
        n_inst = len(self.instructors)
        transit = cfg.transit_slots

        # Build rides
        rides: list[BananaRide] = []
        for t in range(T):
            if solver.Value(banana_used[t]):
                students = []
                student_transport: dict[str, str] = {}
                transport_insts = set()
                for s in range(n_bs):
                    if solver.Value(ride_at[s, t]):
                        sname = self.banana_students[s].name
                        students.append(sname)
                        for i in range(n_inst):
                            if solver.Value(transported_by[s, i]):
                                iname = self.instructors[i].name
                                student_transport[sname] = iname
                                transport_insts.add(iname)
                                break
                rides.append(BananaRide(
                    slot=t,
                    students=students,
                    transport_instructors=sorted(transport_insts),
                    student_transport=student_transport,
                ))

        # Build student schedules
        student_schedules: dict[str, list[StudentScheduleEntry]] = {}

        # Banana students
        for s in range(n_bs):
            stud = self.banana_students[s]
            entries = []
            for t in range(T):
                if solver.Value(student_on_island[s, t]):
                    if solver.Value(ride_at[s, t]):
                        state = StudentState.ON_BANANA
                    else:
                        # Determine if in transit or waiting
                        # Find which instructor transports this student
                        trans_i = next(i for i in range(n_inst) if solver.Value(transported_by[s, i]))
                        dep = solver.Value(depart_slot[trans_i])
                        ret = solver.Value(return_depart[trans_i])
                        if t < dep + transit:
                            state = StudentState.TRANSIT_TO
                        elif t >= ret:
                            state = StudentState.TRANSIT_FROM
                        else:
                            # Prep slots are the prep_slots immediately before the ride
                            student_ride = solver.Value(ride_slot[s])
                            if student_ride - cfg.prep_slots <= t < student_ride:
                                state = StudentState.PREP
                            else:
                                state = StudentState.ON_ISLAND
                    entries.append(StudentScheduleEntry(slot=t, state=state))
                else:
                    # Sailing — find covering instructor
                    covering_inst = None
                    for i in range(n_inst):
                        if (s, i, t) in cover_banana and solver.Value(cover_banana[s, i, t]):
                            covering_inst = self.instructors[i].name
                            break
                    entries.append(StudentScheduleEntry(
                        slot=t, state=StudentState.SAILING, instructor=covering_inst
                    ))
            student_schedules[stud.name] = entries

        # Non-banana students
        for nbs in range(n_nbs):
            stud = self.non_banana_students[nbs]
            entries = []
            for t in range(T):
                covering_inst = None
                for i in range(n_inst):
                    if (nbs, i, t) in cover and solver.Value(cover[nbs, i, t]):
                        covering_inst = self.instructors[i].name
                        break
                entries.append(StudentScheduleEntry(
                    slot=t, state=StudentState.SAILING, instructor=covering_inst
                ))
            student_schedules[stud.name] = entries

        # Build instructor schedules
        instructor_schedules: dict[str, list[InstructorScheduleEntry]] = {}
        for i in range(n_inst):
            inst = self.instructors[i]
            entries = []
            for t in range(T):
                if solver.Value(on_island[i, t]):
                    dep = solver.Value(depart_slot[i])
                    ret = solver.Value(return_depart[i])
                    if t < dep + transit:
                        state = InstructorState.TRANSPORTING_TO
                    elif t >= ret:
                        state = InstructorState.TRANSPORTING_FROM
                    else:
                        state = InstructorState.ON_ISLAND
                    # Count kids this instructor has on island
                    kids = [
                        self.banana_students[s].name
                        for s in range(n_bs)
                        if solver.Value(transported_by[s, i])
                        and solver.Value(student_on_island[s, t])
                    ]
                    entries.append(InstructorScheduleEntry(
                        slot=t, state=state,
                        details=f"with {', '.join(kids)}" if kids else "",
                    ))
                else:
                    # Instructing/covering
                    covered_nbs = [
                        self.non_banana_students[nbs].name
                        for nbs in range(n_nbs)
                        if (nbs, i, t) in cover and solver.Value(cover[nbs, i, t])
                    ]
                    covered_bs = [
                        self.banana_students[s].name
                        for s in range(n_bs)
                        if (s, i, t) in cover_banana and solver.Value(cover_banana[s, i, t])
                    ]
                    all_covered = covered_nbs + covered_bs
                    state = InstructorState.INSTRUCTING
                    entries.append(InstructorScheduleEntry(
                        slot=t, state=state,
                        details=f"{len(all_covered)} kids" if all_covered else "free",
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
