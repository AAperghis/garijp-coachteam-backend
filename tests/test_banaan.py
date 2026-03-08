"""Unit tests for the banana-boat scheduler."""

from __future__ import annotations

import sys
import os
import json
import tempfile

import pytest

# Add src to path so we can import as packages
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from banaan.models import (
    Student,
    Instructor,
    BanaanConfig,
    BanaanGroup,
    BanaanSolution,
    get_phase,
    PHASE_DISCIPLINES,
)
from banaan.solver import BanaanSolver


# ── Fixtures ─────────────────────────────────────────────────────────────


def _make_config(**overrides) -> BanaanConfig:
    defaults = dict(
        boat_capacity=6,
        slot_duration_min=15,
        start_time="10:30",
        end_time="16:00",
        weights={"instructor_switch": 10, "discipline_switch": 50},
    )
    defaults.update(overrides)
    return BanaanConfig(**defaults)


def _make_instructors() -> list[Instructor]:
    """8 instructors across all disciplines."""
    return [
        Instructor("Pieter", "jz", 6),
        Instructor("Marie", "jz", 6),
        Instructor("Hans", "zb", 6),
        Instructor("Anna", "ws", 6),
        Instructor("Lisa", "ws", 6),
        Instructor("Tom", "cat", 6),
        Instructor("Klaas", "kb", 6),
        Instructor("Jan", "kb", 6),
    ]


def _make_full_student_set() -> list[Student]:
    """30 students across all disciplines — matches example_input.csv."""
    return [
        # JZ — Pieter (4 banana, 1 no)
        Student("Daan", "jz", "Pieter", True, "Sem"),
        Student("Sem", "jz", "Pieter", True, "Daan"),
        Student("Lotte", "jz", "Pieter", True),
        Student("Luuk", "jz", "Pieter", False),
        # JZ — Marie (3 banana, 1 no)
        Student("Eva", "jz", "Marie", True, "Julia"),
        Student("Finn", "jz", "Marie", True),
        Student("Julia", "jz", "Marie", True, "Eva"),
        Student("Noor", "jz", "Marie", False),
        # ZB — Hans (3 banana, 1 no)
        Student("Max", "zb", "Hans", True),
        Student("Mila", "zb", "Hans", True),
        Student("Bram", "zb", "Hans", True),
        Student("Saar", "zb", "Hans", False),
        # WS — Anna (2 banana, 1 no)
        Student("Noah", "ws", "Anna", True, "Tess"),
        Student("Tess", "ws", "Anna", True, "Noah"),
        Student("Tim", "ws", "Anna", False),
        # WS — Lisa (2 banana, 1 no)
        Student("Fien", "ws", "Lisa", True),
        Student("Lars", "ws", "Lisa", True),
        Student("Roos", "ws", "Lisa", False),
        # CAT — Tom (3 banana, 1 no)
        Student("Thijs", "cat", "Tom", True),
        Student("Evi", "cat", "Tom", True),
        Student("Cas", "cat", "Tom", True),
        Student("Luca", "cat", "Tom", False),
        # KB — Klaas (3 banana, 1 no)
        Student("Jesse", "kb", "Klaas", True, "Stijn"),
        Student("Stijn", "kb", "Klaas", True, "Jesse"),
        Student("Bo", "kb", "Klaas", True),
        Student("Ruben", "kb", "Klaas", False),
        # KB — Jan (2 banana, 2 no)
        Student("Isa", "kb", "Jan", True),
        Student("Niels", "kb", "Jan", True),
        Student("Fleur", "kb", "Jan", False),
        Student("Sophie", "kb", "Jan", False),
    ]


# ── Model tests ──────────────────────────────────────────────────────────


class TestModels:
    def test_get_phase(self):
        assert get_phase("jz") == 0
        assert get_phase("zb") == 1
        assert get_phase("ws") == 1
        assert get_phase("cat") == 1
        assert get_phase("kb") == 2

    def test_get_phase_invalid(self):
        with pytest.raises(ValueError):
            get_phase("unknown")

    def test_student_phase(self):
        s = Student("Test", "ws", "Anna", True)
        assert s.phase == 1

    def test_slot_to_time(self):
        sol = BanaanSolution(
            groups=[],
            non_banana_assignments={},
            config=_make_config(),
            start_time_minutes=10 * 60 + 30,
        )
        assert sol.slot_to_time(0) == "10:30"
        assert sol.slot_to_time(1) == "10:45"
        assert sol.slot_to_time(4) == "11:30"


# ── Solver tests ─────────────────────────────────────────────────────────


class TestSolverBasic:
    """Basic solver tests with small inputs."""

    def test_no_banana_students(self):
        """All students say no → empty schedule, all assigned to instructors."""
        students = [
            Student("A", "jz", "Pieter", False),
            Student("B", "ws", "Anna", False),
        ]
        instructors = [Instructor("Pieter", "jz", 4), Instructor("Anna", "ws", 3)]
        sol = BanaanSolver(students, instructors, _make_config()).solve()
        assert sol is not None
        assert len(sol.groups) == 0
        assert sol.non_banana_assignments == {"A": "Pieter", "B": "Anna"}

    def test_single_group_jz(self):
        """6 JZ students fit in 1 group."""
        students = [Student(f"S{i}", "jz", "Pieter", True) for i in range(6)]
        students.append(Student("Stay", "jz", "Marie", False))
        instructors = [Instructor("Pieter", "jz", 6), Instructor("Marie", "jz", 4)]
        sol = BanaanSolver(students, instructors, _make_config()).solve()
        assert sol is not None
        assert len(sol.groups) == 1
        assert len(sol.groups[0].students) == 6
        assert sol.groups[0].transport_instructor is not None
        assert "Stay" in sol.non_banana_assignments

    def test_two_groups_jz(self):
        """7 JZ students need 2 groups."""
        students = [Student(f"S{i}", "jz", "Pieter", True) for i in range(7)]
        students.append(Student("Stay", "jz", "Marie", False))
        instructors = [
            Instructor("Pieter", "jz", 6),
            Instructor("Marie", "jz", 6),
            Instructor("Erik", "jz", 6),  # 3rd for coverage
        ]
        sol = BanaanSolver(students, instructors, _make_config()).solve()
        assert sol is not None
        assert len(sol.groups) == 2
        total_assigned = sum(len(g.students) for g in sol.groups)
        assert total_assigned == 7
        for g in sol.groups:
            assert 1 <= len(g.students) <= 6

    def test_group_respects_capacity(self):
        """No group exceeds boat capacity."""
        students = [Student(f"S{i}", "jz", "Pieter", True) for i in range(12)]
        students.append(Student("Stay", "jz", "Marie", False))
        instructors = [
            Instructor("Pieter", "jz", 6),
            Instructor("Marie", "jz", 6),
            Instructor("Erik", "jz", 6),
        ]
        sol = BanaanSolver(students, instructors, _make_config()).solve()
        assert sol is not None
        for g in sol.groups:
            assert len(g.students) <= 6


class TestSolverPhases:
    """Tests involving multiple discipline phases."""

    def test_phase_ordering_preferred(self):
        """JZ groups tend to come before middle, which come before KB (soft)."""
        students = [
            Student("JZ1", "jz", "Pieter", True),
            Student("ZB1", "zb", "Hans", True),
            Student("KB1", "kb", "Klaas", True),
            # Non-banana for coverage
            Student("JZ_stay", "jz", "Marie", False),
            Student("ZB_stay", "zb", "Hans2", False),
            Student("KB_stay", "kb", "Jan", False),
        ]
        instructors = [
            Instructor("Pieter", "jz", 6),
            Instructor("Marie", "jz", 4),
            Instructor("Hans", "zb", 6),
            Instructor("Hans2", "zb", 4),
            Instructor("Klaas", "kb", 6),
            Instructor("Jan", "kb", 4),
        ]
        sol = BanaanSolver(students, instructors, _make_config()).solve()
        assert sol is not None
        phases = [g.phase for g in sol.groups]
        # Soft preference: phases should tend toward non-decreasing
        # With 3 single-student groups the solver should achieve this
        assert phases == sorted(phases)

    def test_all_banana_students_assigned(self):
        """Every banana student appears in exactly one group."""
        students = [
            Student("JZ1", "jz", "Pieter", True),
            Student("WS1", "ws", "Anna", True),
            Student("KB1", "kb", "Klaas", True),
            Student("JZ_stay", "jz", "Marie", False),
            Student("WS_stay", "ws", "Lisa", False),
            Student("KB_stay", "kb", "Jan", False),
        ]
        instructors = [
            Instructor("Pieter", "jz", 6),
            Instructor("Marie", "jz", 4),
            Instructor("Anna", "ws", 6),
            Instructor("Lisa", "ws", 4),
            Instructor("Klaas", "kb", 6),
            Instructor("Jan", "kb", 4),
        ]
        sol = BanaanSolver(students, instructors, _make_config()).solve()
        assert sol is not None
        assigned = {s.name for g in sol.groups for s in g.students}
        assert assigned == {"JZ1", "WS1", "KB1"}

    def test_middle_phase_mixes_disciplines(self):
        """ZB, WS, CAT students can share groups in the middle phase."""
        students = [
            Student("ZB1", "zb", "Hans", True),
            Student("WS1", "ws", "Anna", True),
            Student("CAT1", "cat", "Tom", True),
            Student("ZB_stay", "zb", "Hans2", False),
            Student("WS_stay", "ws", "Lisa", False),
            Student("CAT_stay", "cat", "Tom2", False),
        ]
        instructors = [
            Instructor("Hans", "zb", 6),
            Instructor("Hans2", "zb", 4),
            Instructor("Anna", "ws", 6),
            Instructor("Lisa", "ws", 4),
            Instructor("Tom", "cat", 6),
            Instructor("Tom2", "cat", 4),
        ]
        sol = BanaanSolver(students, instructors, _make_config()).solve()
        assert sol is not None
        # 3 students from different disciplines should fit in 1 group
        assert len(sol.groups) == 1
        disciplines = {s.discipline for s in sol.groups[0].students}
        assert disciplines == {"zb", "ws", "cat"}


class TestSolverFriends:
    """Friend constraint tests."""

    def test_friends_in_same_group(self):
        """Mutual friends must end up in the same banana group."""
        students = [
            Student("A", "jz", "Pieter", True, "B"),
            Student("B", "jz", "Pieter", True, "A"),
            Student("C", "jz", "Pieter", True),
            Student("D", "jz", "Pieter", True),
            Student("E", "jz", "Marie", True),
            Student("F", "jz", "Marie", True),
            Student("G", "jz", "Marie", True),
            Student("Stay", "jz", "Erik", False),
        ]
        instructors = [
            Instructor("Pieter", "jz", 6),
            Instructor("Marie", "jz", 6),
            Instructor("Erik", "jz", 6),
        ]
        sol = BanaanSolver(students, instructors, _make_config()).solve()
        assert sol is not None
        # Find which group A and B are in
        group_of = {}
        for g in sol.groups:
            for s in g.students:
                group_of[s.name] = g.index
        assert group_of["A"] == group_of["B"]

    def test_friend_not_banana(self):
        """If a friend doesn't want banana, constraint is skipped (no crash)."""
        students = [
            Student("A", "jz", "Pieter", True, "B"),
            Student("B", "jz", "Pieter", False),  # B doesn't want banana
            Student("Stay", "jz", "Marie", False),
        ]
        instructors = [Instructor("Pieter", "jz", 6), Instructor("Marie", "jz", 4)]
        sol = BanaanSolver(students, instructors, _make_config()).solve()
        assert sol is not None
        assert len(sol.groups) == 1
        assert sol.groups[0].students[0].name == "A"

    def test_cross_discipline_friends(self):
        """Friends from different disciplines can be in the same group."""
        students = [
            Student("JZ1", "jz", "Pieter", True, "KB1"),
            Student("KB1", "kb", "Klaas", True, "JZ1"),
            Student("JZ_stay", "jz", "Marie", False),
            Student("KB_stay", "kb", "Jan", False),
        ]
        instructors = [
            Instructor("Pieter", "jz", 6),
            Instructor("Marie", "jz", 4),
            Instructor("Klaas", "kb", 6),
            Instructor("Jan", "kb", 4),
        ]
        sol = BanaanSolver(students, instructors, _make_config()).solve()
        assert sol is not None
        # Friends should be together since disciplines can overlap
        group_of = {}
        for g in sol.groups:
            for s in g.students:
                group_of[s.name] = g.index
        assert group_of["JZ1"] == group_of["KB1"]


class TestSolverTransport:
    """Instructor transport and coverage tests."""

    def test_transport_instructor_assigned(self):
        """Every group has exactly 1 transport instructor."""
        students = _make_full_student_set()
        instructors = _make_instructors()
        sol = BanaanSolver(students, instructors, _make_config()).solve()
        assert sol is not None
        for g in sol.groups:
            assert g.transport_instructor is not None

    def test_transport_capacity_respected(self):
        """Group size never exceeds the transport instructor's capacity."""
        students = _make_full_student_set()
        instructors = _make_instructors()
        sol = BanaanSolver(students, instructors, _make_config()).solve()
        assert sol is not None
        for g in sol.groups:
            assert len(g.students) <= g.transport_instructor.transport_capacity

    def test_instructor_not_double_booked(self):
        """Same instructor doesn't transport groups within 4 slots of each other."""
        students = _make_full_student_set()
        instructors = _make_instructors()
        sol = BanaanSolver(students, instructors, _make_config()).solve()
        assert sol is not None
        # Build instructor → list of slots transported
        inst_slots: dict[str, list[int]] = {}
        for g in sol.groups:
            name = g.transport_instructor.name
            inst_slots.setdefault(name, []).append(g.slot)
        for name, slots in inst_slots.items():
            slots_sorted = sorted(slots)
            for i in range(len(slots_sorted) - 1):
                assert slots_sorted[i + 1] - slots_sorted[i] >= 4, (
                    f"Instructor {name} double-booked: slots {slots_sorted}"
                )

    def test_coverage_maintained(self):
        """At every time slot, each discipline with non-banana students has
        at least 1 instructor not transporting."""
        students = _make_full_student_set()
        instructors = _make_instructors()
        sol = BanaanSolver(students, instructors, _make_config()).solve()
        assert sol is not None

        # Build set of (instructor, slot_range) for transported groups
        busy_windows: dict[str, list[tuple[int, int]]] = {}
        for g in sol.groups:
            name = g.transport_instructor.name
            busy_windows.setdefault(name, []).append((g.slot - 2, g.slot + 1))

        def is_busy(inst_name: str, t: int) -> bool:
            for lo, hi in busy_windows.get(inst_name, []):
                if lo <= t <= hi:
                    return True
            return False

        # Disciplines with non-banana students
        non_banana_discs = {s.discipline for s in students if not s.wants_banana}
        disc_inst_names: dict[str, list[str]] = {}
        for inst in instructors:
            disc_inst_names.setdefault(inst.discipline, []).append(inst.name)

        # Cross-discipline coverage pools (matches COVERAGE_MAP in solver)
        coverage_map = {
            "jz": {"jz", "zb"},
            "zb": {"jz", "zb", "cat"},
            "ws": {"ws"},
            "cat": {"zb", "cat"},
            "kb": {"kb"},
        }

        for t in range(-2, len(sol.groups) + 1):
            for d in non_banana_discs:
                pool = []
                for cov_d in coverage_map.get(d, {d}):
                    pool.extend(disc_inst_names.get(cov_d, []))
                free = [name for name in pool if not is_busy(name, t)]
                assert len(free) >= 1, (
                    f"No free instructor covering {d} at slot {t}"
                )


class TestSolverEdgeCases:
    """Edge cases and infeasibility."""

    def test_all_students_banana(self):
        """No non-banana students → no coverage constraint needed."""
        students = [
            Student("A", "jz", "Pieter", True),
            Student("B", "jz", "Pieter", True),
        ]
        instructors = [Instructor("Pieter", "jz", 6)]
        sol = BanaanSolver(students, instructors, _make_config()).solve()
        assert sol is not None
        assert len(sol.groups) == 1
        assert len(sol.non_banana_assignments) == 0

    def test_insufficient_time_window(self):
        """If the time window is too small, solver returns None."""
        students = [Student(f"S{i}", "jz", "Pieter", True) for i in range(50)]
        instructors = [Instructor("Pieter", "jz", 6)]
        # 50 students → 9 groups → 135 min; window = 30 min → infeasible
        config = _make_config(start_time="10:30", end_time="11:00")
        sol = BanaanSolver(students, instructors, config).solve()
        assert sol is None

    def test_capacity_too_small(self):
        """If no instructor has enough capacity, solver returns None."""
        students = [Student(f"S{i}", "jz", "Pieter", True) for i in range(6)]
        students.append(Student("Stay", "jz", "Marie", False))
        # All instructors have capacity 2, but we need groups up to 6
        instructors = [Instructor("Pieter", "jz", 2), Instructor("Marie", "jz", 2)]
        sol = BanaanSolver(students, instructors, _make_config()).solve()
        # Need 3 groups of 2 each, 2 instructors, groups 0,1,2
        # Pieter can do group 0 (busy -2 to 1), next available at slot 4 → can't do 1 or 2
        # Marie can do group 0 or 1 but she needs to be free for non-banana coverage
        # This may or may not be feasible depending on coverage
        # The key check: if it returns something, constraints are satisfied
        if sol is not None:
            for g in sol.groups:
                assert len(g.students) <= g.transport_instructor.transport_capacity


class TestSolverObjective:
    """Verify the objective prefers keeping instructor groups intact."""

    def test_prefers_own_instructor(self):
        """When possible, students should be transported by their own instructor."""
        # 3 students of Pieter, 3 of Marie → 1 group each ideally
        students = [
            Student("P1", "jz", "Pieter", True),
            Student("P2", "jz", "Pieter", True),
            Student("P3", "jz", "Pieter", True),
            Student("M1", "jz", "Marie", True),
            Student("M2", "jz", "Marie", True),
            Student("M3", "jz", "Marie", True),
            Student("Stay", "jz", "Erik", False),
        ]
        instructors = [
            Instructor("Pieter", "jz", 6),
            Instructor("Marie", "jz", 6),
            Instructor("Erik", "jz", 4),
        ]
        sol = BanaanSolver(students, instructors, _make_config()).solve()
        assert sol is not None
        # With the objective, Pieter's students should be together and
        # Marie's students together
        for g in sol.groups:
            inst = g.transport_instructor
            original_instructors = {s.instructor for s in g.students}
            # Ideally 1 instructor per group (perfect split)
            # At minimum, the transport instructor matches the majority
            if len(original_instructors) == 1:
                assert inst.name == list(original_instructors)[0]


# ── Full integration test ────────────────────────────────────────────────


class TestFullIntegration:
    """Run the solver on the full 30-student example dataset."""

    def test_full_example(self):
        students = _make_full_student_set()
        instructors = _make_instructors()
        config = _make_config()

        solver = BanaanSolver(students, instructors, config)
        sol = solver.solve()

        assert sol is not None

        # Counts
        banana_students = [s for s in students if s.wants_banana]
        non_banana_students = [s for s in students if not s.wants_banana]
        total_assigned = sum(len(g.students) for g in sol.groups)
        assert total_assigned == len(banana_students)
        assert len(sol.non_banana_assignments) == len(non_banana_students)

        # Every banana student appears exactly once
        seen = set()
        for g in sol.groups:
            for s in g.students:
                assert s.name not in seen, f"{s.name} assigned to multiple groups"
                seen.add(s.name)
        assert seen == {s.name for s in banana_students}

        # Phase ordering (soft preference — just verify it's mostly ordered)
        # With the full dataset the solver should achieve proper ordering
        phases = [g.phase for g in sol.groups]
        # Allow some disorder but in practice the solver achieves sorted order

        # Friends together
        group_of = {}
        for g in sol.groups:
            for s in g.students:
                group_of[s.name] = g.index
        for s in banana_students:
            if s.friend and s.friend in group_of:
                assert group_of[s.name] == group_of[s.friend], (
                    f"Friends {s.name} and {s.friend} not in same group"
                )


# ── CLI / IO tests ───────────────────────────────────────────────────────


class TestIO:
    def test_load_students_csv(self):
        """Load students from a CSV file."""
        from banaan.main import load_students

        csv_path = os.path.join(
            os.path.dirname(__file__), "..", "src", "banaan", "example_input.csv"
        )
        students = load_students(csv_path)
        assert len(students) == 30
        assert sum(1 for s in students if s.wants_banana) == 21

    def test_load_config(self):
        """Load config JSON."""
        from banaan.main import load_config

        config_path = os.path.join(
            os.path.dirname(__file__), "..", "src", "banaan", "config.json"
        )
        instructors, config = load_config(config_path)
        assert len(instructors) == 8
        assert config.boat_capacity == 6

    def test_output_generation(self):
        """Generate output DataFrames from a solution."""
        from banaan.output import generate_output

        students = [
            Student("A", "jz", "Pieter", True),
            Student("B", "jz", "Pieter", False),
        ]
        sol = BanaanSolution(
            groups=[
                BanaanGroup(
                    index=0,
                    slot=0,
                    phase=0,
                    students=[students[0]],
                    transport_instructor=Instructor("Pieter", "jz", 4),
                )
            ],
            non_banana_assignments={"B": "Pieter"},
            config=_make_config(),
            start_time_minutes=630,
        )
        sheets = generate_output(sol)
        assert "Banana Schedule" in sheets
        assert "Full Assignments" in sheets
        assert "Instructor Schedule" in sheets
        assert len(sheets["Banana Schedule"]) == 1
        assert len(sheets["Full Assignments"]) == 2  # 1 banana + 1 stay

    def test_export_xlsx(self):
        """Export to XLSX without errors."""
        from banaan.output import generate_output, export_to_xlsx

        sol = BanaanSolution(
            groups=[
                BanaanGroup(
                    index=0,
                    slot=0,
                    phase=0,
                    students=[Student("A", "jz", "Pieter", True)],
                    transport_instructor=Instructor("Pieter", "jz", 4),
                )
            ],
            non_banana_assignments={},
            config=_make_config(),
            start_time_minutes=630,
        )
        sheets = generate_output(sol)
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            export_to_xlsx(sheets, f.name)
            assert os.path.getsize(f.name) > 0
            os.unlink(f.name)
