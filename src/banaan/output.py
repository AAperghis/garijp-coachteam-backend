"""Generate spreadsheet output from a BanaanSolution."""

from __future__ import annotations

import pandas as pd

from .models import BanaanSolution


def generate_output(
    solution: BanaanSolution,
    all_students: list | None = None,
) -> dict[str, pd.DataFrame]:
    """Build DataFrames for each output sheet.

    Returns a dict mapping sheet name → DataFrame.
    """
    sheets: dict[str, pd.DataFrame] = {}

    # ── Sheet 1: Banana Schedule ─────────────────────────────────────────
    schedule_rows = []
    for group in solution.groups:
        schedule_rows.append(
            {
                "Time": solution.slot_to_time(group.slot),
                "Group": group.index + 1,
                "Students": ", ".join(s.name for s in group.students),
                "Count": len(group.students),
                "Transport Instructor": (
                    group.transport_instructor.name
                    if group.transport_instructor
                    else ""
                ),
                "Disciplines": ", ".join(
                    sorted({s.discipline for s in group.students})
                ),
            }
        )
    sheets["Banana Schedule"] = pd.DataFrame(schedule_rows)

    # ── Sheet 2: Full Assignments ────────────────────────────────────────
    assignment_rows = []
    for group in solution.groups:
        for s in group.students:
            assignment_rows.append(
                {
                    "Name": s.name,
                    "Discipline": s.discipline,
                    "Original Instructor": s.instructor,
                    "Assignment": f"Banana Group {group.index + 1}",
                    "Time": solution.slot_to_time(group.slot),
                    "Transport Instructor": (
                        group.transport_instructor.name
                        if group.transport_instructor
                        else ""
                    ),
                }
            )
    # Handle new structure: (student_name, slot) -> [instructor_name, ...]
    for assignment in sorted(solution.non_banana_assignments, key=lambda x: (x.student.name, x.slot)):
        assignment_rows.append(
            {
                "Name": assignment.student.name,
                "Discipline": assignment.student.discipline,
                "Original Instructor": assignment.student.instructor,
                "Assignment": f"Covered by {assignment.instructor_name}",
                "Time": solution.slot_to_time(assignment.slot),
                "Transport Instructor": "",
            }
        )
    sheets["Full Assignments"] = pd.DataFrame(assignment_rows)

    # ── Sheet 3: Instructor Schedule ─────────────────────────────────────
    instructor_rows = []
    slot_dur = solution.config.slot_duration_min
    for group in solution.groups:
        inst = group.transport_instructor
        if inst is None:
            continue
        g_slot = group.slot
        # Transport out: 2 slots before ride
        depart_min = solution.start_time_minutes + (g_slot - 2) * slot_dur
        arrive_island_min = solution.start_time_minutes + (g_slot - 1) * slot_dur
        ride_min = solution.start_time_minutes + g_slot * slot_dur
        return_min = solution.start_time_minutes + (g_slot + 1) * slot_dur

        def _fmt(minutes: int) -> str:
            return f"{minutes // 60:02d}:{minutes % 60:02d}"

        instructor_rows.append(
            {
                "Instructor": inst.name,
                "Time": _fmt(depart_min),
                "Activity": f"Transport Group {group.index + 1} to island",
            }
        )
        instructor_rows.append(
            {
                "Instructor": inst.name,
                "Time": _fmt(arrive_island_min),
                "Activity": f"Group {group.index + 1} prep/wait at island",
            }
        )
        instructor_rows.append(
            {
                "Instructor": inst.name,
                "Time": _fmt(ride_min),
                "Activity": f"Group {group.index + 1} banana ride",
            }
        )
        instructor_rows.append(
            {
                "Instructor": inst.name,
                "Time": _fmt(return_min),
                "Activity": f"Transport Group {group.index + 1} back",
            }
        )
    sheets["Instructor Schedule"] = pd.DataFrame(instructor_rows)

    return sheets


def export_to_xlsx(sheets: dict[str, pd.DataFrame], filename: str) -> None:
    """Write all sheets to an Excel workbook."""
    with pd.ExcelWriter(filename, engine="openpyxl") as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=name, index=False)


def export_to_csv(sheets: dict[str, pd.DataFrame], base: str) -> None:
    """Write each sheet as a separate CSV file."""
    for name, df in sheets.items():
        safe_name = name.lower().replace(" ", "_")
        df.to_csv(f"{base}_{safe_name}.csv", index=False)
