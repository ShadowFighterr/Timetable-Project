"""OR-Tools CP-SAT adapter for the currently supported common hard constraints."""

from __future__ import annotations

import time
from collections import defaultdict
from itertools import combinations
import re
from threading import Event, Thread
from typing import Any

from algorithms.base import (
    AlgorithmResult,
    RunConfig,
    SchedulingAlgorithm,
    make_result,
)
from model import Schedule
from parser import Instance, Placement
from validation import (
    PAIRWISE_TYPES,
    is_soft_objective_supported,
)


MAX_PAIR_CHECKS = 1_000_000


class _BuildDeadline(Exception):
    pass


class CpSatAlgorithm(SchedulingAlgorithm):
    name = "OR-Tools CP-SAT"
    version = "2"

    def run(self, instance: Instance, config: RunConfig) -> AlgorithmResult:
        started = time.perf_counter()
        try:
            from ortools.sat.python import cp_model
        except ImportError as exc:
            return make_result(
                algorithm=self.name,
                version=self.version,
                status="error",
                runtime_s=time.perf_counter() - started,
                schedule=Schedule(instance),
                config=config,
                termination_reason="dependency_missing",
                error=f"OR-Tools is not installed. Install requirements.txt: {exc}",
            )

        unsupported = [
            {
                "type": distribution.type,
                "required": True,
                "class_ids": list(distribution.class_ids),
            }
            for distribution in instance.distributions
            if distribution.required
            and not _cp_supports(distribution.type, len(distribution.class_ids))
        ]
        if unsupported:
            return make_result(
                algorithm=self.name,
                version=self.version,
                status="unsupported",
                runtime_s=time.perf_counter() - started,
                schedule=Schedule(instance),
                config=config,
                termination_reason="unsupported_required_constraints",
                error=f"CP-SAT does not yet model required distributions: {unsupported}",
            )
        if instance.student_weight > 0 and instance.students:
            return make_result(
                algorithm=self.name,
                version=self.version,
                status="unsupported",
                runtime_s=time.perf_counter() - started,
                schedule=Schedule(instance),
                config=config,
                termination_reason="unsupported_student_objective",
                error=(
                    "CP-SAT does not jointly optimize student section choices "
                    "with timetable placements. The separate fixed-timetable "
                    "sectioner is not a substitute for the joint objective."
                ),
            )
        unsupported_soft = [
            {
                "type": distribution.type,
                "required": False,
                "class_ids": list(distribution.class_ids),
            }
            for distribution in instance.distributions
            if not distribution.required
            and distribution.penalty > 0
            and not _cp_supports_soft(distribution.type)
        ]
        if unsupported_soft:
            return make_result(
                algorithm=self.name,
                version=self.version,
                status="unsupported",
                runtime_s=time.perf_counter() - started,
                schedule=Schedule(instance),
                config=config,
                termination_reason="unsupported_soft_objective",
                error=(
                    "CP-SAT does not yet optimize soft distribution penalties: "
                    f"{unsupported_soft}"
                ),
            )
        if config.cancellation_event is not None and config.cancellation_event.is_set():
            return make_result(
                algorithm=self.name,
                version=self.version,
                status="cancelled",
                runtime_s=time.perf_counter() - started,
                schedule=Schedule(instance),
                config=config,
                termination_reason="cancelled_before_model_build",
            )
        if config.node_limit is not None:
            return make_result(
                algorithm=self.name,
                version=self.version,
                status="unsupported",
                runtime_s=time.perf_counter() - started,
                schedule=Schedule(instance),
                config=config,
                termination_reason="incompatible_stopping_condition",
                error=(
                    "CP-SAT does not expose the CSP adapter's node-count limit; "
                    "use the shared wall-clock budget for comparisons."
                ),
            )
        if time.perf_counter() - started >= config.time_limit_s:
            return _timeout_during_build(
                self, instance, config, started, 0
            )

        model = cp_model.CpModel()
        variables: dict[int, list[Any]] = {}
        for class_id, cls in instance.classes.items():
            if config.cancellation_event is not None and config.cancellation_event.is_set():
                return _cancelled_during_build(self, instance, config, started, 0)
            if time.perf_counter() - started >= config.time_limit_s:
                return _timeout_during_build(
                    self, instance, config, started, 0
                )
            class_vars = [
                model.NewBoolVar(f"x_{class_id}_{index}")
                for index in range(len(cls.placements))
            ]
            variables[class_id] = class_vars
            model.AddExactlyOne(class_vars)
            for index, placement in enumerate(cls.placements):
                incompatible_room = (
                    cls.room_required
                    and (
                        placement.room_id is None
                        or placement.room_id not in instance.rooms
                    )
                )
                over_capacity = (
                    cls.expected_enrollment is not None
                    and placement.room_id in instance.rooms
                    and (
                        instance.rooms[placement.room_id].capacity is not None
                        and instance.rooms[placement.room_id].capacity
                        < cls.expected_enrollment
                    )
                )
                if incompatible_room or over_capacity:
                    model.Add(class_vars[index] == 0)

        interval_groups: dict[tuple[int, int, int], list[Any]] = defaultdict(list)
        for class_id, cls in instance.classes.items():
            for option_index, placement in enumerate(cls.placements):
                if option_index % 1024 == 0 and (
                    config.cancellation_event is not None
                    and config.cancellation_event.is_set()
                ):
                    return _cancelled_during_build(
                        self, instance, config, started, 0
                    )
                if option_index % 1024 == 0 and (
                    time.perf_counter() - started >= config.time_limit_s
                ):
                    return _timeout_during_build(
                        self, instance, config, started, 0
                    )
                if placement.room_id is None:
                    continue
                variable = variables[class_id][option_index]
                for day, day_bit in enumerate(placement.days):
                    if day_bit != "1":
                        continue
                    for week, week_bit in enumerate(placement.weeks):
                        if week_bit != "1":
                            continue
                        interval_groups[
                            (placement.room_id, day, week)
                        ].append(
                            model.NewOptionalFixedSizeIntervalVar(
                                placement.start,
                                placement.length,
                                variable,
                                f"room_{placement.room_id}_d{day}_w{week}_"
                                f"c{class_id}_p{option_index}",
                            )
                        )
        for intervals in interval_groups.values():
            model.AddNoOverlap(intervals)

        objective_terms = [
            (
                instance.time_weight * placement.time_penalty
                + instance.room_weight * placement.room_penalty
            )
            * variables[class_id][index]
            for class_id, cls in instance.classes.items()
            for index, placement in enumerate(cls.placements)
        ]

        pair_checks = 0
        try:
            for distribution in instance.distributions:
                if (
                    distribution.required
                    or distribution.penalty <= 0
                    or instance.distribution_weight == 0
                ):
                    continue
                kind = distribution.type
                member_pairs = (
                    combinations(distribution.class_ids, 2)
                    if kind in PAIRWISE_TYPES
                    or kind == "Precedence"
                    or re.fullmatch(r"WorkDay\(\d+\)|MinGap\(\d+\)", kind)
                    else ()
                )
                for class_a, class_b in member_pairs:
                    placements_a = instance.classes[class_a].placements
                    placements_b = instance.classes[class_b].placements
                    for index_a, first in enumerate(placements_a):
                        for index_b, second in enumerate(placements_b):
                            pair_checks += 1
                            if pair_checks > MAX_PAIR_CHECKS:
                                raise ValueError(
                                    "CP-SAT model exceeds the configured "
                                    f"{MAX_PAIR_CHECKS:,} pair-check build limit."
                                )
                            if pair_checks % 4096 == 0 and (
                                config.cancellation_event is not None
                                and config.cancellation_event.is_set()
                            ):
                                raise _BuildDeadline
                            if pair_checks % 4096 == 0 and (
                                time.perf_counter() - started
                                >= config.time_limit_s
                            ):
                                raise _BuildDeadline
                            if not _pairwise_violation(
                                instance, kind, first, second
                            ):
                                continue
                            violated_pair = model.NewBoolVar(
                                f"soft_{kind}_c{class_a}_p{index_a}_"
                                f"c{class_b}_p{index_b}"
                            )
                            first_var = variables[class_a][index_a]
                            second_var = variables[class_b][index_b]
                            model.Add(violated_pair <= first_var)
                            model.Add(violated_pair <= second_var)
                            model.Add(
                                violated_pair >= first_var + second_var - 1
                            )
                            objective_terms.append(
                                instance.distribution_weight
                                * distribution.penalty
                                * violated_pair
                            )
        except _BuildDeadline:
            if (
                config.cancellation_event is not None
                and config.cancellation_event.is_set()
            ):
                return _cancelled_during_build(
                    self, instance, config, started, pair_checks
                )
            return _timeout_during_build(
                self, instance, config, started, pair_checks
            )
        except ValueError as exc:
            return make_result(
                algorithm=self.name,
                version=self.version,
                status="unsupported",
                runtime_s=time.perf_counter() - started,
                schedule=Schedule(instance),
                config=config,
                statistics={"pair_checks": pair_checks, "model_built": False},
                termination_reason="model_size_limit",
                error=str(exc),
            )

        model.Minimize(sum(objective_terms))
        try:
            for distribution in instance.distributions:
                if not distribution.required:
                    continue
                kind = distribution.type
                if kind == "Precedence":
                    member_pairs = zip(
                        distribution.class_ids, distribution.class_ids[1:]
                    )
                elif (
                    kind in PAIRWISE_TYPES
                    or kind.startswith(("WorkDay(", "MinGap("))
                    or (
                        kind.startswith("MaxBreaks(")
                        and len(distribution.class_ids) == 2
                    )
                ):
                    member_pairs = combinations(distribution.class_ids, 2)
                else:
                    member_pairs = ()
                for class_a, class_b in member_pairs:
                    placements_a = instance.classes[class_a].placements
                    placements_b = instance.classes[class_b].placements
                    for index_a, first in enumerate(placements_a):
                        for index_b, second in enumerate(placements_b):
                            pair_checks += 1
                            if pair_checks > MAX_PAIR_CHECKS:
                                raise ValueError(
                                    "CP-SAT model exceeds the configured "
                                    f"{MAX_PAIR_CHECKS:,} pair-check build limit."
                                )
                            if pair_checks % 4096 == 0 and (
                                config.cancellation_event is not None
                                and config.cancellation_event.is_set()
                            ):
                                raise _BuildDeadline
                            if pair_checks % 4096 == 0 and (
                                time.perf_counter() - started
                                >= config.time_limit_s
                            ):
                                raise _BuildDeadline
                            if _pairwise_violation(instance, kind, first, second):
                                model.Add(
                                    variables[class_a][index_a]
                                    + variables[class_b][index_b]
                                    <= 1
                                )

                if kind.startswith("MaxDays("):
                    limit = int(kind[8:-1])
                    used_days = []
                    for day in range(instance.nr_days):
                        active = [
                            variables[class_id][index]
                            for class_id in distribution.class_ids
                            for index, placement in enumerate(
                                instance.classes[class_id].placements
                            )
                            if placement.days[day] == "1"
                        ]
                        if active:
                            day_used = model.NewBoolVar(
                                f"maxdays_{len(used_days)}_{day}"
                            )
                            model.AddMaxEquality(day_used, active)
                            used_days.append(day_used)
                    model.Add(sum(used_days) <= limit)
                elif kind.startswith("MaxDayLoad("):
                    limit = int(kind[11:-1])
                    for day in range(instance.nr_days):
                        for week in range(instance.nr_weeks):
                            load = [
                                placement.length * variables[class_id][index]
                                for class_id in distribution.class_ids
                                for index, placement in enumerate(
                                    instance.classes[class_id].placements
                                )
                                if (
                                    placement.days[day] == "1"
                                    and placement.weeks[week] == "1"
                                )
                            ]
                            model.Add(sum(load) <= limit)
                elif kind.startswith("MaxBreaks("):
                    match = re.fullmatch(r"MaxBreaks\((\d+),(\d+)\)", kind)
                    if match is None:
                        raise ValueError(
                            f"Unsupported MaxBreaks distribution: {kind}"
                        )
                    if len(distribution.class_ids) != 2:
                        max_breaks, gap_limit = map(int, match.groups())
                        _add_max_breaks_constraint(
                            model,
                            instance,
                            distribution.class_ids,
                            variables,
                            max_breaks,
                            gap_limit,
                            config,
                            started,
                        )
        except _BuildDeadline:
            if (
                config.cancellation_event is not None
                and config.cancellation_event.is_set()
            ):
                return _cancelled_during_build(
                    self, instance, config, started, pair_checks
                )
            return _timeout_during_build(
                self, instance, config, started, pair_checks
            )
        except ValueError as exc:
            return make_result(
                algorithm=self.name,
                version=self.version,
                status="unsupported",
                runtime_s=time.perf_counter() - started,
                schedule=Schedule(instance),
                config=config,
                statistics={"pair_checks": pair_checks, "model_built": False},
                termination_reason="model_size_limit",
                error=str(exc),
            )

        remaining_time = config.time_limit_s - (time.perf_counter() - started)
        if config.cancellation_event is not None and config.cancellation_event.is_set():
            return _cancelled_during_build(
                self, instance, config, started, pair_checks
            )
        if remaining_time <= 0:
            return _timeout_during_build(
                self, instance, config, started, pair_checks
            )

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = remaining_time
        solver.parameters.random_seed = config.random_seed
        solver.parameters.num_search_workers = config.workers
        watcher_stop = Event()
        watcher: Thread | None = None
        if config.cancellation_event is not None:
            def stop_when_cancelled() -> None:
                while not watcher_stop.wait(0.02):
                    if config.cancellation_event.is_set():
                        solver.StopSearch()
                        return

            watcher = Thread(target=stop_when_cancelled, daemon=True)
            watcher.start()
        try:
            status_code = solver.Solve(model)
        finally:
            watcher_stop.set()
            if watcher is not None:
                watcher.join(timeout=0.1)
        runtime = time.perf_counter() - started
        stats = {
            "status": solver.StatusName(status_code),
            "branches": solver.NumBranches(),
            "conflicts": solver.NumConflicts(),
            "pair_checks": pair_checks,
            "model_variables": len(model.Proto().variables),
            "model_constraints": len(model.Proto().constraints),
            "model_built": True,
            "optimal": status_code == cp_model.OPTIMAL,
        }

        if config.cancellation_event is not None and config.cancellation_event.is_set():
            schedule = Schedule(instance)
            if status_code in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                for class_id, class_vars in variables.items():
                    for index, variable in enumerate(class_vars):
                        if solver.BooleanValue(variable):
                            schedule.assign(
                                class_id, instance.classes[class_id].placements[index]
                            )
                            break
            return make_result(
                algorithm=self.name,
                version=self.version,
                status="cancelled",
                runtime_s=runtime,
                schedule=schedule,
                config=config,
                statistics=stats,
                termination_reason="cancelled",
            )

        if status_code in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            schedule = Schedule(instance)
            for class_id, class_vars in variables.items():
                for index, variable in enumerate(class_vars):
                    if solver.BooleanValue(variable):
                        schedule.assign(
                            class_id,
                            instance.classes[class_id].placements[index],
                        )
                        break
            return make_result(
                algorithm=self.name,
                version=self.version,
                status="complete",
                runtime_s=runtime,
                schedule=schedule,
                config=config,
                statistics=stats,
                termination_reason=(
                    "objective_optimum_proven"
                    if status_code == cp_model.OPTIMAL
                    else "feasible_assignment_found"
                ),
            )
        if status_code == cp_model.INFEASIBLE:
            return make_result(
                algorithm=self.name,
                version=self.version,
                status="infeasible_proven",
                runtime_s=runtime,
                schedule=Schedule(instance),
                config=config,
                statistics=stats,
                termination_reason="solver_proved_infeasible",
            )
        if status_code == cp_model.MODEL_INVALID:
            return make_result(
                algorithm=self.name,
                version=self.version,
                status="error",
                runtime_s=runtime,
                schedule=Schedule(instance),
                config=config,
                statistics=stats,
                termination_reason="invalid_model",
                error=f"CP-SAT rejected the generated model: {solver.StatusName(status_code)}",
            )
        return make_result(
            algorithm=self.name,
            version=self.version,
            status="timeout_unknown",
            runtime_s=runtime,
            schedule=Schedule(instance),
            config=config,
            statistics=stats,
            termination_reason=(
                "cancelled"
                if config.cancellation_event is not None
                and config.cancellation_event.is_set()
                else "solver_stopped_without_proof"
            ),
        )


def _pairwise_violation(
    instance: Instance,
    kind: str,
    first: Placement,
    second: Placement,
) -> bool:
    if kind == "Precedence":
        first_week = _first_bit(first.weeks)
        second_week = _first_bit(second.weeks)
        if first_week != second_week:
            return first_week > second_week
        first_day = _first_bit(first.days)
        second_day = _first_bit(second.days)
        if first_day != second_day:
            return first_day > second_day
        return first.start + first.length > second.start
    max_breaks = re.fullmatch(r"MaxBreaks\((\d+),(\d+)\)", kind)
    if max_breaks:
        break_limit, gap_limit = map(int, max_breaks.groups())
        for day in range(instance.nr_days):
            for week in range(instance.nr_weeks):
                intervals = sorted(
                    (placement.start, placement.start + placement.length)
                    for placement in (first, second)
                    if placement.days[day] == "1" and placement.weeks[week] == "1"
                )
                breaks = sum(
                    start - previous_end > gap_limit
                    for (_, previous_end), (start, _) in zip(
                        intervals, intervals[1:]
                    )
                )
                if breaks > break_limit:
                    return True
        return False
    from constraints import pair_distribution_violation

    return pair_distribution_violation(instance, kind, first, second)


def _first_bit(bits: str) -> int:
    return next((index for index, value in enumerate(bits) if value == "1"), 10**9)


def _cp_supports(kind: str, class_count: int) -> bool:
    return (
        kind in PAIRWISE_TYPES
        or kind == "Precedence"
        or re.fullmatch(r"WorkDay\(\d+\)|MinGap\(\d+\)", kind) is not None
        or re.fullmatch(r"MaxDays\(\d+\)|MaxDayLoad\(\d+\)", kind) is not None
        or (
            class_count >= 1
            and re.fullmatch(r"MaxBreaks\(\d+,\d+\)", kind) is not None
        )
    )


def _cp_supports_soft(kind: str) -> bool:
    return is_soft_objective_supported(kind)


def _add_max_breaks_constraint(
    model: Any,
    instance: Instance,
    class_ids: list[int],
    variables: dict[int, list[Any]],
    max_breaks: int,
    gap_limit: int,
    config: RunConfig,
    started: float,
) -> None:
    operations = 0

    def check_build_deadline() -> None:
        if (
            config.cancellation_event is not None
            and config.cancellation_event.is_set()
        ):
            raise _BuildDeadline
        if time.perf_counter() - started >= config.time_limit_s:
            raise _BuildDeadline

    for day in range(instance.nr_days):
        for week in range(instance.nr_weeks):
            slot_options: list[list[Any]] = [
                [] for _ in range(instance.slots_per_day)
            ]
            for class_id in class_ids:
                cls = instance.classes[class_id]
                for option_index, placement in enumerate(cls.placements):
                    operations += 1
                    if operations % 256 == 0:
                        check_build_deadline()
                    if placement.days[day] != "1" or placement.weeks[week] != "1":
                        continue
                    end_slot = placement.start + placement.length
                    if placement.start < 0 or end_slot > instance.slots_per_day:
                        raise ValueError(
                            f"MaxBreaks cannot model placement outside the day "
                            f"bounds for class {class_id}"
                        )
                    for slot in range(placement.start, end_slot):
                        slot_options[slot].append(variables[class_id][option_index])

            if not any(slot_options):
                continue

            occupied = [
                model.NewBoolVar(f"maxbreaks_d{day}_w{week}_t{slot}")
                for slot in range(instance.slots_per_day)
            ]
            for slot, options in enumerate(slot_options):
                if slot % 32 == 0:
                    check_build_deadline()
                if options:
                    model.AddMaxEquality(occupied[slot], options)
                else:
                    model.Add(occupied[slot] == 0)

            prior_counts: list[Any] = [0]
            recent_counts: list[Any] = [0]
            break_vars = []
            for slot in range(instance.slots_per_day):
                if slot % 32 == 0:
                    check_build_deadline()
                prior_count = prior_counts[slot]
                recent_count = recent_counts[slot]
                has_prior = model.NewBoolVar(
                    f"maxbreaks_has_prior_d{day}_w{week}_t{slot}"
                )
                model.Add(prior_count >= 1).OnlyEnforceIf(has_prior)
                model.Add(prior_count == 0).OnlyEnforceIf(has_prior.Not())
                has_recent = model.NewBoolVar(
                    f"maxbreaks_has_recent_d{day}_w{week}_t{slot}"
                )
                model.Add(recent_count >= 1).OnlyEnforceIf(has_recent)
                model.Add(recent_count == 0).OnlyEnforceIf(has_recent.Not())
                far_before = model.NewBoolVar(
                    f"maxbreaks_far_before_d{day}_w{week}_t{slot}"
                )
                model.Add(far_before <= has_prior)
                model.Add(far_before + has_recent <= 1)
                model.Add(far_before >= has_prior - has_recent)

                block_start = model.NewBoolVar(
                    f"maxbreaks_block_start_d{day}_w{week}_t{slot}"
                )
                if slot == 0:
                    model.Add(block_start == occupied[slot])
                else:
                    model.Add(block_start <= occupied[slot])
                    model.Add(block_start + occupied[slot - 1] <= 1)
                    model.Add(
                        block_start >= occupied[slot] - occupied[slot - 1]
                    )

                is_break = model.NewBoolVar(
                    f"maxbreaks_break_d{day}_w{week}_t{slot}"
                )
                model.Add(is_break <= block_start)
                model.Add(is_break <= far_before)
                model.Add(is_break >= block_start + far_before - 1)
                break_vars.append(is_break)

                next_prior = model.NewIntVar(
                    0,
                    slot + 1,
                    f"maxbreaks_prior_count_d{day}_w{week}_t{slot + 1}",
                )
                model.Add(next_prior == prior_count + occupied[slot])
                prior_counts.append(next_prior)

                expired_slot = slot - gap_limit - 1
                expired = (
                    occupied[expired_slot] if expired_slot >= 0 else 0
                )
                next_recent = model.NewIntVar(
                    0,
                    min(slot + 1, gap_limit + 1),
                    f"maxbreaks_recent_count_d{day}_w{week}_t{slot + 1}",
                )
                model.Add(
                    next_recent == recent_count + occupied[slot] - expired
                )
                recent_counts.append(next_recent)

            model.Add(sum(break_vars) <= max_breaks)


def _timeout_during_build(
    algorithm: CpSatAlgorithm,
    instance: Instance,
    config: RunConfig,
    started: float,
    pair_checks: int,
) -> AlgorithmResult:
    return make_result(
        algorithm=algorithm.name,
        version=algorithm.version,
        status="timeout_unknown",
        runtime_s=time.perf_counter() - started,
        schedule=Schedule(instance),
        config=config,
        statistics={"pair_checks": pair_checks, "model_built": False},
        termination_reason="time_limit_during_model_build",
    )


def _cancelled_during_build(
    algorithm: CpSatAlgorithm,
    instance: Instance,
    config: RunConfig,
    started: float,
    pair_checks: int,
) -> AlgorithmResult:
    return make_result(
        algorithm=algorithm.name,
        version=algorithm.version,
        status="cancelled",
        runtime_s=time.perf_counter() - started,
        schedule=Schedule(instance),
        config=config,
        statistics={"pair_checks": pair_checks, "model_built": False},
        termination_reason="cancelled_during_model_build",
    )
