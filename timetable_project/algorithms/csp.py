"""Adapter for the existing finite-domain CSP solver."""

from __future__ import annotations

import time

from algorithms.base import (
    AlgorithmResult,
    RunConfig,
    SchedulingAlgorithm,
    make_result,
)
from parser import Instance
from solver import CSPSolver
from validation import is_soft_objective_supported, unsupported_distributions


class CspAlgorithm(SchedulingAlgorithm):
    name = "CSP (static MRV + forward checking)"
    version = "2"

    def run(self, instance: Instance, config: RunConfig) -> AlgorithmResult:
        started = time.perf_counter()
        unsupported_required = [
            item for item in unsupported_distributions(instance)
            if item["required"]
        ]
        if unsupported_required:
            from model import Schedule

            return make_result(
                algorithm=self.name,
                version=self.version,
                status="unsupported",
                runtime_s=time.perf_counter() - started,
                schedule=Schedule(instance),
                config=config,
                termination_reason="unsupported_required_constraints",
                error=f"Unsupported required distributions: {unsupported_required}",
            )

        unsupported_soft = [
            item
            for item in instance.distributions
            if not item.required
            and item.penalty > 0
            and not is_soft_objective_supported(item.type)
        ]
        if unsupported_soft:
            from model import Schedule

            return make_result(
                algorithm=self.name,
                version=self.version,
                status="unsupported",
                runtime_s=time.perf_counter() - started,
                schedule=Schedule(instance),
                config=config,
                termination_reason="unsupported_soft_objective",
                error=f"Unsupported soft objective distributions: {unsupported_soft}",
            )
        if instance.student_weight > 0 and instance.students:
            from model import Schedule

            return make_result(
                algorithm=self.name,
                version=self.version,
                status="unsupported",
                runtime_s=time.perf_counter() - started,
                schedule=Schedule(instance),
                config=config,
                termination_reason="unsupported_student_objective",
                error=(
                    "CSP does not jointly optimize student section choices "
                    "with timetable placements. The separate fixed-timetable "
                    "sectioner is not a substitute for the joint objective."
                ),
            )

        solver = CSPSolver(
            instance,
            variable_selection=str(config.options.get("variable_selection", "static")),
            time_limit=config.time_limit_s,
            node_limit=(
                config.node_limit
                if config.node_limit is not None
                else 2**63 - 1
            ),
            cancellation_event=config.cancellation_event,
            optimize_objective=True,
        )
        solved, runtime = solver.solve(started_at=started)
        stopped_by_time = solver.time_exceeded()
        stopped_by_nodes = solver.node_limit_reached()

        if config.cancellation_event is not None and config.cancellation_event.is_set():
            status = "cancelled"
            reason = "cancelled"
            schedule = solver.schedule if solved else solver.best_schedule
        elif solver.best_assigned == len(instance.classes):
            status = "complete"
            reason = (
                "objective_optimum_proven"
                if solver.objective_optimal
                else (
                    "time_limit_with_feasible_incumbent"
                    if stopped_by_time
                    else (
                        "node_limit_with_feasible_incumbent"
                        if stopped_by_nodes
                        else "feasible_incumbent"
                    )
                )
            )
            schedule = solver.best_schedule
        elif solved:
            status = "complete"
            reason = "feasible_assignment_found"
            schedule = solver.schedule
        elif stopped_by_nodes and solver.best_assigned:
            status = "partial"
            reason = "node_limit"
            schedule = solver.best_schedule
        elif stopped_by_time:
            status = "timeout_unknown"
            reason = "time_limit"
            schedule = solver.best_schedule
        elif stopped_by_nodes:
            status = "timeout_unknown"
            reason = "node_limit"
            schedule = solver.best_schedule
        else:
            status = "infeasible_proven"
            reason = "search_exhausted"
            schedule = solver.best_schedule

        statistics = {
            "search_nodes": solver.nodes,
            "backtracks": solver.backtracks,
            "candidate_outcomes": dict(solver.candidate_outcomes),
            "forward_check_failures": solver.forward_check_failures,
            "variable_selection": solver.variable_selection,
            "node_limit": solver.node_limit,
            "objective_optimal": solver.objective_optimal,
            "best_objective_score": solver.best_objective_score,
        }
        return make_result(
            algorithm=self.name,
            version=self.version,
            status=status,
            runtime_s=runtime,
            schedule=schedule,
            config=config,
            statistics=statistics,
            termination_reason=reason,
        )
