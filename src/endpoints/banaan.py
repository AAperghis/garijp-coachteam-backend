from fastapi import APIRouter
from pydantic import BaseModel

from banaan.models import Student, Instructor, BanaanConfig
from banaan.solver import BanaanSolver

router = APIRouter(prefix="/banaan")


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


class BanaanRequest(BaseModel):
    students: list[StudentInput]
    instructors: list[InstructorInput]
    boat_capacity: int = 6
    slot_duration_min: int = 15
    prep_time_min: int = 15
    transport_time_min: int = 15
    start_time: str = "10:30"
    end_time: str = "16:00"
    weights: dict[str, int] = {"instructor_switch": 10, "discipline_switch": 50}


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


@router.post("/solve", response_model=BanaanResponse)
async def solve_banaan(req: BanaanRequest):
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
    config = BanaanConfig(
        boat_capacity=req.boat_capacity,
        slot_duration_min=req.slot_duration_min,
        prep_time_min=req.prep_time_min,
        transport_time_min=req.transport_time_min,
        start_time=req.start_time,
        end_time=req.end_time,
        weights=req.weights,
    )

    solver = BanaanSolver(students, instructors, config)
    solution = solver.solve()

    if solution is None:
        from fastapi import HTTPException
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
