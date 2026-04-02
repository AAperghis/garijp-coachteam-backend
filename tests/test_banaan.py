"""Unit tests for the banana-boat scheduler (state-based model)."""

from __future__ import annotations

import sys
import os
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from banaan.models import (
    Student,
    Instructor,
    BanaanConfig,
    BananaSolution,
    BananaRide,
    StudentState,
    get_phase,
    normalise_discipline,
)
from banaan.solver import BanaanSolver


# ── Fixtures ─────────────────────────────────────────────────────────────


def _make_config(**overrides) -> BanaanConfig:
    defaults = dict(
        boat_capacity=6,
        slot_duration_min=15,
        transit_slots=1,
        prep_slots=1,
        start_time="10:30",
        end_time="16:00",
    )
    defaults.update(overrides)
    return BanaanConfig(**defaults)


def _make_instructors() -> list[Instructor]:
    return [
        Instructor("Pieter", "jz", 2, 6, 6),
        Instructor("Marie", "jz", 3, 6, 6),
        Instructor("Hans", "zb", 4, 6, 6),
        Instructor("Anna", "surf", 1, 6, 6),
        Instructor("Lisa", "surf", 2, 6, 6),
        Instructor("Tom", "cat", 3, 6, 6),
        Instructor("Klaas", "kb", 4, 6, 6),
        Instructor("Jan", "kb", 4, 6, 6),
    ]


def _make_full_student_set() -> list[Student]:
    return [
        Student("Daan", "jz", "Pieter", True, 2, 10, ["Sem"]),
        Student("Sem", "jz", "Pieter", True, 2, 10, ["Daan"]),
        Student("Lotte", "jz", "Pieter", True, 2, 9),
        Student("Luuk", "jz", "Pieter", False, 2, 9),
        Student("Eva", "jz", "Marie", True, 3, 11, ["Julia"]),
        Student("Finn", "jz", "Marie", True, 3, 10),
        Student("Julia", "jz", "Marie", True, 3, 11, ["Eva"]),
        Student("Noor", "jz", "Marie", False, 2, 10),
        Student("Max", "zb", "Hans", True, 4, 12),
        Student("Mila", "zb", "Hans", True, 4, 12),
        Student("Bram", "zb", "Hans", True, 4, 13),
        Student("Saar", "zb", "Hans", False, 4, 12),
        Student("Noah", "surf", "Anna", True, 1, 13, ["Tess"]),
        Student("Tess", "surf", "Anna", True, 1, 13, ["Noah"]),
        Student("Tim", "surf", "Anna", False, 1, 12),
        Student("Fien", "surf", "Lisa", True, 2, 14),
        Student("Lars", "surf", "Lisa", True, 2, 14),
        Student("Roos", "surf", "Lisa", False, 2, 13),
        Student("Thijs", "cat", "Tom", True, 3, 15),
        Student("Evi", "cat", "Tom", True, 3, 15),
        Student("Cas", "cat", "Tom", True, 3, 16),
        Student("Luca", "cat", "Tom", False, 3, 15),
        Student("Jesse", "kb", "Klaas", True, 4, 17, ["Stijn"]),
        Student("Stijn", "kb", "Klaas", True, 4, 17, ["Jesse"]),
        Student("Bo", "kb", "Klaas", True, 4, 16),
        Student("Ruben", "kb", "Klaas", False, 4, 16),
        Student("Isa", "kb", "Jan", True, 4, 17),
        Student("Niels", "kb", "Jan", True, 4, 16),
        Student("Fleur", "kb", "Jan", False, 4, 17),
        Student("Sophie", "kb", "Jan", False, 4, 16),
    ]


# ── Helpers ──────────────────────────────────────────────────────────────


def _ride_slot_for(solution: BananaSolution, student_name: str) -> int | None:
    for ride in solution.rides:
        if student_name in ride.students:
            return ride.slot
    return None


# ── Model tests ──────────────────────────────────────────────────────────


class TestModels:
    def test_get_phase(self):
        assert get_phase("jz") == 0
        assert get_phase("opti") == 0
        assert get_phase("laerling") == 0
        assert get_phase("zb") == 1
        assert get_phase("surf") == 1
        assert get_phase("cat") == 1
        assert get_phase("kb") == 2

    def test_get_phase_invalid(self):
        with pytest.raises(ValueError):
            get_phase("unknown")

    def test_normalise_discipline(self):
        assert normalise_discipline("ws") == "surf"
        assert normalise_discipline("windsurf") == "surf"
        assert normalise_discipline("JZ") == "jz"
        assert normalise_discipline(" Cat ") == "cat"

    def test_student_phase(self):
        s = Student("Test", "surf", "Anna", True, 1, 12)
        assert s.phase == 1

    def test_config_slot_time_conversion(self):
        cfg = _make_config()
        assert cfg.slot_to_time(0) == "10:30"
        assert cfg.slot_to_time(1) == "10:45"
        assert cfg.slot_to_time(4) == "11:30"
        assert cfg.time_to_slot("10:30") == 0
        assert cfg.time_to_slot("11:30") == 4

    def test_config_total_slots(self):
        cfg = _make_config(start_time="10:30", end_time="16:00")
        assert cfg.total_slots == 22


# ── Solver tests ─────────────────────────────────────────────────────────


class TestSolverBasic:
    def test_no_banana_students(self):
        students = [
            Student("A", "jz", "Pieter", False, 2, 10),
            Student("B", "surf", "Anna", False, 1, 11),
        ]
        instructors = [Instructor("Pieter", "jz", 2, 4, 4), Instructor("Anna", "surf", 1, 3, 3)]
        sol = BanaanSolver(students, instructors, _make_config()).solve()
        assert sol is not None
        assert len(sol.rides) == 0

    def test_single_ride(self):
        students = [Student(f"S{i}", "jz", "Pieter", True, 2, 10) for i in range(6)]
        students.append(Student("Stay", "jz", "Marie", False, 3, 11))
        instructors = [Instructor("Pieter", "jz", 2, 6, 6), Instructor("Marie", "jz", 3, 4, 4)]
        sol = BanaanSolver(students, instructors, _make_config()).solve()
        assert sol is not None
        assert len(sol.rides) == 1
        assert len(sol.rides[0].students) == 6

    def test_two_rides(self):
        students = [Student(f"S{i}", "jz", "Pieter", True, 2, 10) for i in range(7)]
        students.append(Student("Stay", "jz", "Erik", False, 3, 11))
        instructors = [
            Instructor("Pieter", "jz", 2, 6, 6),
            Instructor("Marie", "jz", 3, 6, 6),
            Instructor("Erik", "jz", 2, 6, 6),
        ]
        sol = BanaanSolver(students, instructors, _make_config()).solve()
        assert sol is not None
        assert len(sol.rides) == 2
        total_assigned = sum(len(r.students) for r in sol.rides)
        assert total_assigned == 7
        for r in sol.rides:
            assert 1 <= len(r.students) <= 6

    def test_ride_respects_capacity(self):
        students = [Student(f"S{i}", "jz", "Pieter", True, 2, 10) for i in range(12)]
        students.append(Student("Stay", "jz", "Erik", False, 3, 11))
        instructors = [
            Instructor("Pieter", "jz", 2, 6, 6),
            Instructor("Marie", "jz", 3, 6, 6),
            Instructor("Erik", "jz", 2, 6, 6),
        ]
        sol = BanaanSolver(students, instructors, _make_config()).solve()
        assert sol is not None
        for r in sol.rides:
            assert len(r.students) <= 6


class TestSolverPhases:
    def test_phase_ordering_preferred(self):
        students = [
            Student("JZ1", "jz", "Pieter", True, 2, 10),
            Student("ZB1", "zb", "Hans", True, 2, 10),
            Student("KB1", "kb", "Klaas", True, 2, 10),
            Student("JZ_stay", "jz", "Marie", False, 3, 11),
            Student("ZB_stay", "zb", "Hans2", False, 3, 11),
            Student("KB_stay", "kb", "Jan", False, 3, 11),
        ]
        instructors = [
            Instructor("Pieter", "jz", 2, 6, 6),
            Instructor("Marie", "jz", 3, 6, 6),
            Instructor("Hans", "zb", 2, 6, 6),
            Instructor("Hans2", "zb", 3, 6, 6),
            Instructor("Klaas", "kb", 2, 6, 6),
            Instructor("Jan", "kb", 3, 6, 6),
        ]
        sol = BanaanSolver(students, instructors, _make_config()).solve()
        assert sol is not None
        jz_slot = _ride_slot_for(sol, "JZ1")
        zb_slot = _ride_slot_for(sol, "ZB1")
        kb_slot = _ride_slot_for(sol, "KB1")
        assert jz_slot is not None and zb_slot is not None and kb_slot is not None
        assert jz_slot <= zb_slot <= kb_slot

    def test_all_banana_students_assigned(self):
        students = [
            Student("JZ1", "jz", "Pieter", True, 2, 10),
            Student("SURF1", "surf", "Anna", True, 2, 10),
            Student("KB1", "kb", "Klaas", True, 2, 10),
            Student("JZ_stay", "jz", "Marie", False, 3, 11),
            Student("SURF_stay", "surf", "Lisa", False, 3, 11),
            Student("KB_stay", "kb", "Jan", False, 3, 11),
        ]
        instructors = [
            Instructor("Pieter", "jz", 2, 6, 6),
            Instructor("Marie", "jz", 3, 6, 6),
            Instructor("Anna", "surf", 2, 6, 6),
            Instructor("Lisa", "surf", 3, 6, 6),
            Instructor("Klaas", "kb", 2, 6, 6),
            Instructor("Jan", "kb", 3, 6, 6),
        ]
        sol = BanaanSolver(students, instructors, _make_config()).solve()
        assert sol is not None
        assigned = {name for r in sol.rides for name in r.students}
        assert assigned == {"JZ1", "SURF1", "KB1"}


class TestSolverFriends:
    def test_friends_in_same_ride(self):
        students = [
            Student("A", "jz", "Pieter", True, 2, 10, ["B"]),
            Student("B", "jz", "Pieter", True, 3, 11, ["A"]),
            Student("C", "jz", "Pieter", True, 2, 10),
            Student("D", "jz", "Pieter", True, 2, 10),
            Student("E", "jz", "Marie", True, 2, 10),
            Student("F", "jz", "Marie", True, 2, 10),
            Student("G", "jz", "Marie", True, 2, 10),
            Student("Stay", "jz", "Erik", False, 3, 11),
        ]
        instructors = [
            Instructor("Pieter", "jz", 3, 6, 6),
            Instructor("Marie", "jz", 6, 6, 6),
            Instructor("Erik", "jz", 6, 6, 6),
        ]
        sol = BanaanSolver(students, instructors, _make_config()).solve()
        assert sol is not None
        a_slot = _ride_slot_for(sol, "A")
        b_slot = _ride_slot_for(sol, "B")
        assert a_slot == b_slot

    def test_friend_not_banana(self):
        students = [
            Student("A", "jz", "Pieter", True, 2, 4, ["B"]),
            Student("B", "jz", "Pieter", False, 2, 4),
            Student("Stay", "jz", "Marie", False, 3, 11),
        ]
        instructors = [Instructor("Pieter", "jz", 3, 6, 6), Instructor("Marie", "jz", 4, 6, 6)]
        sol = BanaanSolver(students, instructors, _make_config()).solve()
        assert sol is not None
        assert len(sol.rides) == 1
        assert "A" in sol.rides[0].students


class TestSolverTransport:
    def test_transport_instructor_assigned(self):
        students = [
            Student("S1", "jz", "Pieter", True, 2, 10),
            Student("S2", "jz", "Pieter", True, 2, 10),
            Student("Stay", "jz", "Marie", False, 3, 11),
        ]
        instructors = [Instructor("Pieter", "jz", 2, 6, 6), Instructor("Marie", "jz", 3, 6, 6)]
        sol = BanaanSolver(students, instructors, _make_config()).solve()
        assert sol is not None
        for r in sol.rides:
            assert len(r.transport_instructors) >= 1

    def test_coverage_maintained(self):
        """At every slot, every non-banana student has a covering instructor."""
        students = [
            Student("B1", "jz", "Pieter", True, 2, 10),
            Student("NB1", "jz", "Marie", False, 3, 11),
            Student("NB2", "kb", "Klaas", False, 4, 16),
        ]
        instructors = [
            Instructor("Pieter", "jz", 2, 6, 6),
            Instructor("Marie", "jz", 3, 6, 6),
            Instructor("Klaas", "kb", 4, 6, 6),
        ]
        sol = BanaanSolver(students, instructors, _make_config()).solve()
        assert sol is not None
        # Check that non-banana students have an instructor at every slot
        for name in ["NB1", "NB2"]:
            sched = sol.student_schedules[name]
            for entry in sched:
                assert entry.state == StudentState.SAILING
                assert entry.instructor is not None

    def test_contiguous_rides(self):
        """Banana ride slots form a contiguous block."""
        students = _make_full_student_set()
        instructors = _make_instructors()
        sol = BanaanSolver(students, instructors, _make_config()).solve()
        assert sol is not None
        if len(sol.rides) > 1:
            slots = sorted(r.slot for r in sol.rides)
            for i in range(len(slots) - 1):
                assert slots[i + 1] - slots[i] == 1, f"Gap in ride slots: {slots}"


class TestSolverEdgeCases:
    def test_all_students_banana(self):
        students = [
            Student("A", "jz", "Pieter", True, 2, 10),
            Student("B", "jz", "Pieter", True, 2, 10),
        ]
        instructors = [Instructor("Pieter", "jz", 2, 6, 6)]
        sol = BanaanSolver(students, instructors, _make_config()).solve()
        assert sol is not None
        assert len(sol.rides) == 1


# ── IO tests ─────────────────────────────────────────────────────────────


class TestIO:
    def test_load_students_csv(self):
        from banaan.main import load_students
        csv_path = os.path.join(
            os.path.dirname(__file__), "..", "src", "banaan", "example_input.csv"
        )
        students = load_students(csv_path)
        assert len(students) == 30
        assert sum(1 for s in students if s.wants_banana) == 21

    def test_load_config(self):
        from banaan.main import load_config
        config_path = os.path.join(
            os.path.dirname(__file__), "..", "src", "banaan", "config.json"
        )
        config = load_config(config_path)
        assert config.boat_capacity == 6

    def test_output_generation(self):
        from banaan.output import generate_output
        from banaan.models import StudentScheduleEntry, InstructorScheduleEntry, InstructorState

        cfg = _make_config()
        sol = BananaSolution(
            rides=[BananaRide(slot=0, students=["A"], transport_instructors=["Pieter"])],
            student_schedules={
                "A": [StudentScheduleEntry(slot=0, state=StudentState.ON_BANANA)],
                "B": [StudentScheduleEntry(slot=0, state=StudentState.SAILING, instructor="Marie")],
            },
            instructor_schedules={
                "Pieter": [InstructorScheduleEntry(slot=0, state=InstructorState.ON_ISLAND, details="with A")],
                "Marie": [InstructorScheduleEntry(slot=0, state=InstructorState.INSTRUCTING, details="1 kids")],
            },
            config=cfg,
        )
        sheets = generate_output(sol)
        assert "Banana Schedule" in sheets
        assert "Full Assignments" in sheets
        assert "Instructor Schedule" in sheets
        assert len(sheets["Banana Schedule"]) == 1

    def test_export_xlsx(self):
        from banaan.output import generate_output, export_to_xlsx
        from banaan.models import StudentScheduleEntry, InstructorScheduleEntry, InstructorState

        cfg = _make_config()
        sol = BananaSolution(
            rides=[BananaRide(slot=0, students=["A"], transport_instructors=["Pieter"])],
            student_schedules={
                "A": [StudentScheduleEntry(slot=0, state=StudentState.ON_BANANA)],
            },
            instructor_schedules={
                "Pieter": [InstructorScheduleEntry(slot=0, state=InstructorState.ON_ISLAND)],
            },
            config=cfg,
        )
        sheets = generate_output(sol)
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            export_to_xlsx(sheets, f.name)
            assert os.path.getsize(f.name) > 0
            os.unlink(f.name)
