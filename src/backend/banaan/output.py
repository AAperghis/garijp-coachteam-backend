"""Generate spreadsheet output from a BananaSolution."""

from __future__ import annotations

from collections import defaultdict

import pandas as pd

from backend.banaan.models import BananaSolution, StudentState, InstructorState


def generate_output(solution: BananaSolution) -> dict[str, pd.DataFrame]:
    """Build DataFrames for each output sheet.

    Returns a dict mapping sheet name → DataFrame.
    """
    sheets: dict[str, pd.DataFrame] = {}
    cfg = solution.config
    T = cfg.total_slots
    times = [cfg.slot_to_time(t) for t in range(T)]

    # ── Sheet 1: Banana Schedule ─────────────────────────────────────────
    schedule_rows = []
    for ride in solution.rides:
        # Group students by their transport instructor
        by_instructor: dict[str, list[str]] = defaultdict(list)
        for sname in ride.students:
            inst = ride.student_transport.get(sname, "?")
            by_instructor[inst].append(sname)
        groups = []
        for inst in sorted(by_instructor.keys()):
            kids = ", ".join(by_instructor[inst])
            groups.append(f"{inst}: [{kids}]")
        schedule_rows.append({
            "Time": solution.slot_to_time(ride.slot),
            "Slot": ride.slot,
            "Students": ", ".join(ride.students),
            "Count": len(ride.students),
            "Transport Instructors": ", ".join(ride.transport_instructors),
            "Transport Groups": "; ".join(groups),
        })
    sheets["Banana Schedule"] = pd.DataFrame(schedule_rows)

    # ── Sheet 2: Full Assignments ────────────────────────────────────────
    assignment_rows = []
    for name, entries in sorted(solution.student_schedules.items()):
        for entry in entries:
            assignment_rows.append({
                "Name": name,
                "Time": solution.slot_to_time(entry.slot),
                "State": entry.state.value,
                "Instructor": entry.instructor or "",
            })
    sheets["Full Assignments"] = pd.DataFrame(assignment_rows)

    # ── Sheet 3: Instructor Schedule ─────────────────────────────────────
    instructor_rows = []
    for name, entries in sorted(solution.instructor_schedules.items()):
        for entry in entries:
            instructor_rows.append({
                "Instructor": name,
                "Time": solution.slot_to_time(entry.slot),
                "State": entry.state.value,
                "Details": entry.details,
            })
    sheets["Instructor Schedule"] = pd.DataFrame(instructor_rows)

    # ── Sheet 4: Instructor Timeline Grid ────────────────────────────────
    # Rows = instructors, Columns = time slots.  Each cell shows a compact
    # label: "→island", "🏝", "🍌 6 kids", "←back", "⛵ 8 kids", etc.
    inst_grid: dict[str, dict[str, str]] = {}
    for name, entries in sorted(solution.instructor_schedules.items()):
        row: dict[str, str] = {}
        for entry in entries:
            t = solution.slot_to_time(entry.slot)
            state = entry.state
            det = entry.details
            if state == InstructorState.TRANSPORTING_TO:
                row[t] = "→ island"
            elif state == InstructorState.ON_ISLAND:
                row[t] = "🏝️ island"
            elif state == InstructorState.TRANSPORTING_FROM:
                row[t] = "← back"
            elif state == InstructorState.INSTRUCTING:
                row[t] = det if det else "free"
            else:
                row[t] = det if det else state.value
        inst_grid[name] = row
    inst_df = pd.DataFrame.from_dict(inst_grid, orient="index")
    inst_df.columns.name = "Time"
    inst_df.index.name = "Instructor"
    # Reorder columns to match time order
    inst_df = inst_df.reindex(columns=times)
    sheets["Instructor Timeline"] = inst_df.reset_index()

    # ── Sheet 5: Student Timeline Grid ───────────────────────────────────
    # Rows = students, Columns = time slots.  Shows state + instructor.
    STATE_SYMBOLS = {
        StudentState.SAILING: "⛵",
        StudentState.TRANSIT_TO: "→",
        StudentState.ON_ISLAND: "🏝️",
        StudentState.PREP: "⏳",
        StudentState.ON_BANANA: "🍌",
        StudentState.TRANSIT_FROM: "←",
    }
    stud_grid: dict[str, dict[str, str]] = {}
    for name, entries in sorted(solution.student_schedules.items()):
        row: dict[str, str] = {}
        for entry in entries:
            t = solution.slot_to_time(entry.slot)
            sym = STATE_SYMBOLS.get(entry.state, "?")
            if entry.state == StudentState.SAILING and entry.instructor:
                row[t] = f"⛵ {entry.instructor}"
            else:
                row[t] = sym
        stud_grid[name] = row
    stud_df = pd.DataFrame.from_dict(stud_grid, orient="index")
    stud_df.columns.name = "Time"
    stud_df.index.name = "Student"
    stud_df = stud_df.reindex(columns=times)
    sheets["Student Timeline"] = stud_df.reset_index()

    # ── Sheet 6: Coverage Summary ────────────────────────────────────────
    # Per instructor per slot: how many students they cover + names.
    coverage: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for name, entries in solution.student_schedules.items():
        for entry in entries:
            if entry.state == StudentState.SAILING and entry.instructor:
                t = solution.slot_to_time(entry.slot)
                coverage[entry.instructor][t] += 1

    cov_rows = []
    for inst_name in sorted(coverage.keys()):
        row = {"Instructor": inst_name}
        for t in times:
            row[t] = coverage[inst_name].get(t, 0)
        cov_rows.append(row)
    sheets["Coverage Grid"] = pd.DataFrame(cov_rows)

    # ── Sheet 7: Statistics ──────────────────────────────────────────────
    total_students = len(solution.student_schedules)
    banana_students = sum(
        1 for entries in solution.student_schedules.values()
        if any(e.state == StudentState.ON_BANANA for e in entries)
    )
    total_rides = len(solution.rides)
    ride_sizes = [len(r.students) for r in solution.rides]
    instructors_going = sum(
        1 for entries in solution.instructor_schedules.values()
        if any(e.state == InstructorState.TRANSPORTING_TO for e in entries)
    )

    # Count coverage transitions
    total_switches = 0
    students_with_switch = 0
    for name, entries in solution.student_schedules.items():
        prev_inst = None
        switched = False
        for entry in entries:
            if entry.state == StudentState.SAILING and entry.instructor:
                if prev_inst and entry.instructor != prev_inst:
                    total_switches += 1
                    switched = True
                prev_inst = entry.instructor
            else:
                prev_inst = None
        if switched:
            students_with_switch += 1

    # Ride time span
    if solution.rides:
        first_time = solution.slot_to_time(solution.rides[0].slot)
        last_time = solution.slot_to_time(solution.rides[-1].slot)
    else:
        first_time = last_time = "-"

    stats = [
        {"Metric": "Total students", "Value": total_students},
        {"Metric": "Banana students", "Value": banana_students},
        {"Metric": "Total banana rides", "Value": total_rides},
        {"Metric": "Avg group size", "Value": f"{sum(ride_sizes) / len(ride_sizes):.1f}" if ride_sizes else "0"},
        {"Metric": "Min group size", "Value": min(ride_sizes) if ride_sizes else 0},
        {"Metric": "Max group size", "Value": max(ride_sizes) if ride_sizes else 0},
        {"Metric": "First ride", "Value": first_time},
        {"Metric": "Last ride", "Value": last_time},
        {"Metric": "Instructors going to island", "Value": instructors_going},
        {"Metric": "Coverage transitions", "Value": total_switches},
        {"Metric": "Students with instructor switch", "Value": students_with_switch},
    ]
    sheets["Statistics"] = pd.DataFrame(stats)

    # ── Sheet 8: Transfers ───────────────────────────────────────────────
    # Every time a student's covering instructor changes, that's a physical
    # transfer.  Also tracks transport to/from island.
    transfer_rows = []
    for name, entries in sorted(solution.student_schedules.items()):
        prev_inst = None
        prev_state = None
        for entry in entries:
            t = solution.slot_to_time(entry.slot)
            state = entry.state

            if state == StudentState.TRANSIT_TO:
                # Student is being taken to the island — find their specific transport instructor
                transport_inst = None
                for ride in solution.rides:
                    if name in ride.students:
                        transport_inst = ride.student_transport.get(name)
                        break
                transfer_rows.append({
                    "Time": t,
                    "Student": name,
                    "Type": "To island",
                    "From": prev_inst or "(own instructor)",
                    "To": transport_inst or "transport",
                    "Reason": "Banana transport",
                })
                prev_inst = None

            elif state == StudentState.TRANSIT_FROM:
                pass  # will be handled when they resume sailing

            elif state == StudentState.SAILING and entry.instructor:
                if prev_state in (StudentState.TRANSIT_FROM, StudentState.ON_ISLAND, StudentState.ON_BANANA):
                    # Coming back from island
                    transfer_rows.append({
                        "Time": t,
                        "Student": name,
                        "Type": "From island",
                        "From": "island",
                        "To": entry.instructor,
                        "Reason": "Return from banana",
                    })
                elif prev_inst and entry.instructor != prev_inst:
                    # Instructor switch while sailing
                    transfer_rows.append({
                        "Time": t,
                        "Student": name,
                        "Type": "Reassign",
                        "From": prev_inst,
                        "To": entry.instructor,
                        "Reason": "Instructor unavailable",
                    })
                prev_inst = entry.instructor

            prev_state = state

    # Sort by time, then type
    if transfer_rows:
        df_transfers = pd.DataFrame(transfer_rows)
        # Add a sort key based on time
        df_transfers["_sort"] = df_transfers["Time"].apply(
            lambda x: int(x.split(":")[0]) * 60 + int(x.split(":")[1])
        )
        df_transfers = df_transfers.sort_values(["_sort", "Type", "Student"]).drop(columns=["_sort"])
        sheets["Transfers"] = df_transfers.reset_index(drop=True)
    else:
        sheets["Transfers"] = pd.DataFrame(columns=["Time", "Student", "Type", "From", "To", "Reason"])

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
