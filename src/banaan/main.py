"""CLI entry point for the banana-boat scheduler.

Usage:
    python -m banaan.main --students students.csv --instructors instructors.csv --config config.json --output schedule.xlsx
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from .models import Student, Instructor, BanaanConfig, normalise_discipline
from .solver import BanaanSolver
from .output import generate_output, export_to_xlsx, export_to_csv


def load_students(path: str) -> list[Student]:
    """Read the student spreadsheet (CSV or XLSX)."""
    if path.endswith(".xlsx"):
        df = pd.read_excel(path)
    else:
        df = pd.read_csv(path)

    # Normalise column names: strip whitespace and lowercase
    df.columns = [c.strip() for c in df.columns]

    # Support flexible column naming
    col_map = {c.lower(): c for c in df.columns}

    def _get(row, *candidates, default=None):
        for c in candidates:
            actual = col_map.get(c.lower())
            if actual and pd.notna(row.get(actual)):
                return row[actual]
        return default

    students: list[Student] = []
    for _, row in df.iterrows():
        name = str(_get(row, "Name", "name", default="")).strip()
        if not name:
            continue

        discipline_raw = str(_get(row, "Discipline", "discipline", default="")).strip()
        discipline = normalise_discipline(discipline_raw)

        instructor = str(_get(row, "Instructor", "instructor", default="")).strip()

        wants_raw = str(_get(row, "Will banana", "will_banana", "wants_banana", "banana", default="yes")).strip().lower()
        wants_banana = wants_raw in ("yes", "true", "1", "ja")

        friend_val = _get(row, "Friends", "Friend", "friends", "friend")
        friends = None
        if friend_val is not None:
            friends = [f.strip() for f in str(friend_val).split(",") if f.strip()]
            if not friends:
                friends = None

        cwo = int(_get(row, "cwo", "CWO", default=1))
        age = int(_get(row, "Age", "age", default=13))

        students.append(Student(
            name=name,
            discipline=discipline,
            instructor=instructor,
            wants_banana=wants_banana,
            friends=friends,
            cwo=cwo,
            age=age,
        ))
    return students


def load_instructors(path: str) -> list[Instructor]:
    """Read instructors from a CSV or XLSX file."""
    if path.endswith(".xlsx"):
        df = pd.read_excel(path)
    else:
        df = pd.read_csv(path)

    df.columns = [c.strip() for c in df.columns]
    col_map = {c.lower(): c for c in df.columns}

    def _get(row, *candidates, default=None):
        for c in candidates:
            actual = col_map.get(c.lower())
            if actual and pd.notna(row.get(actual)):
                return row[actual]
        return default

    instructors: list[Instructor] = []
    for _, row in df.iterrows():
        name = str(_get(row, "Name", "name", default="")).strip()
        if not name:
            continue

        discipline_raw = str(_get(row, "Discipline", "discipline", default="")).strip()
        discipline = normalise_discipline(discipline_raw)

        instructors.append(Instructor(
            name=name,
            discipline=discipline,
            cwo=int(_get(row, "cwo", "CWO", default=1)),
            transport_capacity=int(_get(row, "transport_capacity", "Transport_capacity", default=6)),
            cover_capacity=int(_get(row, "cover_capacity", "Cover_capacity", default=6)),
        ))
    return instructors


def load_config(path: str) -> BanaanConfig:
    """Read the JSON config file and return config."""
    with open(path) as f:
        data = json.load(f)

    default_weights = BanaanConfig().weights
    loaded_weights = data.get("weights", {})
    merged_weights = {**default_weights, **loaded_weights}

    return BanaanConfig(
        boat_capacity=data.get("boat_capacity", 6),
        slot_duration_min=data.get("slot_duration_min", 15),
        transit_slots=data.get("transit_slots", 1),
        prep_slots=data.get("prep_slots", 1),
        start_time=data.get("start_time", "10:30"),
        end_time=data.get("end_time", "16:00"),
        weights=merged_weights,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Banana-boat scheduler")
    parser.add_argument("--students", required=True, help="Path to student CSV/XLSX")
    parser.add_argument("--instructors", required=True, help="Path to instructor CSV/XLSX")
    parser.add_argument("--config", default=None, help="Path to config JSON")
    parser.add_argument("--output", default="schedule", help="Output base name")
    parser.add_argument("--timeout", type=int, default=300, help="Solver timeout in seconds")
    args = parser.parse_args()

    students = load_students(args.students)
    instructors = load_instructors(args.instructors)
    config = load_config(args.config) if args.config else BanaanConfig()

    banana_count = sum(1 for s in students if s.wants_banana)
    print(f"Loaded {len(students)} students ({banana_count} want banana)")
    print(f"Loaded {len(instructors)} instructors")

    solver = BanaanSolver(students, instructors, config)
    print("Solving...")

    solution = solver.solve(timeout=args.timeout)

    if solution is None:
        print("No feasible schedule found.")
        sys.exit(1)

    print(f"Found schedule with {len(solution.rides)} banana rides")

    sheets = generate_output(solution)
    if args.output.endswith(".xlsx"):
        export_to_xlsx(sheets, args.output)
        print(f"Saved to {args.output}")
    else:
        export_to_csv(sheets, args.output)
        print(f"Saved CSV files with prefix {args.output}_")


if __name__ == "__main__":
    main()
