import argparse
import json
from backend.roster.models import Person, Task, Roster
from backend.roster.solver import RosterSolver
from backend.roster.output import generate_roster_table, export_roster

def load_data(config_file):
    """Load roster configuration from JSON file"""
    with open(config_file, 'r') as f:
        data = json.load(f)
    
    # Create people
    people = [
        Person(
            id=p["id"],
            name=p["name"],
            task_weights=p.get("task_weights", {})
        )
        for p in data["people"]
    ]
    
    # Create tasks
    tasks = [
        Task(
            id=t["id"],
            name=t["name"],
            preferred_people=t["preferred_people"],
            min_people=t["min_people"]
        )
        for t in data["tasks"]
    ]
    
    # Create roster with constraints
    roster = Roster(
        people=people,
        tasks=tasks,
        days=data["days"],
        task_conflicts=data.get("task_conflicts", []),
        max_task_assignments=data.get("max_task_assignments", {}),
        pre_assignments=data.get("pre_assignments", [])
    )
    
    return roster

def main():
    parser = argparse.ArgumentParser(description="Generate optimal task roster")
    parser.add_argument("--config", required=True, help="Path to roster configuration file")
    parser.add_argument("--output", default="roster", help="Output filename base")
    args = parser.parse_args()
    
    # Load data
    roster = load_data(args.config)
    
    # Solve the problem
    solver = RosterSolver(roster)
    solution = solver.solve()
    
    if solution:
        # Generate output
        roster_table = generate_roster_table(solution, roster)
        print("\nGenerated Roster:")
        print(roster_table)
        
        # Export
        export_roster(roster_table, args.output)
        print(f"\nRoster exported to {args.output}.csv and {args.output}.xlsx")
    else:
        print("No feasible solution found. Try relaxing some constraints.")

if __name__ == "__main__":
    main()