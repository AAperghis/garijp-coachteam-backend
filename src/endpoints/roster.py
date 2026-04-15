import io
import json

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import pandas as pd
import openpyxl  # noqa: F401 — ensures openpyxl engine is available for pd.read_excel

from src.backend.roster.models import Person, Task, Roster
from src.backend.roster.solver import RosterSolver
from src.backend.roster.output import generate_roster_table

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


def _upload_from_json(contents: bytes) -> UploadResponse:
    """Parse a JSON roster config file."""
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


def _upload_from_xlsx(contents: bytes) -> UploadResponse:
    """Parse an XLSX file with two sheets: 'People' and 'Tasks'.

    People sheet columns:
        id        — unique person identifier
        name      — display name
        <task_id> — one column per task; value is the preference weight (float)
                    extra columns whose names do not match any task id are ignored.

    Tasks sheet columns:
        id                — unique task identifier
        name              — display name
        preferred_people  — target headcount
        min_people        — minimum required headcount

    Config (days, conflicts, pre-assignments) cannot be expressed in this flat
    format and will be returned as empty defaults for the user to fill in on the
    frontend.
    """
    try:
        xl = pd.read_excel(io.BytesIO(contents), sheet_name=None, engine="openpyxl")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not parse XLSX: {exc}")

    # ── Sheet name matching (case-insensitive) ────────────────────────────
    sheet_map = {k.strip().lower(): k for k in xl}

    if "people" not in sheet_map:
        raise HTTPException(status_code=400, detail="XLSX must contain a 'People' sheet")
    if "tasks" not in sheet_map:
        raise HTTPException(status_code=400, detail="XLSX must contain a 'Tasks' sheet")

    people_df = xl[sheet_map["people"]]
    tasks_df = xl[sheet_map["tasks"]]

    # ── Validate required columns ─────────────────────────────────────────
    people_required = {"id", "name"}
    missing = people_required - {c.strip().lower() for c in people_df.columns}
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"People sheet missing columns: {', '.join(sorted(missing))}",
        )

    tasks_required = {"id", "name", "preferred_people", "min_people"}
    missing = tasks_required - {c.strip().lower() for c in tasks_df.columns}
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Tasks sheet missing columns: {', '.join(sorted(missing))}",
        )

    # ── Normalise column names ────────────────────────────────────────────
    people_df.columns = [c.strip().lower() for c in people_df.columns]
    tasks_df.columns = [c.strip().lower() for c in tasks_df.columns]

    # ── Parse tasks first so we know valid task ids ───────────────────────
    tasks: list[TaskInput] = []
    task_ids: set[str] = set()
    for _, row in tasks_df.iterrows():
        tid = str(row["id"]).strip()
        task_ids.add(tid)
        tasks.append(TaskInput(
            id=tid,
            name=str(row["name"]).strip(),
            preferred_people=int(row["preferred_people"]),
            min_people=int(row["min_people"]),
        ))

    # ── Parse people; extra columns → task weights ────────────────────────
    weight_cols = [c for c in people_df.columns if c not in ("id", "name") and c in task_ids]
    people: list[PersonInput] = []
    for _, row in people_df.iterrows():
        task_weights: dict[str, float] = {}
        for col in weight_cols:
            val = row[col]
            if pd.notna(val):
                try:
                    task_weights[col] = float(val)
                except (ValueError, TypeError):
                    pass
        people.append(PersonInput(
            id=str(row["id"]).strip(),
            name=str(row["name"]).strip(),
            task_weights=task_weights,
        ))

    config = RosterConfig(days=[])
    return UploadResponse(people=people, tasks=tasks, config=config)


def _upload_from_csv(contents: bytes) -> UploadResponse:
    """Parse a single CSV as a people list.

    Expected columns: id, name, <task_id_1>, <task_id_2>, ...
    Task columns are any columns beyond id and name; their names become task ids
    and auto-populated tasks with preferred_people=1, min_people=1.

    This is a convenience format; use XLSX with a Tasks sheet for full control.
    """
    try:
        df = pd.read_csv(io.BytesIO(contents))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not parse CSV: {exc}")

    df.columns = [c.strip().lower() for c in df.columns]

    required = {"id", "name"}
    missing = required - set(df.columns)
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"CSV missing columns: {', '.join(sorted(missing))}",
        )

    weight_cols = [c for c in df.columns if c not in ("id", "name")]

    tasks = [
        TaskInput(id=col, name=col.replace("_", " ").title(), preferred_people=1, min_people=1)
        for col in weight_cols
    ]

    people: list[PersonInput] = []
    for _, row in df.iterrows():
        task_weights: dict[str, float] = {}
        for col in weight_cols:
            val = row[col]
            if pd.notna(val):
                try:
                    task_weights[col] = float(val)
                except (ValueError, TypeError):
                    pass
        people.append(PersonInput(
            id=str(row["id"]).strip(),
            name=str(row["name"]).strip(),
            task_weights=task_weights,
        ))

    config = RosterConfig(days=[])
    return UploadResponse(people=people, tasks=tasks, config=config)


@router.post("/upload", response_model=UploadResponse)
async def upload_roster(file: UploadFile):
    """Parse an uploaded roster file and return structured data for the frontend.

    Supported formats:

    **JSON** — Full config including days, conflicts, pre-assignments.
    Must contain 'people', 'tasks', and 'days' keys (existing format).

    **XLSX** — Two sheets required:
      - *People*: columns `id`, `name`, plus one column per task id with preference weight.
      - *Tasks*: columns `id`, `name`, `preferred_people`, `min_people`.
    Config (days, conflicts, pre-assignments) returned as empty defaults to fill in on the frontend.

    **CSV** — People only (flat format). Columns: `id`, `name`, extra columns = task weights.
    Tasks are auto-created from column names. Config returned as empty defaults.
    """
    contents = await file.read()
    filename = (file.filename or "").lower()

    if filename.endswith(".json"):
        return _upload_from_json(contents)
    if filename.endswith(".xlsx"):
        return _upload_from_xlsx(contents)
    if filename.endswith(".csv"):
        return _upload_from_csv(contents)

    # Fallback: try JSON first, then CSV
    try:
        return _upload_from_json(contents)
    except HTTPException:
        return _upload_from_csv(contents)


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
