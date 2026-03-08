import io
import json

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import pandas as pd

from roster.models import Person, Task, Roster
from roster.solver import RosterSolver
from roster.output import generate_roster_table

router = APIRouter(prefix="/roster")


# ── Pydantic models ─────────────────────────────────────────────────────


class PersonInput(BaseModel):
    id: str
    name: str
    task_weights: dict[str, float] = {}


class TaskInput(BaseModel):
    id: str
    name: str
    preferred_people: int
    min_people: int


class RosterConfig(BaseModel):
    days: list[str]
    task_conflicts: list[tuple[str, str]] = []
    max_task_assignments: dict[str, int] = {}
    pre_assignments: list[tuple[str, str, str]] = []


class UploadResponse(BaseModel):
    people: list[PersonInput]
    tasks: list[TaskInput]
    config: RosterConfig


class RosterRequest(BaseModel):
    people: list[PersonInput]
    tasks: list[TaskInput]
    config: RosterConfig


class RosterResponse(BaseModel):
    schedule: dict[str, dict[str, list[str]]]


# ── Endpoints ────────────────────────────────────────────────────────────


def _build_roster(req: RosterRequest) -> Roster:
    """Convert a RosterRequest into a Roster domain model."""
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

    max_assignments: dict[tuple[str, str], int] = {}
    for key, val in req.config.max_task_assignments.items():
        parts = key.split(":", 1)
        if len(parts) == 2:
            max_assignments[(parts[0], parts[1])] = val

    return Roster(
        people=people,
        tasks=tasks,
        days=req.config.days,
        task_conflicts=req.config.task_conflicts,
        max_task_assignments=max_assignments,
        pre_assignments=req.config.pre_assignments,
    )


@router.post("/upload", response_model=UploadResponse)
async def upload_roster(file: UploadFile):
    """Parse an uploaded JSON roster config file.

    Returns people, tasks, and config so the frontend can display
    a preview and let the user adjust parameters before solving.
    """
    contents = await file.read()

    try:
        data = json.loads(contents)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}")

    if "people" not in data or "tasks" not in data or "days" not in data:
        raise HTTPException(
            status_code=400,
            detail="JSON must contain 'people', 'tasks', and 'days' keys",
        )

    people = [
        PersonInput(
            id=p["id"],
            name=p["name"],
            task_weights=p.get("task_weights", {}),
        )
        for p in data["people"]
    ]
    tasks = [
        TaskInput(
            id=t["id"],
            name=t["name"],
            preferred_people=t["preferred_people"],
            min_people=t["min_people"],
        )
        for t in data["tasks"]
    ]

    # Normalize max_task_assignments from "p1,t1" to "p1:t1" format
    raw_max = data.get("max_task_assignments", {})
    max_assignments = {}
    for key, val in raw_max.items():
        normalized = key.replace(",", ":")
        max_assignments[normalized] = val

    config = RosterConfig(
        days=data["days"],
        task_conflicts=data.get("task_conflicts", []),
        max_task_assignments=max_assignments,
        pre_assignments=data.get("pre_assignments", []),
    )

    return UploadResponse(people=people, tasks=tasks, config=config)


@router.post("/solve", response_model=RosterResponse)
async def solve_roster(req: RosterRequest):
    """Run the solver on the (possibly edited) roster data."""
    roster = _build_roster(req)
    solver = RosterSolver(roster)
    solution = solver.solve()

    if solution is None:
        raise HTTPException(status_code=422, detail="No feasible roster found")

    return RosterResponse(schedule=solution)


@router.post("/download")
async def download_roster(req: RosterRequest):
    """Solve and return the result as a downloadable XLSX file."""
    roster = _build_roster(req)
    solver = RosterSolver(roster)
    solution = solver.solve()

    if solution is None:
        raise HTTPException(status_code=422, detail="No feasible roster found")

    df = generate_roster_table(solution, roster)

    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=roster.xlsx"},
    )
