"""CLI entry point for the banana-boat scheduler.

Usage:
    cd backend/src/banaan
    python main.py --input example_input.csv --config config.json --output schedule.xlsx
"""

from __future__ import annotations

import argparse
import json
import sys

import pandas as pd

from .models import Student, Instructor, BanaanConfig
from .solver import BanaanSolver
from .output import generate_output, export_to_xlsx, export_to_csv


def load_students(path: str) -> list[Student]:
    """Read the student spreadsheet (CSV or XLSX)."""
    if path.endswith(".xlsx"):
        df = pd.read_excel(path)
    else:
        df = pd.read_csv(path)

    students: list[Student] = []
    for _, row in df.iterrows():
        friend_val = row.get("Friend")
        friend = (
            str(friend_val).strip()
            if pd.notna(friend_val) and str(friend_val).strip()
            else None
        )
        students.append(
            Student(
                name=str(row["Name"]).strip(),
                discipline=str(row["Discipline"]).strip().lower(),
                instructor=str(row["Instructor"]).strip(),
                wants_banana=str(row["Will banana"]).strip().lower()
                in ("yes", "true", "1", "ja"),
                friend=friend,
            )
        )
    return students


def load_config(path: str) -> tuple[list[Instructor], BanaanConfig]:
    """Read the JSON config file and return instructors + config."""
    with open(path, "r") as f:
        data = json.load(f)

    instructors = [
        Instructor(
            name=name,
            discipline=info["discipline"],
            transport_capacity=info["transport_capacity"],
        )
        for name, info in data.get("instructors", {}).items()
    ]

    config = BanaanConfig(
        boat_capacity=data.get("boat_capacity", 6),
        slot_duration_min=data.get("slot_duration_min", 15),
        prep_time_min=data.get("prep_time_min", 15),
        transport_time_min=data.get("transport_time_min", 15),
        start_time=data.get("start_time", "10:30"),
        end_time=data.get("end_time", "16:00"),
        weights=data.get(
            "weights",
            {"instructor_switch": 10, "discipline_switch": 50},
        ),
    )
    return instructors, config


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate an optimal banana-boat schedule"
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to student spreadsheet (CSV or XLSX)",
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to JSON config file",
    )
    parser.add_argument(
        "--output",
        default="schedule.xlsx",
        help="Output filename (.xlsx or base name for CSVs)",
    )
    args = parser.parse_args()

    students = load_students(args.input)
    instructors, config = load_config(args.config)

    banana_count = sum(1 for s in students if s.wants_banana)
    print(f"Loaded {len(students)} students ({banana_count} want banana)")
    print(f"Loaded {len(instructors)} instructors")

    solver = BanaanSolver(students, instructors, config)
    print(f"Need {solver.total_groups} banana groups across 3 phases")
    print("Solving...")

    solution = solver.solve()

    if solution is None:
        print("No feasible solution found. Check constraints and input data.")
        sys.exit(1)

    # Print summary
    print(f"\nSolution found! {len(solution.groups)} groups:")
    for g in solution.groups:
        inst_name = g.transport_instructor.name if g.transport_instructor else "?"
        names = ", ".join(s.name for s in g.students)
        print(
            f"  Group {g.index + 1} @ {solution.slot_to_time(g.slot)}: "
            f"[{inst_name}] {names}"
        )

    print(f"\nNon-banana students ({len(solution.non_banana_assignments)}):")
    for s_name, i_name in sorted(solution.non_banana_assignments.items()):
        print(f"  {s_name} → {i_name}")

    # Export
    sheets = generate_output(solution)
    if args.output.endswith(".xlsx"):
        export_to_xlsx(sheets, args.output)
        print(f"\nSchedule exported to {args.output}")
    else:
        export_to_csv(sheets, args.output)
        print(f"\nSchedule exported as CSV files with base name {args.output}")


if __name__ == "__main__":
    main()
