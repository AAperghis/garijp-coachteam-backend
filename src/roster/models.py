from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple

@dataclass
class Person:
    id: str
    name: str
    task_weights: Dict[str, float] = field(default_factory=dict)  # {task_id: weight}

@dataclass
class Task:
    id: str
    name: str
    preferred_people: int  # Optimal number of people
    min_people: int  # Minimum required people

@dataclass
class Roster:
    people: List[Person]
    tasks: List[Task]
    days: List[str]  # E.g., ["Monday", "Tuesday", ...]
    
    # Constraints
    task_conflicts: List[Tuple[str, str]] = field(default_factory=list)  # Tasks that can't be done by same person on same day
    max_task_assignments: Dict[Tuple[str, str], int] = field(default_factory=dict)  # {(person_id, task_id): max_times_per_week}
    pre_assignments: List[Tuple[str, str, str]] = field(default_factory=list)  # [(person_id, task_id, day)]