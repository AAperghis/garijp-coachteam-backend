from ortools.sat.python import cp_model
from .models import Roster
from typing import Dict, List, Tuple, Optional

class RosterSolver:
    def __init__(self, roster: Roster):
        self.roster = roster
        self.model = cp_model.CpModel()
        self.vars = {}  # Will hold all our decision variables
    
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
        self._add_task_conflict_constraints()
        self._add_max_assignments_constraints()
        self._add_pre_assignment_constraints()
        
        # Set objective function - maximize total weight
        self._set_objective()
        
        # Solve
        solver = cp_model.CpSolver()
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
                task_assignments = []
                for person in self.roster.people:
                    task_assignments.append(self.vars[(person.id, task.id, day)])
                
                self.model.Add(sum(task_assignments) >= task.min_people)
    
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
            assignments = []
            for day in self.roster.days:
                assignments.append(self.vars[(person_id, task_id, day)])
            
            self.model.Add(sum(assignments) <= max_count)
    
    def _add_pre_assignment_constraints(self):
        """Handle pre-assigned tasks"""
        for person_id, task_id, day in self.roster.pre_assignments:
            self.model.Add(self.vars[(person_id, task_id, day)] == 1)
    
    def _set_objective(self):
        """Set the objective function to maximize weighted assignments"""
        objective_terms = []
        
        for person in self.roster.people:
            for task in self.roster.tasks:
                for day in self.roster.days:
                    if task.id in person.task_weights:
                        weight = person.task_weights[task.id]
                        objective_terms.append(
                            weight * self.vars[(person.id, task.id, day)]
                        )
        
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