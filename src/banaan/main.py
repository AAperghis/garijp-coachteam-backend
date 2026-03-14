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
        friend_val = row.get("Friends")
        friends = str(friend_val).strip().split(",") if pd.notna(friend_val) and str(friend_val).strip() else None
        students.append(
            Student(
                name=str(row["Name"]).strip(),
                discipline=str(row["Discipline"]).strip().lower(),
                instructor=str(row["Instructor"]).strip(),
                wants_banana=str(row["Will banana"]).strip().lower()
                in ("yes", "true", "1", "ja"),
                friends=friends,
                cwo=int(row["cwo"]) if "cwo" in row and pd.notna(row["cwo"]) else 1,
                age=int(row["Age"]) if "Age" in row and pd.notna(row["Age"]) else 13,
            )
        )
    return students



def load_instructors(path: str) -> list[Instructor]:
    """Read instructors from a CSV or XLSX file."""
    if path.endswith(".xlsx"):
        df = pd.read_excel(path)
    else:
        df = pd.read_csv(path)
    instructors: list[Instructor] = []
    for _, row in df.iterrows():
        instructors.append(
            Instructor(
                name=str(row["Name"]).strip(),
                discipline=str(row["Discipline"]).strip().lower(),
                cwo=int(row["cwo"]) if "cwo" in row and pd.notna(row["cwo"]) else 1,
                transport_capacity=int(row["transport_capacity"]) if "transport_capacity" in row and pd.notna(row["transport_capacity"]) else 6,
                cover_capacity=int(row["cover_capacity"]) if "cover_capacity" in row and pd.notna(row["cover_capacity"]) else 6,
            )
        )
    return instructors

def load_config(path: str) -> BanaanConfig:
    """Read the JSON config file and return config only."""
    with open(path, "r") as f:
        data = json.load(f)
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
    return config


def main() -> None:


    students = load_students("/home/aaperghis/software/apps/garijp-coachteam/week_2_cursisten.xlsx")
    config = load_config("src/banaan/config.json")
    instructors = load_instructors("src/banaan/example_instructors_garijp.csv")

    banana_count = sum(1 for s in students if s.wants_banana)
    print(f"Loaded {len(students)} students ({banana_count} want banana)")
    print(f"Loaded {len(instructors)} instructors")

    solver = BanaanSolver(students, instructors, config)
    print("Solving...")

    solution = solver.solve()

    # Export
    sheets = generate_output(solution)
    export_to_csv(sheets, "src/banaan/example_output.csv")


if __name__ == "__main__":
    main()
