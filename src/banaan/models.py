from __future__ import annotations

from dataclasses import dataclass, field

PHASE_DISCIPLINES: dict[int, set[str]] = {
    0: {"jz"},
    1: {"zb", "ws", "cat"},
    2: {"kb"},
}


def get_phase(discipline: str) -> int:
    """Return the discipline phase (0=jz, 1=zb/ws/cat, 2=kb)."""
    for phase, discs in PHASE_DISCIPLINES.items():
        if discipline in discs:
            return phase
    raise ValueError(f"Unknown discipline: {discipline}")


@dataclass
class Student:
    name: str
    discipline: str
    instructor: str
    wants_banana: bool
    friend: str | None = None

    @property
    def phase(self) -> int:
        return get_phase(self.discipline)


@dataclass
class Instructor:
    name: str
    discipline: str
    transport_capacity: int


@dataclass
class BanaanConfig:
    boat_capacity: int = 6
    slot_duration_min: int = 15
    prep_time_min: int = 15
    transport_time_min: int = 15
    start_time: str = "10:30"
    end_time: str = "16:00"
    weights: dict[str, int] = field(
        default_factory=lambda: {
            "instructor_switch": 10,
            "discipline_switch": 50,
        }
    )


@dataclass
class BanaanGroup:
    index: int
    slot: int
    phase: int
    students: list[Student] = field(default_factory=list)
    transport_instructor: Instructor | None = None


@dataclass
class BanaanSolution:
    groups: list[BanaanGroup]
    non_banana_assignments: dict[str, str]  # student_name -> instructor_name
    config: BanaanConfig
    start_time_minutes: int = 630  # 10:30 default

    def slot_to_time(self, slot: int) -> str:
        """Convert a banana-boat slot index to HH:MM string."""
        total_min = self.start_time_minutes + slot * self.config.slot_duration_min
        return f"{total_min // 60:02d}:{total_min % 60:02d}"
