from ortools.sat.python import cp_model
from backend.roster.models import Roster
from typing import Dict, List, Tuple, Optional


def _status_name(status: int) -> str:
    return {0: "UNKNOWN", 1: "MODEL_INVALID", 2: "FEASIBLE", 3: "INFEASIBLE", 4: "OPTIMAL"}.get(status, str(status))


class SolverError(Exception):
    """Raised when the solver cannot find a feasible solution."""
    def __init__(self, message: str, hints: List[str]):
        self.hints = hints
        super().__init__(message)

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
        self._add_disabled_task_day_constraints()
        
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
            hints = self._diagnose()
            raise SolverError(
                f"Solver status: {_status_name(status)}",
                hints=hints,
            )
    
    def _add_min_people_constraints(self):
        """Ensure each task has at least min_people assigned each day (skip disabled)"""
        disabled = self.roster.disabled_task_days
        for task in self.roster.tasks:
            for day in self.roster.days:
                if day in disabled.get(task.id, []):
                    continue
                task_assignments = [
                    self.vars[(person.id, task.id, day)]
                    for person in self.roster.people
                ]
                self.model.Add(sum(task_assignments) >= task.min_people)

    def _add_preferred_people_constraints(self):
        """Ensure each task has at most preferred_people assigned each day (skip disabled)"""
        disabled = self.roster.disabled_task_days
        for task in self.roster.tasks:
            for day in self.roster.days:
                if day in disabled.get(task.id, []):
                    continue
                task_assignments = [
                    self.vars[(person.id, task.id, day)]
                    for person in self.roster.people
                ]
                self.model.Add(sum(task_assignments) <= task.preferred_people)
    
    def _add_task_conflict_constraints(self):
        """Ensure people can't do conflicting tasks on the same day"""
        task_ids = {t.id for t in self.roster.tasks}
        for task1_id, task2_id in self.roster.task_conflicts:
            if task1_id not in task_ids or task2_id not in task_ids:
                continue
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

    def _add_disabled_task_day_constraints(self):
        """Force all assignments to 0 for disabled task-day pairs"""
        for task_id, days in self.roster.disabled_task_days.items():
            for day in days:
                for person in self.roster.people:
                    key = (person.id, task_id, day)
                    if key in self.vars:
                        self.model.Add(self.vars[key] == 0)

    def _diagnose(self) -> List[str]:
        """Return human-readable hints about why the model is infeasible."""
        hints: List[str] = []
        disabled = self.roster.disabled_task_days

        for task in self.roster.tasks:
            if task.min_people < 1:
                continue
            for day in self.roster.days:
                if day in disabled.get(task.id, []):
                    continue
                # Count people who are NOT blocked from this task on this day
                blocked = set()
                for pid, tid, d in self.roster.task_blocks:
                    if tid == task.id and (d == day or d == ""):
                        blocked.add(pid)
                available = [p for p in self.roster.people if p.id not in blocked]
                if len(available) < task.min_people:
                    hints.append(
                        f"'{task.name}' op {day}: {task.min_people} personen nodig "
                        f"maar slechts {len(available)} beschikbaar (rest is geblokkeerd)"
                    )

        total_slots_needed = 0
        total_slots_available = 0
        for day in self.roster.days:
            for task in self.roster.tasks:
                if day in disabled.get(task.id, []):
                    continue
                total_slots_needed += task.min_people
            total_slots_available += len(self.roster.people)
        if total_slots_needed > total_slots_available:
            hints.append(
                f"Totaal {total_slots_needed} toewijzingen nodig, "
                f"maar slechts {total_slots_available} beschikbaar "
                f"({len(self.roster.people)} personen × {len(self.roster.days)} dagen). "
                f"Voeg meer instructeurs toe of verlaag het minimale aantal per taak."
            )

        if not hints:
            hints.append(
                "De combinatie van beperkingen (blokkades, conflicten, min/max) "
                "maakt het onmogelijk een rooster te maken. "
                "Probeer beperkingen te versoepelen."
            )

        return hints

    def _set_objective(self):
        """Objective with soft constraints:
        1. Respect user weight preferences (highest priority)
        2. Penalise multiple tasks on the same day (soft, not hard)
        3. Penalise repeating the same task across the week
        4. Balance total load across people

        All penalty/bonus magnitudes are driven by solver_config.
        """
        cfg = self.roster.solver_config
        num_days = len(self.roster.days)
        num_tasks = len(self.roster.tasks)
        no_repeat_ids = set(cfg.no_repeat_tasks)
        objective_terms = []

        # ── 1. Preference weights (highest priority) ──
        weight_scale = num_days * num_tasks * cfg.preference_scale

        for person in self.roster.people:
            for task in self.roster.tasks:
                w = person.task_weights.get(task.id, 0)
                if w != 0:
                    for day in self.roster.days:
                        objective_terms.append(
                            int(w * weight_scale) * self.vars[(person.id, task.id, day)]
                        )

        # ── 2. Soft: penalise >1 task per person per day ──
        for person in self.roster.people:
            for day in self.roster.days:
                day_total = sum(
                    self.vars[(person.id, task.id, day)]
                    for task in self.roster.tasks
                )
                extra = self.model.NewIntVar(0, num_tasks, f"extra_{person.id}_{day}")
                self.model.Add(extra >= day_total - 1)
                self.model.Add(extra >= 0)
                objective_terms.append(-cfg.multi_task_day_penalty * extra)

        # ── 3. Penalise repeating the same task (any two days) ──
        for person in self.roster.people:
            for task in self.roster.tasks:
                week_count = sum(
                    self.vars[(person.id, task.id, day)]
                    for day in self.roster.days
                )
                repeat = self.model.NewIntVar(0, num_days, f"rep_{person.id}_{task.id}")
                self.model.Add(repeat >= week_count - 1)
                self.model.Add(repeat >= 0)

                penalty = cfg.repeat_penalty
                if task.id in no_repeat_ids:
                    penalty += cfg.no_repeat_penalty
                objective_terms.append(-penalty * repeat)

        # ── 4. Balance total load across people (proportional to available days) ──
        # A person blocked on all tasks for a day is effectively absent that day.
        # We balance load / available_days rather than raw totals so that someone
        # present 4 out of 6 days gets roughly 4/6 the load of a full-week person.

        blocked_all_days: Dict[str, set] = {}  # person_id -> set of fully-blocked days
        task_ids = {t.id for t in self.roster.tasks}
        disabled = self.roster.disabled_task_days
        for person in self.roster.people:
            absent_days: set = set()
            for day in self.roster.days:
                all_blocked = True
                for task in self.roster.tasks:
                    if day in disabled.get(task.id, []):
                        continue  # task not available this day for anyone
                    # Check if this person is blocked from this task on this day
                    person_blocked = False
                    for pid, tid, d in self.roster.task_blocks:
                        if pid == person.id and tid == task.id and (d == day or d == ""):
                            person_blocked = True
                            break
                    if not person_blocked:
                        all_blocked = False
                        break
                if all_blocked:
                    absent_days.add(day)
            blocked_all_days[person.id] = absent_days

        available_counts = {
            p.id: max(1, len(self.roster.days) - len(blocked_all_days[p.id]))
            for p in self.roster.people
        }

        # Scale each person's load to a common denominator so the solver can
        # compare them as integers.  scaled_load = total * lcm / available_days
        from math import gcd
        from functools import reduce
        def lcm(a: int, b: int) -> int:
            return a * b // gcd(a, b)
        common = reduce(lcm, available_counts.values(), 1)

        max_scaled = self.model.NewIntVar(0, num_days * num_tasks * common, "max_scaled")
        min_scaled = self.model.NewIntVar(0, num_days * num_tasks * common, "min_scaled")

        for person in self.roster.people:
            total = sum(
                self.vars[(person.id, task.id, day)]
                for task in self.roster.tasks
                for day in self.roster.days
            )
            scale = common // available_counts[person.id]
            scaled = self.model.NewIntVar(0, num_days * num_tasks * common, f"scaled_{person.id}")
            self.model.Add(scaled == total * scale)
            self.model.Add(max_scaled >= scaled)
            self.model.Add(min_scaled <= scaled)

        objective_terms.append(-cfg.balance_penalty * (max_scaled - min_scaled))

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