from ortools.sat.python import cp_model
from backend.roster.models import Roster
from typing import Dict, List, Tuple, Optional

class RosterSolver:
    def __init__(self, roster: Roster):
        self.roster = roster
        self.model = cp_model.CpModel()
        self.vars: Dict[Tuple[str, str, str], cp_model.IntVar] = {}
    
    def solve(self) -> Optional[Dict]:
        """Run the solver and return a solution if found"""
        # Create variables: x[person_id][task_id][day] = 1 if person assigned to task on day
        for person in self.roster.people:
            for task in self.roster.tasks:
                for day in self.roster.days:
                    var_name = f"x_{person.id}_{task.id}_{day}"
                    self.vars[(person.id, task.id, day)] = self.model.NewBoolVar(var_name)
        
        # Add constraints
        self._add_min_people_constraints()
        self._add_preferred_people_constraints()
        self._add_task_conflict_constraints()
        self._add_max_assignments_constraints()
        self._add_pre_assignment_constraints()
        self._add_task_block_constraints()
        
        # Set objective function
        self._set_objective()
        
        # Solve
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 30
        status = solver.Solve(self.model)
        
        # Process results
        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            return self._extract_solution(solver)
        else:
            return None
    
    def _add_min_people_constraints(self):
        """Ensure each task has at least min_people assigned each day"""
        for task in self.roster.tasks:
            for day in self.roster.days:
                task_assignments = [
                    self.vars[(person.id, task.id, day)]
                    for person in self.roster.people
                ]
                self.model.Add(sum(task_assignments) >= task.min_people)

    def _add_preferred_people_constraints(self):
        """Ensure each task has at most preferred_people assigned each day"""
        for task in self.roster.tasks:
            for day in self.roster.days:
                task_assignments = [
                    self.vars[(person.id, task.id, day)]
                    for person in self.roster.people
                ]
                self.model.Add(sum(task_assignments) <= task.preferred_people)
    
    def _add_task_conflict_constraints(self):
        """Ensure people can't do conflicting tasks on the same day"""
        for task1_id, task2_id in self.roster.task_conflicts:
            for person in self.roster.people:
                for day in self.roster.days:
                    self.model.Add(
                        self.vars[(person.id, task1_id, day)] + 
                        self.vars[(person.id, task2_id, day)] <= 1
                    )
    
    def _add_max_assignments_constraints(self):
        """Limit how many times each person can do each task in a week"""
        for (person_id, task_id), max_count in self.roster.max_task_assignments.items():
            assignments = [
                self.vars[(person_id, task_id, day)]
                for day in self.roster.days
            ]
            self.model.Add(sum(assignments) <= max_count)
    
    def _add_pre_assignment_constraints(self):
        """Handle pre-assigned tasks"""
        for person_id, task_id, day in self.roster.pre_assignments:
            self.model.Add(self.vars[(person_id, task_id, day)] == 1)
    
    def _add_task_block_constraints(self):
        """Block specific person-task(-day) assignments"""
        for person_id, task_id, day in self.roster.task_blocks:
            if day:  # specific day
                key = (person_id, task_id, day)
                if key in self.vars:
                    self.model.Add(self.vars[key] == 0)
            else:  # all days
                for d in self.roster.days:
                    key = (person_id, task_id, d)
                    if key in self.vars:
                        self.model.Add(self.vars[key] == 0)

    def _set_objective(self):
        """Objective with soft constraints:
        1. Respect user weight preferences (highest priority)
        2. Penalise multiple tasks on the same day (soft, not hard)
        3. Penalise repeating the same task across the week
        4. Balance total load across people
        """
        num_days = len(self.roster.days)
        num_tasks = len(self.roster.tasks)
        objective_terms = []

        # ── 1. Preference weights (highest priority) ──
        weight_scale = num_days * num_tasks * 100

        for person in self.roster.people:
            for task in self.roster.tasks:
                w = person.task_weights.get(task.id, 0)
                if w != 0:
                    for day in self.roster.days:
                        objective_terms.append(
                            int(w * weight_scale) * self.vars[(person.id, task.id, day)]
                        )

        # ── 2. Soft: penalise >1 task per person per day ──
        # extra_tasks_d = max(0, tasks_that_day - 1)
        for person in self.roster.people:
            for day in self.roster.days:
                day_total = sum(
                    self.vars[(person.id, task.id, day)]
                    for task in self.roster.tasks
                )
                extra = self.model.NewIntVar(0, num_tasks, f"extra_{person.id}_{day}")
                self.model.Add(extra >= day_total - 1)
                self.model.Add(extra >= 0)
                # Moderate penalty – worse than repeating a task but not a deal-breaker
                objective_terms.append(-10 * extra)

        # ── 3. Penalise repeating the same task (any two days, not just consecutive) ──
        for person in self.roster.people:
            for task in self.roster.tasks:
                week_count = sum(
                    self.vars[(person.id, task.id, day)]
                    for day in self.roster.days
                )
                # repeat = max(0, week_count - 1)
                repeat = self.model.NewIntVar(0, num_days, f"rep_{person.id}_{task.id}")
                self.model.Add(repeat >= week_count - 1)
                self.model.Add(repeat >= 0)
                # Strong penalty per extra occurrence
                objective_terms.append(-20 * repeat)

        # ── 4. Balance total load across people ──
        max_load = self.model.NewIntVar(0, num_days * num_tasks, "max_load")
        min_load = self.model.NewIntVar(0, num_days * num_tasks, "min_load")

        for person in self.roster.people:
            total = sum(
                self.vars[(person.id, task.id, day)]
                for task in self.roster.tasks
                for day in self.roster.days
            )
            self.model.Add(max_load >= total)
            self.model.Add(min_load <= total)

        objective_terms.append(-5 * (max_load - min_load))

        self.model.Maximize(sum(objective_terms))
    
    def _extract_solution(self, solver):
        """Extract the solution into a readable format"""
        solution = {day: {task.id: [] for task in self.roster.tasks} 
                   for day in self.roster.days}
        
        for person in self.roster.people:
            for task in self.roster.tasks:
                for day in self.roster.days:
                    if solver.Value(self.vars[(person.id, task.id, day)]) == 1:
                        solution[day][task.id].append(person.id)
        
        return solution