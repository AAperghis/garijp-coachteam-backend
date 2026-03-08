from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from roster.models import Person, Task, Roster
from roster.solver import RosterSolver

router = APIRouter(prefix="/roster")


class PersonInput(BaseModel):
    id: str
    name: str
    task_weights: dict[str, float] = {}


class TaskInput(BaseModel):
    id: str
    name: str
    preferred_people: int
    min_people: int


class RosterRequest(BaseModel):
    people: list[PersonInput]
    tasks: list[TaskInput]
    days: list[str]
    task_conflicts: list[tuple[str, str]] = []
    max_task_assignments: dict[str, int] = {}
    pre_assignments: list[tuple[str, str, str]] = []


class RosterResponse(BaseModel):
    schedule: dict[str, dict[str, list[str]]]


@router.post("/solve", response_model=RosterResponse)
async def solve_roster(req: RosterRequest):
    people = [
        Person(id=p.id, name=p.name, task_weights=p.task_weights)
        for p in req.people
    ]
    tasks = [
        Task(
            id=t.id,
            name=t.name,
            preferred_people=t.preferred_people,
            min_people=t.min_people,
        )
        for t in req.tasks
    ]

    # Convert max_task_assignments from flat "person_id:task_id" keys to tuple keys
    max_assignments: dict[tuple[str, str], int] = {}
    for key, val in req.max_task_assignments.items():
        parts = key.split(":", 1)
        if len(parts) == 2:
            max_assignments[(parts[0], parts[1])] = val

    roster = Roster(
        people=people,
        tasks=tasks,
        days=req.days,
        task_conflicts=req.task_conflicts,
        max_task_assignments=max_assignments,
        pre_assignments=req.pre_assignments,
    )

    solver = RosterSolver(roster)
    solution = solver.solve()

    if solution is None:
        raise HTTPException(status_code=422, detail="No feasible roster found")

    return RosterResponse(schedule=solution)
