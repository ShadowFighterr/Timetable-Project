from __future__ import annotations

import time
from threading import Event
import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager
from statistics import median

from parser import parse_instance
from model import Schedule, Placement
from constraints import (
    required_distribution_violation,
    validate_schedule,
)
from validation import objective_lower_bound


def _validate_final_schedule(instance, schedule):
    violations = validate_schedule(instance, schedule)
    feasible = all(
        violations[name] == 0
        for name in (
            "unassigned",
            "room",
            "required_distribution",
            "other",
        )
    )
    return violations, feasible


class CSPSolver:
    """
    Constraint Satisfaction Problem solver for university timetabling.

    Main optimizations:
      1. Precomputed constraint graph
      2. Incremental room/time occupancy
      3. MRV + degree heuristic
      4. Neighbor-only forward checking
      5. Precomputed required-distribution membership
      6. Best partial solution preservation
    """

    TIME_LIMIT = 300.0
    NODE_LIMIT = 1_000_000

    def __init__(
        self,
        instance,
        variable_selection: str = "static",
        time_limit: float | None = None,
        node_limit: int | None = None,
        cancellation_event: Event | None = None,
        optimize_objective: bool = False,
    ):
        if variable_selection not in {"static", "dynamic"}:
            raise ValueError(
                "variable_selection must be 'static' or 'dynamic'"
            )

        self.instance = instance
        self.variable_selection = variable_selection
        self.time_limit = (
            self.TIME_LIMIT if time_limit is None else time_limit
        )
        self.node_limit = (
            self.NODE_LIMIT if node_limit is None else node_limit
        )
        self.cancellation_event = cancellation_event
        self.optimize_objective = optimize_objective

        self.schedule = Schedule(instance)

        self.start_time = None
        self.nodes = 0
        self.backtracks = 0
        self.profile_stats = {
            name: {"calls": 0, "seconds": 0.0}
            for name in (
                "candidate_valid",
                "_distribution_valid_after_assignment",
                "required_distribution_violation",
                "forward_check",
                "select_unassigned_class",
            )
        }
        self.candidate_outcomes = Counter()
        self.forward_check_failures = 0
        self.forward_check_failure_classes = Counter()
        self.forward_check_trigger_classes = Counter()
        self.forward_check_legal_observations = defaultdict(Counter)
        self.forward_check_failure_details = {}
        self.forward_check_trigger_details = {}
        self.dead_end_classes = Counter()
        self.dead_end_contexts = Counter()
        self.last_dead_end = None
        self.best_assignment_milestones = []

        # Best partial solution found before timeout.
        self.best_schedule = Schedule(instance)
        self.best_assigned = 0
        self.best_objective_score = None
        self.objective_optimal = False

        # ---------------------------------------------------------
        # Room occupancy
        # ---------------------------------------------------------
        #
        # room_id -> list[(class_id, placement)]
        #
        self.room_occupancy = defaultdict(list)

        # ---------------------------------------------------------
        # Constraint graph
        # ---------------------------------------------------------
        #
        # class_id -> set(class_ids that can interact with it)
        #
        self.neighbors = defaultdict(set)

        # class_id -> required distributions involving the class
        self.class_distributions = defaultdict(list)

        # ---------------------------------------------------------
        # Degree
        # ---------------------------------------------------------
        self.degree = {}

        # ---------------------------------------------------------
        # Domains
        # ---------------------------------------------------------
        #
        # We keep the original domains and dynamically filter them.
        #
        self.domains = {
            class_id: list(cls.placements)
            for class_id, cls in instance.classes.items()
        }

        # ---------------------------------------------------------
        # Build preprocessing structures
        # ---------------------------------------------------------
        self._build_constraint_graph()
        self._build_degrees()

        # Fixed assignments are not automatically inserted here.
        # They are still variables in the CSP, but MRV will naturally
        # select their one-value domains first.

    @contextmanager
    def _measure(self, name):
        stats = self.profile_stats[name]
        stats["calls"] += 1
        started = time.perf_counter()
        try:
            yield
        finally:
            stats["seconds"] += time.perf_counter() - started

    # =============================================================
    # PREPROCESSING
    # =============================================================

    def _build_constraint_graph(self):
        """
        Build an undirected graph of classes participating in
        required binary/multi-class distributions.

        Instead of checking every class after each assignment,
        forward checking only revisits affected classes.
        """

        for distribution in self.instance.distributions:

            if not distribution.required:
                continue

            class_ids = list(distribution.class_ids)

            for class_id in class_ids:
                self.class_distributions[class_id].append(distribution)

            # Complete graph for classes participating in the
            # same required distribution.
            #
            # The instances are small enough that this preprocessing
            # cost is acceptable and dramatically reduces repeated
            # work during search.
            for i, a in enumerate(class_ids):
                for b in class_ids[i + 1:]:
                    self.neighbors[a].add(b)
                    self.neighbors[b].add(a)

        # Ensure every class exists in the graph.
        for class_id in self.instance.classes:
            self.neighbors.setdefault(class_id, set())

    def _build_degrees(self):
        for class_id in self.instance.classes:
            self.degree[class_id] = len(self.neighbors[class_id])

    # =============================================================
    # TIME / ROOM HELPERS
    # =============================================================

    @staticmethod
    def _bits_overlap(a: str, b: str) -> bool:
        return any(x == "1" and y == "1" for x, y in zip(a, b))

    @staticmethod
    def _time_overlap(a: Placement, b: Placement) -> bool:
        """
        Check whether two placements overlap in day/time/week.
        """

        if not CSPSolver._bits_overlap(a.days, b.days):
            return False

        if not CSPSolver._bits_overlap(a.weeks, b.weeks):
            return False

        a_start = a.start
        a_end = a.start + a.length

        b_start = b.start
        b_end = b.start + b.length

        return a_start < b_end and b_start < a_end

    def _room_conflict(self, class_id: int, placement: Placement) -> bool:
        """
        Check whether a candidate placement conflicts with an
        already assigned class using the same room.
        """

        room_id = placement.room_id

        if room_id is None:
            return False

        for other_id, other_placement in self.room_occupancy[room_id]:
            if other_id == class_id:
                continue

            if self._time_overlap(placement, other_placement):
                return True

        return False

    # =============================================================
    # DISTRIBUTION CHECKING
    # =============================================================

    def _distribution_valid_after_assignment(
        self,
        class_id: int,
        placement: Placement,
    ) -> bool:
        """
        Temporarily test the candidate against all required
        distributions involving class_id.

        Only distributions touching this class are inspected.
        """

        with self._measure("_distribution_valid_after_assignment"):
            old = self.schedule.get_placement(class_id)

            self.schedule.assign(class_id, placement)

            try:
                for distribution in self.class_distributions[class_id]:

                    with self._measure("required_distribution_violation"):
                        violation = required_distribution_violation(
                            self.instance,
                            distribution,
                            self.schedule,
                        )

                    if violation:
                        return False

                return True

            finally:
                if old is None:
                    self.schedule.unassign(class_id)
                else:
                    self.schedule.assign(class_id, old)

    # =============================================================
    # CANDIDATE VALIDATION
    # =============================================================

    def candidate_valid(
        self,
        class_id: int,
        placement: Placement,
    ) -> bool:

        with self._measure("candidate_valid"):
            cls = self.instance.classes[class_id]
            if (
                cls.room_required
                and (
                    placement.room_id is None
                    or placement.room_id not in self.instance.rooms
                )
            ):
                self.candidate_outcomes["room compatibility violation"] += 1
                return False
            if (
                cls.expected_enrollment is not None
                and placement.room_id is not None
                and placement.room_id in self.instance.rooms
                and self.instance.rooms[placement.room_id].capacity
                < cls.expected_enrollment
            ):
                self.candidate_outcomes["room capacity violation"] += 1
                return False

            # ---------------------------------------------------------
            # Room conflict
            # ---------------------------------------------------------

            if self._room_conflict(class_id, placement):
                self.candidate_outcomes["room conflict"] += 1
                return False

            # ---------------------------------------------------------
            # Required distributions
            # ---------------------------------------------------------

            if not self._distribution_valid_after_assignment(
                class_id,
                placement,
            ):
                self.candidate_outcomes[
                    "required-distribution violation"
                ] += 1
                return False

            self.candidate_outcomes["accepted"] += 1
            return True

    # =============================================================
    # LEGAL VALUES
    # =============================================================

    def legal_values(self, class_id: int):
        """
        Return currently legal placements for a class.

        Values are ordered later by order_values().
        """

        legal = []

        for placement in self.domains[class_id]:

            if self.candidate_valid(class_id, placement):
                legal.append(placement)

        return legal

    # =============================================================
    # MRV
    # =============================================================

    def select_unassigned_class(self):
        """
        Select a variable with the configured MRV strategy.
        """
        with self._measure("select_unassigned_class"):
            if self.variable_selection == "dynamic":
                return self._select_dynamic_mrv()
            return self._select_static_mrv()

    def _select_static_mrv(self):
        unassigned = [
            class_id
            for class_id in self.instance.classes
            if not self.schedule.is_assigned(class_id)
        ]

        if not unassigned:
            return None, []

        class_id = min(
            unassigned,
            key=lambda cid: (
                len(self.domains[cid]),
                -self.degree.get(cid, 0),
            ),
        )

        values = self.legal_values(class_id)
        return class_id, values

    def _select_dynamic_mrv(self):
        best_class = None
        best_values = []
        best_key = None

        for class_id in self.instance.classes:
            if self.schedule.is_assigned(class_id):
                continue

            values = self.legal_values(class_id)
            unassigned_degree = sum(
                not self.schedule.is_assigned(neighbor_id)
                for neighbor_id in self.neighbors[class_id]
            )
            key = (
                len(values),
                -unassigned_degree,
            )
            if best_key is None or key < best_key:
                best_class = class_id
                best_values = values
                best_key = key

        return best_class, best_values

    # =============================================================
    # VALUE ORDERING
    # =============================================================

    def order_values(self, class_id: int, values):
        """
        Prefer low-penalty placements.

        This is a heuristic only. It does NOT affect feasibility.
        """

        return sorted(
            values,
            key=lambda p: (
                p.time_penalty,
                p.room_penalty,
                p.start,
            ),
        )

    # =============================================================
    # ASSIGN / UNASSIGN
    # =============================================================

    def assign(self, class_id: int, placement: Placement):

        self.schedule.assign(class_id, placement)

        room_id = placement.room_id

        if room_id is not None:
            self.room_occupancy[room_id].append(
                (class_id, placement)
            )

        assigned = self.schedule.assigned_count

        if assigned > self.best_assigned:
            self.best_assigned = assigned
            self.best_schedule = self.schedule.copy()
            self.best_assignment_milestones.append((assigned, class_id))

    def unassign(self, class_id: int):

        placement = self.schedule.get_placement(class_id)

        if placement is None:
            return

        room_id = placement.room_id

        if room_id is not None:
            entries = self.room_occupancy[room_id]

            self.room_occupancy[room_id] = [
                item
                for item in entries
                if item[0] != class_id
            ]

        self.schedule.unassign(class_id)

    # =============================================================
    # FORWARD CHECKING
    # =============================================================

    def forward_check(self, class_id: int) -> bool:
        """
        Only inspect classes affected by the newly assigned class.

        This is the major optimization compared with the previous
        implementation, which scanned every remaining class.
        """

        with self._measure("forward_check"):
            affected = self.neighbors[class_id]

            for neighbor_id in affected:

                if self.schedule.is_assigned(neighbor_id):
                    continue

                # We only need to know whether at least one value remains.
                has_value = False
                legal_candidates_found = 0

                for placement in self.domains[neighbor_id]:

                    if self.candidate_valid(
                        neighbor_id,
                        placement
                    ):
                        has_value = True
                        legal_candidates_found = 1
                        break

                self.forward_check_legal_observations[neighbor_id][
                    legal_candidates_found
                ] += 1

                if not has_value:
                    self.forward_check_failures += 1
                    self.forward_check_failure_classes[neighbor_id] += 1
                    self.forward_check_trigger_classes[class_id] += 1
                    self.forward_check_failure_details[neighbor_id] = (
                        class_id,
                        self.schedule.assigned_count,
                        legal_candidates_found,
                    )
                    self.forward_check_trigger_details[class_id] = (
                        neighbor_id,
                        self.schedule.assigned_count,
                        legal_candidates_found,
                    )
                    return False

            return True

    # =============================================================
    # SEARCH CONTROL
    # =============================================================

    def time_exceeded(self):
        return (
            time.perf_counter() - self.start_time
            >= self.time_limit
        )

    def node_limit_reached(self):
        return self.nodes >= self.node_limit

    def cancelled(self):
        return (
            self.cancellation_event is not None
            and self.cancellation_event.is_set()
        )

    # =============================================================
    # BACKTRACKING
    # =============================================================

    def backtrack(self):

        self.nodes += 1

        # ---------------------------------------------------------
        # Limits
        # ---------------------------------------------------------

        if self.cancelled() or self.time_exceeded():
            return False

        if self.node_limit_reached():
            return False

        # ---------------------------------------------------------
        # Complete?
        # ---------------------------------------------------------

        if self.schedule.is_complete:
            if not self.optimize_objective:
                return True
            score = objective_lower_bound(
                self.instance,
                self.schedule.assignments,
            )
            if (
                self.best_objective_score is None
                or score < self.best_objective_score
            ):
                self.best_objective_score = score
                self.best_schedule = self.schedule.copy()
                self.best_assigned = self.schedule.assigned_count
            if score == 0:
                self.objective_optimal = True
                return True
            return False

        if (
            self.optimize_objective
            and self.best_objective_score is not None
            and objective_lower_bound(
                self.instance,
                self.schedule.assignments,
            ) >= self.best_objective_score
        ):
            return False

        # ---------------------------------------------------------
        # MRV
        # ---------------------------------------------------------

        class_id, values = self.select_unassigned_class()

        if class_id is None:
            return True

        if not values:
            self.dead_end_classes[class_id] += 1
            self.dead_end_contexts[
                (class_id, self.schedule.assigned_count, "empty domain")
            ] += 1
            self.last_dead_end = (
                class_id,
                self.schedule.assigned_count,
                "selected class has no legal values",
            )
            self.backtracks += 1
            return False

        # ---------------------------------------------------------
        # Value ordering
        # ---------------------------------------------------------

        values = self.order_values(class_id, values)

        # ---------------------------------------------------------
        # Try candidates
        # ---------------------------------------------------------

        for placement in values:

            if self.cancelled() or self.time_exceeded():
                return False

            if self.node_limit_reached():
                return False

            if not self.candidate_valid(
                class_id,
                placement
            ):
                continue

            self.assign(class_id, placement)

            # -----------------------------------------------------
            # Forward checking
            # -----------------------------------------------------

            if self.forward_check(class_id):

                if self.backtrack():
                    return True

            else:
                self.candidate_outcomes["forward-check rejection"] += 1

            self.unassign(class_id)

        if (
            not self.cancelled()
            and not self.time_exceeded()
            and not self.node_limit_reached()
        ):
            self.dead_end_classes[class_id] += 1
            self.dead_end_contexts[
                (
                    class_id,
                    self.schedule.assigned_count,
                    "all candidate placements exhausted",
                )
            ] += 1
            self.last_dead_end = (
                class_id,
                self.schedule.assigned_count,
                "all candidate placements exhausted",
            )
        self.backtracks += 1

        return False

    # =============================================================
    # SOLVE
    # =============================================================

    def solve(self, *, started_at: float | None = None):

        self.start_time = (
            time.perf_counter() if started_at is None else started_at
        )

        solved = self.backtrack()

        runtime = time.perf_counter() - self.start_time

        if (
            self.optimize_objective
            and self.best_assigned == len(self.instance.classes)
            and not self.cancelled()
            and not self.time_exceeded()
            and not self.node_limit_reached()
        ):
            self.objective_optimal = True

        # If solved, keep the actual solution.
        if solved:
            self.best_schedule = self.schedule.copy()
            self.best_assigned = self.schedule.assigned_count

        return solved, runtime


# =================================================================
# MAIN
# =================================================================

def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument(
        "--strategy",
        choices=("static", "dynamic"),
        default="static",
        help="Variable selection strategy (default: static baseline)",
    )
    args = argument_parser.parse_args()

    instance = parse_instance("data/pu-d5-spr17.xml")

    print(f"Loaded instance: {instance.name}")
    print(f"Classes: {len(instance.classes)}")
    print(f"Rooms:   {len(instance.rooms)}")

    print()
    print("=" * 60)
    print("OPTIMIZED CSP FEASIBILITY SOLVER")
    print("=" * 60)

    solver = CSPSolver(
        instance,
        variable_selection=args.strategy,
    )
    print(f"Variable selection: {solver.variable_selection}")

    print()
    print("Preprocessing:")
    print(f"  Variables:       {len(instance.classes)}")
    print(f"  Required dist.:  {sum(1 for d in instance.distributions if d.required)}")

    degrees = list(solver.degree.values())

    if degrees:
        print(f"  Avg degree:      {sum(degrees) / len(degrees):.2f}")
        print(f"  Max degree:      {max(degrees)}")

    domain_sizes = [len(domain) for domain in solver.domains.values()]
    if domain_sizes:
        print(
            f"  Empty domains:   "
            f"{sum(size == 0 for size in domain_sizes)}"
        )
        print(
            f"  Initial domain:  min={min(domain_sizes)}, "
            f"median={median(domain_sizes):g}, "
            f"max={max(domain_sizes)}"
        )
    else:
        print("  Empty domains:   0")
        print("  Initial domain:  no classes")

    roomless_classes = sum(
        not cls.room_required
        for cls in instance.classes.values()
    )
    print(f"  No room required:{roomless_classes}")

    print()
    print("Search started...")

    solved, runtime = solver.solve()

    print()
    print("=" * 60)
    print("RESULT")
    print("=" * 60)

    print(f"Solved:            {solved}")
    print(
        f"Assigned classes:  "
        f"{solver.schedule.assigned_count if solved else solver.best_assigned}"
    )
    print(f"Total classes:     {len(instance.classes)}")
    print(f"Search nodes:      {solver.nodes}")
    print(f"Backtracks:        {solver.backtracks}")
    print(f"Runtime:           {runtime:.3f} seconds")

    print()
    print("PROFILE (cumulative inclusive timings)")
    print("-" * 60)
    for name, stats in solver.profile_stats.items():
        print(
            f"{name}: calls={stats['calls']}, "
            f"time={stats['seconds']:.3f} seconds"
        )

    print()
    print("DIAGNOSTICS")
    print("-" * 60)
    for reason in (
        "room conflict",
        "required-distribution violation",
        "forward-check rejection",
        "other",
        "accepted",
    ):
        print(f"Candidate {reason}: {solver.candidate_outcomes[reason]}")
    print(f"Forward-check failures: {solver.forward_check_failures}")
    print(
        "Forward-check class probes (legal candidates found, capped at 1): "
        f"0={sum(counts[0] for counts in solver.forward_check_legal_observations.values())}, "
        f"1={sum(counts[1] for counts in solver.forward_check_legal_observations.values())}"
    )
    print("Most frequent classes triggering forward-check failure:")
    if solver.forward_check_trigger_classes:
        for trigger_class_id, count in solver.forward_check_trigger_classes.most_common(10):
            blocked_id, assigned_count, legal_count = (
                solver.forward_check_trigger_details[trigger_class_id]
            )
            print(
                f"  class {trigger_class_id}: {count} failures; "
                f"last blocked class {blocked_id} had {legal_count} "
                f"legal candidates at {assigned_count} assigned"
            )
    else:
        print("  none")
    print("Most frequent classes with no legal candidate in forward checking:")
    if solver.forward_check_failure_classes:
        for blocked_class_id, count in solver.forward_check_failure_classes.most_common(10):
            trigger_id, assigned_count, legal_count = (
                solver.forward_check_failure_details[blocked_class_id]
            )
            print(
                f"  class {blocked_class_id}: {count} failures; "
                f"{legal_count} legal candidates, last triggered by "
                f"class {trigger_id} at {assigned_count} assigned"
            )
    else:
        print("  none")

    print(
        f"New-maximum assignment events: "
        f"{len(solver.best_assignment_milestones)}"
    )
    if solver.best_assignment_milestones:
        first_count, first_class = solver.best_assignment_milestones[0]
        last_count, last_class = solver.best_assignment_milestones[-1]
        print(
            f"  First: {first_count} assigned by class {first_class}; "
            f"latest: {last_count} assigned by class {last_class}"
        )
        recent = solver.best_assignment_milestones[-10:]
        print(
            "  Recent maxima (assigned count: class): "
            + ", ".join(f"{count}: {class_id}" for count, class_id in recent)
        )

    print(f"Dead-end occurrences: {sum(solver.dead_end_classes.values())}")
    print("Classes most often selected before a dead end:")
    if solver.dead_end_classes:
        for dead_end_class_id, count in solver.dead_end_classes.most_common(10):
            print(f"  class {dead_end_class_id}: {count}")
    else:
        print("  none")
    if solver.last_dead_end is not None:
        dead_end_class_id, assigned_count, reason = solver.last_dead_end
        print(
            f"Last dead end: class {dead_end_class_id} selected at "
            f"{assigned_count} assigned ({reason})"
        )

    if solved:
        print("Reason:            feasible solution found")
    elif solver.nodes >= solver.NODE_LIMIT:
        print("Reason:            node limit reached")
    else:
        print("Reason:            time limit reached")

    print()
    print("BEST PARTIAL SOLUTION")
    print("-" * 60)
    print(f"Assigned classes:  {solver.best_assigned}")
    print(
        f"Coverage:          "
        f"{100 * solver.best_assigned / len(instance.classes):.2f}%"
    )

    # -------------------------------------------------------------
    # Final schedule
    # -------------------------------------------------------------

    if solved:
        final_schedule = solver.schedule
    else:
        final_schedule = solver.best_schedule

    print()
    print("=" * 60)
    print("FINAL VALIDATION")
    print("=" * 60)

    validation = final_schedule

    print(
        f"Assigned classes: {validation.assigned_count}"
    )
    print(
        f"Total classes:    {validation.total_classes}"
    )
    print(
        f"Unassigned:       "
        f"{validation.total_classes - validation.assigned_count}"
    )

    # -------------------------------------------------------------
    # Validate only complete solution here.
    # -------------------------------------------------------------

    if solved:
        report, feasible = _validate_final_schedule(
            instance,
            final_schedule
        )

        print(f"Room violations:   {report['room']}")
        print(
            f"Required dist.:    "
            f"{report['required_distribution']}"
        )
        print(f"Other violations:  {report['other']}")
        print(f"Feasible:          {feasible}")

    else:
        print("Feasible:          NOT DETERMINED")
        print(
            "Note: solver timed out before obtaining a complete "
            "assignment."
        )

    # -------------------------------------------------------------
    # First assignments
    # -------------------------------------------------------------

    print()
    print("FIRST 10 ASSIGNMENTS")

    shown = 0

    for class_id, placement in final_schedule.assignments.items():

        print(
            f"Class {class_id}: "
            f"room={placement.room_id}, "
            f"day={placement.days}, "
            f"start={placement.start}, "
            f"length={placement.length}, "
            f"weeks={placement.weeks}"
        )

        shown += 1

        if shown >= 10:
            break


if __name__ == "__main__":
    main()