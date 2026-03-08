import pandas as pd
from .models import Roster
from typing import Dict

def generate_roster_table(solution: Dict, roster: Roster) -> pd.DataFrame:
    """Generate a human-readable roster table"""
    # Create rows for each day
    rows = []
    for day in roster.days:
        row = {'Day': day}
        
        # Add tasks as columns
        for task in roster.tasks:
            assigned_people = solution[day][task.id]
            # Map IDs to names
            assigned_names = [
                next(p.name for p in roster.people if p.id == pid)
                for pid in assigned_people
            ]
            row[task.name] = ", ".join(assigned_names) if assigned_names else "N/A"
        
        rows.append(row)
    
    # Create DataFrame
    return pd.DataFrame(rows)

def export_roster(df: pd.DataFrame, filename: str = "roster", formats: list = ["csv", "xlsx"]):
    """Export the roster to various formats"""
    for fmt in formats:
        if fmt == "csv":
            df.to_csv(f"{filename}.csv", index=False)
        elif fmt == "xlsx":
            df.to_excel(f"{filename}.xlsx", index=False)
        # Add more formats as needed