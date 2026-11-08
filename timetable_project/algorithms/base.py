"""Shared input, run configuration, and result contract for algorithms."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import math
from threading import Event
from typing import Any, Literal

from model import Schedule
from parser import Instance
from validation import ValidationReport, validate_schedule_independently


RunStatus = Literal[
    "complete",
    "partial",
    "infeasible_proven",
    "timeout_unknown",
    "cancelled",
    "unsupported",
    "error",
]


@dataclass(frozen=True)
class RunConfig:
    time_limit_s: float = 60.0
    random_seed: int = 0
    workers: int = 1
    node_limit: int | None = None
    options: dict[str, Any] = field(default_factory=dict)
    cancellation_event: Event | None = field(
        default=None, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if not math.isfinite(self.time_limit_s) or self.time_limit_s < 0:
            raise ValueError("time_limit_s must be non-negative")
        if self.workers != 1:
            raise ValueError(
                "Current benchmark adapters use one worker for comparable runs"
            )
        if self.node_limit is not None and self.node_limit < 1:
            raise ValueError("node_limit must be positive when set")


@dataclass
class AlgorithmResult:
    algorithm: str
    version: str
    status: RunStatus
    runtime_s: float
    assignment_coverage: float
    validation: ValidationReport
    configuration: RunConfig
    search_statistics: dict[str, Any] = field(default_factory=dict)
    objective_score: int | None = None
    termination_reason: str | None = None
    error: str | None = None
    schedule: Schedule | None = field(default=None, repr=False, compare=False)

    @property
    def successful(self) -> bool:
        return self.status == "complete" and self.validation.valid_complete

    def to_dict(self) -> dict[str, Any]:
        assignments: list[dict[str, Any]] = []
        if self.schedule is not None:
            assignments = [
                {
                    "class_id": class_id,
                    "room_id": placement.room_id,
                    "days": placement.days,
                    "start": placement.start,
                    "length": placement.length,
                    "weeks": placement.weeks,
                    "time_penalty": placement.time_penalty,
                    "room_penalty": placement.room_penalty,
                }
                for class_id, placement in sorted(
                    self.schedule.assignments.items()
                )
            ]
        return {
            "algorithm": self.algorithm,
            "version": self.version,
            "status": self.status,
            "runtime_s": self.runtime_s,
            "assignment_coverage": self.assignment_coverage,
            "validation": self.validation.to_dict(),
            "objective_score": self.objective_score,
            "configuration": {
                "time_limit_s": self.configuration.time_limit_s,
                "random_seed": self.configuration.random_seed,
                "workers": self.configuration.workers,
                "node_limit": self.configuration.node_limit,
                "options": self.configuration.options,
            },
            "search_statistics": self.search_statistics,
            "termination_reason": self.termination_reason,
            "successful": self.successful,
            "error": self.error,
            "assignments": assignments,
        }


class SchedulingAlgorithm(ABC):
    name: str
    version: str

    @abstractmethod
    def run(self, instance: Instance, config: RunConfig) -> AlgorithmResult:
        """Generate a schedule and independently validate its result."""


def make_result(
    *,
    algorithm: str,
    version: str,
    status: RunStatus,
    runtime_s: float,
    schedule: Schedule,
    config: RunConfig,
    statistics: dict[str, Any] | None = None,
    termination_reason: str | None = None,
    error: str | None = None,
) -> AlgorithmResult:
    report = validate_schedule_independently(schedule.instance, schedule)
    return AlgorithmResult(
        algorithm=algorithm,
        version=version,
        status=status,
        runtime_s=runtime_s,
        assignment_coverage=report.assignment_coverage,
        validation=report,
        configuration=config,
        search_statistics=statistics or {},
        objective_score=report.objective_score,
        termination_reason=termination_reason,
        error=error,
        schedule=schedule,
    )
