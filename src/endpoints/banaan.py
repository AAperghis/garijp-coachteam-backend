import io

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import pandas as pd

from banaan.models import Student, Instructor, BanaanConfig, BanaanGroup, BanaanSolution
from banaan.solver import BanaanSolver
from banaan.output import generate_output, export_to_xlsx

router = APIRouter(prefix="/banaan")


# ── Pydantic models ─────────────────────────────────────────────────────


class InstructorInput(BaseModel):
    name: str
    discipline: str
    transport_capacity: int


class StudentInput(BaseModel):
    name: str
    discipline: str
    instructor: str
    wants_banana: bool
    friend: str | None = None


class ConfigInput(BaseModel):
    boat_capacity: int = 6
    slot_duration_min: int = 15
    prep_time_min: int = 15
    transport_time_min: int = 15
    start_time: str = "10:30"
    end_time: str = "16:00"
    weights: dict[str, int] = {"instructor_switch": 10, "discipline_switch": 50}


# ── Update endpoints ───────────────────────────────────────────────────

from fastapi import Body
from typing import Optional

class UpdateStudentRequest(BaseModel):
    students: list[StudentInput]
    index: Optional[int] = None
    name: Optional[str] = None
    new_values: dict

class UpdateInstructorRequest(BaseModel):
    instructors: list[InstructorInput]
    index: Optional[int] = None
    name: Optional[str] = None
    new_values: dict

class UpdateConfigRequest(BaseModel):
    config: ConfigInput
    new_values: dict

@router.post("/student/update", response_model=list[StudentInput])
async def update_student(req: UpdateStudentRequest):
    """Update a student by index or name."""
    students = req.students.copy()
    idx = req.index
    if idx is None and req.name is not None:
        idx = next((i for i, s in enumerate(students) if s.name == req.name), None)
    if idx is None or idx < 0 or idx >= len(students):
        raise HTTPException(status_code=404, detail="Student not found")
    updated = students[idx].copy(update=req.new_values)
    students[idx] = updated
    return students

@router.post("/instructor/update", response_model=list[InstructorInput])
async def update_instructor(req: UpdateInstructorRequest):
    """Update an instructor by index or name."""
    instructors = req.instructors.copy()
    idx = req.index
    if idx is None and req.name is not None:
        idx = next((i for i, s in enumerate(instructors) if s.name == req.name), None)
    if idx is None or idx < 0 or idx >= len(instructors):
        raise HTTPException(status_code=404, detail="Instructor not found")
    updated = instructors[idx].copy(update=req.new_values)
    instructors[idx] = updated
    return instructors

@router.post("/config/update", response_model=ConfigInput)
async def update_config(req: UpdateConfigRequest):
    """Update config values."""
    config = req.config.copy(update=req.new_values)
    return config


class UploadResponse(BaseModel):
    students: list[StudentInput]
    instructors: list[InstructorInput]
    config: ConfigInput


class BanaanRequest(BaseModel):
    students: list[StudentInput]
    instructors: list[InstructorInput]
    config: ConfigInput = ConfigInput()


class GroupOutput(BaseModel):
    index: int
    slot: int
    time: str
    phase: int
    students: list[str]
    disciplines: list[str]
    transport_instructor: str | None


class BanaanResponse(BaseModel):
    groups: list[GroupOutput]
    non_banana_assignments: dict[str, str]
    total_groups: int
    total_banana_students: int


# ── Endpoints ────────────────────────────────────────────────────────────


@router.post("/upload", response_model=UploadResponse)
async def upload_banaan(file: UploadFile):
    """Parse an uploaded CSV/XLSX student file.

    Returns the student list, extracted instructor list, and default config
    so the frontend can display a preview and let the user adjust parameters.
    """
    contents = await file.read()
    filename = file.filename or ""

    try:
        if filename.endswith(".xlsx"):
            df = pd.read_excel(io.BytesIO(contents))
        else:
            df = pd.read_csv(io.BytesIO(contents))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not parse file: {exc}")

    required_cols = {"Name", "Discipline", "Instructor", "Will banana"}
    missing = required_cols - set(df.columns)
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing columns: {', '.join(sorted(missing))}",
        )

    students: list[StudentInput] = []
    instructor_set: dict[str, str] = {}  # name -> discipline
    for _, row in df.iterrows():
        friend_val = row.get("Friend")
        friend = (
            str(friend_val).strip()
            if pd.notna(friend_val) and str(friend_val).strip()
            else None
        )
        name = str(row["Name"]).strip()
        discipline = str(row["Discipline"]).strip().lower()
        instructor = str(row["Instructor"]).strip()
        wants_banana = str(row["Will banana"]).strip().lower() in (
            "yes", "true", "1", "ja",
        )
        students.append(
            StudentInput(
                name=name,
                discipline=discipline,
                instructor=instructor,
                wants_banana=wants_banana,
                friend=friend,
            )
        )
        instructor_set[instructor] = discipline

    instructors = [
        InstructorInput(name=name, discipline=disc, transport_capacity=6)
        for name, disc in instructor_set.items()
    ]

    return UploadResponse(
        students=students,
        instructors=instructors,
        config=ConfigInput(),
    )


@router.post("/solve", response_model=BanaanResponse)
async def solve_banaan(req: BanaanRequest):
    """Run the solver on the (possibly edited) student/instructor/config data."""
    students = [
        Student(
            name=s.name,
            discipline=s.discipline,
            instructor=s.instructor,
            wants_banana=s.wants_banana,
            friend=s.friend,
        )
        for s in req.students
    ]
    instructors = [
        Instructor(
            name=i.name,
            discipline=i.discipline,
            transport_capacity=i.transport_capacity,
        )
        for i in req.instructors
    ]
    cfg = req.config
    config = BanaanConfig(
        boat_capacity=cfg.boat_capacity,
        slot_duration_min=cfg.slot_duration_min,
        prep_time_min=cfg.prep_time_min,
        transport_time_min=cfg.transport_time_min,
        start_time=cfg.start_time,
        end_time=cfg.end_time,
        weights=cfg.weights,
    )

    solver = BanaanSolver(students, instructors, config)
    solution = solver.solve()

    if solution is None:
        raise HTTPException(status_code=422, detail="No feasible schedule found")

    groups = [
        GroupOutput(
            index=g.index,
            slot=g.slot,
            time=solution.slot_to_time(g.slot),
            phase=g.phase,
            students=[s.name for s in g.students],
            disciplines=sorted({s.discipline for s in g.students}),
            transport_instructor=(
                g.transport_instructor.name if g.transport_instructor else None
            ),
        )
        for g in solution.groups
    ]

    return BanaanResponse(
        groups=groups,
        non_banana_assignments=solution.non_banana_assignments,
        total_groups=len(solution.groups),
        total_banana_students=sum(len(g.students) for g in solution.groups),
    )


@router.post("/download")
async def download_banaan(req: BanaanRequest):
    """Solve and return the result as a downloadable XLSX file."""
    # Re-use the solve logic
    students = [
        Student(
            name=s.name,
            discipline=s.discipline,
            instructor=s.instructor,
            wants_banana=s.wants_banana,
            friend=s.friend,
        )
        for s in req.students
    ]
    instructors = [
        Instructor(
            name=i.name,
            discipline=i.discipline,
            transport_capacity=i.transport_capacity,
        )
        for i in req.instructors
    ]
    cfg = req.config
    config = BanaanConfig(
        boat_capacity=cfg.boat_capacity,
        slot_duration_min=cfg.slot_duration_min,
        prep_time_min=cfg.prep_time_min,
        transport_time_min=cfg.transport_time_min,
        start_time=cfg.start_time,
        end_time=cfg.end_time,
        weights=cfg.weights,
    )

    solver = BanaanSolver(students, instructors, config)
    solution = solver.solve()

    if solution is None:
        raise HTTPException(status_code=422, detail="No feasible schedule found")

    sheets = generate_output(solution)

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=name, index=False)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=banaan_schedule.xlsx"},
    )
