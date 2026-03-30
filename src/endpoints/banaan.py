import io

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import pandas as pd

from banaan.models import Student, Instructor, BanaanConfig, normalise_discipline
from banaan.solver import BanaanSolver
from banaan.output import generate_output

router = APIRouter(prefix="/banaan")


# ── Pydantic models ─────────────────────────────────────────────────────


class InstructorInput(BaseModel):
    name: str
    discipline: str
    cwo: int = 1
    transport_capacity: int = 6
    cover_capacity: int = 6


class StudentInput(BaseModel):
    name: str
    discipline: str
    instructor: str
    wants_banana: bool
    cwo: int = 1
    age: int = 13
    friends: list[str] | None = None


class ConfigInput(BaseModel):
    boat_capacity: int = 6
    slot_duration_min: int = 15
    transit_slots: int = 1
    prep_slots: int = 1
    start_time: str = "10:30"
    end_time: str = "16:00"
    weights: dict[str, int] = {}


# ── Update endpoints ───────────────────────────────────────────────────

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
    students = list(req.students)
    idx = req.index
    if idx is None and req.name is not None:
        idx = next((i for i, s in enumerate(students) if s.name == req.name), None)
    if idx is None or idx < 0 or idx >= len(students):
        raise HTTPException(status_code=404, detail="Student not found")
    updated = students[idx].model_copy(update=req.new_values)
    students[idx] = updated
    return students

@router.post("/instructor/update", response_model=list[InstructorInput])
async def update_instructor(req: UpdateInstructorRequest):
    instructors = list(req.instructors)
    idx = req.index
    if idx is None and req.name is not None:
        idx = next((i for i, s in enumerate(instructors) if s.name == req.name), None)
    if idx is None or idx < 0 or idx >= len(instructors):
        raise HTTPException(status_code=404, detail="Instructor not found")
    updated = instructors[idx].model_copy(update=req.new_values)
    instructors[idx] = updated
    return instructors

@router.post("/config/update", response_model=ConfigInput)
async def update_config(req: UpdateConfigRequest):
    config = req.config.model_copy(update=req.new_values)
    return config


class UploadResponse(BaseModel):
    students: list[StudentInput]
    instructors: list[InstructorInput]
    config: ConfigInput


class BanaanRequest(BaseModel):
    students: list[StudentInput]
    instructors: list[InstructorInput]
    config: ConfigInput = ConfigInput()


class RideOutput(BaseModel):
    slot: int
    time: str
    students: list[str]
    count: int
    transport_instructors: list[str]


class BanaanResponse(BaseModel):
    rides: list[RideOutput]
    total_rides: int
    total_banana_students: int


# ── Helper to build domain objects ───────────────────────────────────────

def _to_domain(req: BanaanRequest) -> tuple[list[Student], list[Instructor], BanaanConfig]:
    students = [
        Student(
            name=s.name,
            discipline=normalise_discipline(s.discipline),
            instructor=s.instructor,
            wants_banana=s.wants_banana,
            cwo=s.cwo,
            age=s.age,
            friends=s.friends,
        )
        for s in req.students
    ]
    instructors = [
        Instructor(
            name=i.name,
            discipline=normalise_discipline(i.discipline),
            cwo=i.cwo,
            transport_capacity=i.transport_capacity,
            cover_capacity=i.cover_capacity,
        )
        for i in req.instructors
    ]
    cfg = req.config
    default_weights = BanaanConfig().weights
    merged_weights = {**default_weights, **cfg.weights}
    config = BanaanConfig(
        boat_capacity=cfg.boat_capacity,
        slot_duration_min=cfg.slot_duration_min,
        transit_slots=cfg.transit_slots,
        prep_slots=cfg.prep_slots,
        start_time=cfg.start_time,
        end_time=cfg.end_time,
        weights=merged_weights,
    )
    return students, instructors, config


# ── Endpoints ────────────────────────────────────────────────────────────


@router.post("/upload", response_model=UploadResponse)
async def upload_banaan(file: UploadFile):
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
    instructor_set: dict[str, str] = {}
    for _, row in df.iterrows():
        name = str(row["Name"]).strip()
        discipline = normalise_discipline(str(row["Discipline"]).strip())
        instructor = str(row["Instructor"]).strip()
        wants_banana = str(row["Will banana"]).strip().lower() in (
            "yes", "true", "1", "ja",
        )

        friend_val = row.get("Friends") if "Friends" in df.columns else row.get("Friend")
        friends = None
        if pd.notna(friend_val) and str(friend_val).strip():
            friends = [f.strip() for f in str(friend_val).split(",") if f.strip()]

        cwo = int(row["cwo"]) if "cwo" in df.columns and pd.notna(row.get("cwo")) else 1
        age = int(row["Age"]) if "Age" in df.columns and pd.notna(row.get("Age")) else 13

        students.append(StudentInput(
            name=name, discipline=discipline, instructor=instructor,
            wants_banana=wants_banana, friends=friends, cwo=cwo, age=age,
        ))
        instructor_set[instructor] = discipline

    instructors = [
        InstructorInput(name=name, discipline=disc)
        for name, disc in instructor_set.items()
    ]

    return UploadResponse(
        students=students,
        instructors=instructors,
        config=ConfigInput(),
    )


@router.post("/solve", response_model=BanaanResponse)
async def solve_banaan(req: BanaanRequest):
    students, instructors, config = _to_domain(req)

    solver = BanaanSolver(students, instructors, config)
    solution = solver.solve()

    if solution is None:
        raise HTTPException(status_code=422, detail="No feasible schedule found")

    rides = [
        RideOutput(
            slot=r.slot,
            time=solution.slot_to_time(r.slot),
            students=r.students,
            count=len(r.students),
            transport_instructors=r.transport_instructors,
        )
        for r in solution.rides
    ]

    return BanaanResponse(
        rides=rides,
        total_rides=len(solution.rides),
        total_banana_students=sum(len(r.students) for r in solution.rides),
    )


@router.post("/download")
async def download_banaan(req: BanaanRequest):
    students, instructors, config = _to_domain(req)

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
