"""Data models for the banana-boat scheduling problem.

State-based time-slot model: tracks the location of every person
(student + instructor) at every 15-min time slot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# ── Disciplines & Phases ─────────────────────────────────────────────────

# Phase ordering for banana scheduling.
# Phase 0 (earliest): jz, opti, laerling
# Phase 1 (middle):   zb, ws, surf, cat
# Phase 2 (latest):   kb
PHASE_DISCIPLINES: dict[int, set[str]] = {
    0: {"jz", "opti", "laerling"},
    1: {"zb", "ws", "surf", "cat"},
    2: {"kb"},
}

# Aliases mapping alternative names to canonical discipline names.
DISCIPLINE_ALIASES: dict[str, str] = {
    "windsurf": "surf",
    "ws": "surf",
}

# Cross-discipline coverage: which instructor disciplines can supervise
# students of a given discipline.  JZ ↔ ZB and ZB ↔ CAT.
DEFAULT_COVERAGE_MAP: dict[str, set[str]] = {
    "jz":       {"jz", "opti", "laerling", "zb"},
    "opti":     {"jz", "opti", "laerling", "zb"},
    "laerling": {"jz", "opti", "laerling", "zb"},
    "zb":       {"jz", "opti", "laerling", "zb", "cat"},
    "surf":     {"surf"},
    "cat":      {"zb", "cat"},
    "kb":       {"kb"},
}


def normalise_discipline(raw: str) -> str:
    """Normalise a discipline string to its canonical form."""
    low = raw.strip().lower()
    return DISCIPLINE_ALIASES.get(low, low)


def get_phase(discipline: str) -> int:
    """Return the discipline phase (0=jz/opti/laerling, 1=zb/surf/cat, 2=kb)."""
    canonical = normalise_discipline(discipline)
    for phase, discs in PHASE_DISCIPLINES.items():
        if canonical in discs:
            return phase
    raise ValueError(f"Unknown discipline: {discipline!r}")


# ── Person states ────────────────────────────────────────────────────────

class StudentState(str, Enum):
    SAILING = "sailing"
    TRANSIT_TO = "transit_to"
    ON_ISLAND = "on_island"
    PREP = "prep"
    ON_BANANA = "on_banana"
    TRANSIT_FROM = "transit_from"


class InstructorState(str, Enum):
    INSTRUCTING = "instructing"
    TRANSPORTING_TO = "transporting_to"
    ON_ISLAND = "on_island"
    TRANSPORTING_FROM = "transporting_from"
    COVERING = "covering"


# ── Core data classes ────────────────────────────────────────────────────

@dataclass
class Student:
    name: str
    discipline: str
    instructor: str
    wants_banana: bool
    cwo: int = 1
    age: int = 13
    friends: list[str] | None = None

    @property
    def phase(self) -> int:
        return get_phase(self.discipline)


@dataclass
class Instructor:
    name: str
    discipline: str
    cwo: int = 1
    transport_capacity: int = 6
    cover_capacity: int = 6


# ── Configuration ────────────────────────────────────────────────────────

@dataclass
class BanaanConfig:
    boat_capacity: int = 6
    slot_duration_min: int = 15
    transit_slots: int = 1
    prep_slots: int = 1
    start_time: str = "10:00"
    end_time: str = "16:00"
    weights: dict[str, int] = field(default_factory=lambda: {
        "group_penalty": 1000,
        "early_bonus": 5,
        "phase_order": 500,
        "island_wait_penalty": 2,
        "instructor_trip_penalty": 300,
        "own_instructor_bonus": 150,
        "same_disc_bonus": 100,
        "friend_bonus": 10,
        "cover_over_penalty": 10,
        "cover_own_bonus": 30,
        "cover_disc_bonus": 60,
        "multi_trip_penalty": 200,
        "cover_switch_penalty": 200,
        "instructor_group_penalty": 100,
    })
    coverage_map: dict[str, set[str]] = field(default_factory=lambda: dict(DEFAULT_COVERAGE_MAP))

    @property
    def start_time_minutes(self) -> int:
        h, m = map(int, self.start_time.split(":"))
        return h * 60 + m

    @property
    def end_time_minutes(self) -> int:
        h, m = map(int, self.end_time.split(":"))
        return h * 60 + m

    @property
    def total_slots(self) -> int:
        return (self.end_time_minutes - self.start_time_minutes) // self.slot_duration_min

    def slot_to_time(self, slot: int) -> str:
        total_min = self.start_time_minutes + slot * self.slot_duration_min
        return f"{total_min // 60:02d}:{total_min % 60:02d}"

    def time_to_slot(self, time_str: str) -> int:
        h, m = map(int, time_str.split(":"))
        return (h * 60 + m - self.start_time_minutes) // self.slot_duration_min


# ── Solution ─────────────────────────────────────────────────────────────

@dataclass
class BananaRide:
    slot: int
    students: list[str]
    transport_instructors: list[str]
    student_transport: dict[str, str] = field(default_factory=dict)  # student_name → instructor_name


@dataclass
class StudentScheduleEntry:
    slot: int
    state: StudentState
    instructor: str | None = None


@dataclass
class InstructorScheduleEntry:
    slot: int
    state: InstructorState
    details: str = ""


@dataclass
class BananaSolution:
    rides: list[BananaRide]
    student_schedules: dict[str, list[StudentScheduleEntry]]
    instructor_schedules: dict[str, list[InstructorScheduleEntry]]
    config: BanaanConfig

    def slot_to_time(self, slot: int) -> str:
        return self.config.slot_to_time(slot)
