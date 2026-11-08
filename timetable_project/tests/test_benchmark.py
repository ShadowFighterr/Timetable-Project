from __future__ import annotations

import unittest
from threading import Event

from algorithms import CpSatAlgorithm, CspAlgorithm, RunConfig
from benchmarks.synthetic import (
    make_synthetic_instance,
    make_synthetic_objective_instance,
)
from model import Schedule
from parser import Class, Distribution, Placement, Student
from validation import validate_schedule_independently


def make_max_breaks_instance(
    starts: tuple[int, int, int],
    *,
    max_breaks: int = 0,
    gap_limit: int = 5,
):
    instance = make_synthetic_instance()
    instance.slots_per_day = 48
    for class_id in (1, 2):
        instance.classes[class_id].room_required = False
    instance.classes[3] = Class(
        id=3,
        course_id=3,
        config_id=3,
        subpart_id=3,
        limit=0,
        parent_id=None,
        room_required=False,
    )
    for class_id, start in enumerate(starts, start=1):
        instance.classes[class_id].placements = [
            Placement(
                room_id=None,
                days="1",
                start=start,
                length=2,
                weeks="1",
                time_penalty=0,
                room_penalty=0,
            )
        ]
    instance.distributions.append(
        Distribution(
            type=f"MaxBreaks({max_breaks},{gap_limit})",
            required=True,
            penalty=0,
            class_ids=[1, 2, 3],
        )
    )
    return instance


def make_soft_not_overlap_instance(second_starts: tuple[int, ...]):
    instance = make_synthetic_instance()
    for cls in instance.classes.values():
        cls.room_required = False
    instance.classes[1].placements = [
        Placement(
            room_id=None,
            days="1",
            start=10,
            length=2,
            weeks="1",
            time_penalty=0,
            room_penalty=0,
        )
    ]
    instance.classes[2].placements = [
        Placement(
            room_id=None,
            days="1",
            start=start,
            length=2,
            weeks="1",
            time_penalty=0,
            room_penalty=0,
        )
        for start in second_starts
    ]
    instance.distribution_weight = 3
    instance.distributions.append(
        Distribution(
            type="NotOverlap",
            required=False,
            penalty=5,
            class_ids=[1, 2],
        )
    )
    return instance


class IndependentValidatorTests(unittest.TestCase):
    def test_partial_assignment_is_not_a_complete_valid_timetable(self) -> None:
        instance = make_synthetic_instance()
        schedule = Schedule(instance)
        schedule.assign(1, instance.classes[1].placements[0])

        report = validate_schedule_independently(instance, schedule)

        self.assertFalse(report.complete)
        self.assertFalse(report.valid_complete)
        self.assertEqual(report.missing_assignments, [2])
        self.assertEqual(report.assignment_coverage, 0.5)

    def test_room_overlap_is_detected_independently(self) -> None:
        instance = make_synthetic_instance(impossible=True)
        schedule = Schedule(instance)
        schedule.assign(1, instance.classes[1].placements[0])
        schedule.assign(2, instance.classes[2].placements[0])

        report = validate_schedule_independently(instance, schedule)

        self.assertTrue(report.complete)
        self.assertFalse(report.valid_complete)
        self.assertEqual(len(report.room_occupancy_conflicts), 1)

    def test_unknown_required_distribution_prevents_full_validation_claim(self) -> None:
        instance = make_synthetic_instance()
        instance.distributions.append(
            Distribution(
                type="UnknownHardRule",
                required=True,
                penalty=0,
                class_ids=[1, 2],
            )
        )
        schedule = Schedule(instance)
        for class_id, cls in instance.classes.items():
            schedule.assign(class_id, cls.placements[-1])

        report = validate_schedule_independently(instance, schedule)

        self.assertFalse(report.validation_complete)
        self.assertFalse(report.valid_complete)
        self.assertEqual(
            report.unsupported_constraints[0]["type"],
            "UnknownHardRule",
        )

    def test_missing_enrollment_makes_capacity_validation_incomplete(self) -> None:
        instance = make_synthetic_instance()
        instance.classes[1].expected_enrollment = None
        schedule = Schedule(instance)
        for class_id, cls in instance.classes.items():
            schedule.assign(class_id, cls.placements[-1])

        report = validate_schedule_independently(instance, schedule)

        self.assertFalse(report.room_capacity_evaluated)
        self.assertFalse(report.validation_complete)
        self.assertFalse(report.valid_complete)
        self.assertIn(
            "RoomCapacity(actual enrollment unavailable)",
            [item["type"] for item in report.unsupported_constraints],
        )

    def test_missing_room_capacity_makes_capacity_validation_incomplete(self) -> None:
        instance = make_synthetic_instance()
        instance.rooms[1].capacity = None
        schedule = Schedule(instance)
        for class_id, cls in instance.classes.items():
            schedule.assign(class_id, cls.placements[-1])

        report = validate_schedule_independently(instance, schedule)

        self.assertFalse(report.room_capacity_evaluated)
        self.assertFalse(report.validation_complete)
        self.assertIn(
            "RoomCapacity(room capacity unavailable)",
            [item["type"] for item in report.unsupported_constraints],
        )

    def test_same_attendees_overlap_is_reported(self) -> None:
        instance = make_synthetic_instance(impossible=True)
        instance.distributions.append(
            Distribution(
                type="SameAttendees",
                required=True,
                penalty=0,
                class_ids=[1, 2],
            )
        )
        schedule = Schedule(instance)
        for class_id, cls in instance.classes.items():
            schedule.assign(class_id, cls.placements[0])

        report = validate_schedule_independently(instance, schedule)

        self.assertEqual(report.same_attendees_violations, 1)
        self.assertFalse(report.valid_complete)

    def test_explicit_capacity_instructor_and_group_conflicts_are_reported(self) -> None:
        instance = make_synthetic_instance(impossible=True)
        instance.classes[1].expected_enrollment = 50
        instance.classes[1].instructor_ids = [9]
        instance.classes[2].instructor_ids = [9]
        instance.classes[1].student_group_ids = [4]
        instance.classes[2].student_group_ids = [4]
        schedule = Schedule(instance)
        for class_id, cls in instance.classes.items():
            schedule.assign(class_id, cls.placements[0])

        report = validate_schedule_independently(instance, schedule)

        self.assertEqual(report.room_capacity_violations, [1])
        self.assertEqual(report.instructor_conflicts, 1)
        self.assertEqual(report.student_conflicts, 1)
        self.assertFalse(report.valid_complete)

    def test_global_day_load_violation_is_reported(self) -> None:
        instance = make_synthetic_instance()
        instance.distributions.append(
            Distribution(
                type="MaxDayLoad(3)",
                required=True,
                penalty=0,
                class_ids=[1, 2],
            )
        )
        schedule = Schedule(instance)
        for class_id, cls in instance.classes.items():
            schedule.assign(class_id, cls.placements[-1])

        report = validate_schedule_independently(instance, schedule)

        self.assertEqual(
            report.required_distribution_violations[0]["type"],
            "MaxDayLoad(3)",
        )
        self.assertFalse(report.valid_complete)

    def test_max_breaks_accepts_a_bridge_and_gap_equal_to_limit(self) -> None:
        instance = make_max_breaks_instance((10, 20, 15))
        schedule = Schedule(instance)
        for class_id, cls in instance.classes.items():
            schedule.assign(class_id, cls.placements[0])

        report = validate_schedule_independently(instance, schedule)

        self.assertTrue(report.valid_complete)
        self.assertEqual(report.required_distribution_violations, [])

        boundary = make_max_breaks_instance((10, 17, 22))
        boundary_schedule = Schedule(boundary)
        for class_id, cls in boundary.classes.items():
            boundary_schedule.assign(class_id, cls.placements[0])

        boundary_report = validate_schedule_independently(
            boundary, boundary_schedule
        )
        self.assertTrue(boundary_report.valid_complete)

    def test_max_breaks_rejects_gap_one_slot_over_limit(self) -> None:
        instance = make_max_breaks_instance(
            (10, 18, 26), max_breaks=1, gap_limit=5
        )
        schedule = Schedule(instance)
        for class_id, cls in instance.classes.items():
            schedule.assign(class_id, cls.placements[0])

        report = validate_schedule_independently(instance, schedule)
        self.assertEqual(
            report.required_distribution_violations[0]["type"],
            "MaxBreaks(1,5)",
        )
        self.assertFalse(report.valid_complete)

    def test_max_breaks_allows_exactly_the_configured_number_of_breaks(self) -> None:
        instance = make_max_breaks_instance(
            (10, 18, 20), max_breaks=1, gap_limit=5
        )
        schedule = Schedule(instance)
        for class_id, cls in instance.classes.items():
            schedule.assign(class_id, cls.placements[0])

        report = validate_schedule_independently(instance, schedule)

        self.assertTrue(report.valid_complete)
        self.assertEqual(report.required_distribution_violations, [])

    def test_soft_distribution_objective_counts_each_violating_pair(self) -> None:
        instance = make_soft_not_overlap_instance((10,))
        instance.classes[3] = Class(
            id=3,
            course_id=3,
            config_id=3,
            subpart_id=3,
            limit=0,
            parent_id=None,
            room_required=False,
            placements=[
                Placement(
                    room_id=None,
                    days="1",
                    start=10,
                    length=2,
                    weeks="1",
                    time_penalty=0,
                    room_penalty=0,
                )
            ],
        )
        instance.distributions[0].class_ids = [1, 2, 3]
        schedule = Schedule(instance)
        for class_id, cls in instance.classes.items():
            schedule.assign(class_id, cls.placements[0])

        report = validate_schedule_independently(instance, schedule)

        self.assertTrue(report.valid_complete)
        self.assertEqual(report.objective_score, 45)
        self.assertEqual(report.objective_components["soft_distribution_penalty"], 45)

    def test_soft_precedence_objective_is_scored_independently(self) -> None:
        instance = make_synthetic_instance()
        for cls in instance.classes.values():
            cls.room_required = False
        instance.distribution_weight = 3
        instance.distributions.append(
            Distribution(
                type="Precedence",
                required=False,
                penalty=5,
                class_ids=[1, 2],
            )
        )
        for class_id, start in ((1, 12), (2, 10)):
            instance.classes[class_id].placements = [
                Placement(
                    room_id=None,
                    days="1",
                    start=start,
                    length=2,
                    weeks="1",
                    time_penalty=0,
                    room_penalty=0,
                )
            ]
        schedule = Schedule(instance)
        for class_id, cls in instance.classes.items():
            schedule.assign(class_id, cls.placements[0])

        report = validate_schedule_independently(instance, schedule)

        self.assertTrue(report.valid_complete)
        self.assertEqual(report.objective_score, 15)
        self.assertEqual(
            report.objective_components["soft_distribution_penalty"],
            15,
        )


class AlgorithmAdapterTests(unittest.TestCase):
    def test_both_adapters_optimize_positive_common_synthetic_objective(self) -> None:
        instance = make_synthetic_objective_instance()

        results = [
            algorithm.run(instance, RunConfig(time_limit_s=30))
            for algorithm in (CspAlgorithm(), CpSatAlgorithm())
        ]

        for result in results:
            with self.subTest(algorithm=result.algorithm):
                self.assertTrue(result.successful)
                self.assertEqual(result.objective_score, 15)
                self.assertTrue(result.validation.valid_complete)
        self.assertTrue(results[0].search_statistics["objective_optimal"])
        self.assertTrue(results[1].search_statistics["optimal"])
        self.assertEqual(results[0].termination_reason, "objective_optimum_proven")
        self.assertEqual(results[1].termination_reason, "objective_optimum_proven")

    def test_csp_finds_independently_valid_complete_schedule(self) -> None:
        result = CspAlgorithm().run(
            make_synthetic_instance(),
            RunConfig(time_limit_s=5),
        )

        self.assertEqual(result.status, "complete")
        self.assertTrue(result.successful)
        self.assertEqual(result.assignment_coverage, 1.0)

    def test_csp_minimizes_weighted_soft_distribution_objective(self) -> None:
        instance = make_soft_not_overlap_instance((10, 12))

        result = CspAlgorithm().run(instance, RunConfig(time_limit_s=5))

        self.assertEqual(result.status, "complete")
        self.assertTrue(result.successful)
        self.assertEqual(result.schedule.assignments[2].start, 12)
        self.assertEqual(result.objective_score, 0)
        self.assertTrue(result.search_statistics["objective_optimal"])

    def test_csp_reports_proven_optimum_for_forced_positive_objective(self) -> None:
        instance = make_soft_not_overlap_instance((10,))

        result = CspAlgorithm().run(instance, RunConfig(time_limit_s=5))

        self.assertEqual(result.status, "complete")
        self.assertTrue(result.successful)
        self.assertEqual(result.objective_score, 15)
        self.assertTrue(result.search_statistics["objective_optimal"])
        self.assertEqual(result.termination_reason, "objective_optimum_proven")

    def test_csp_rejects_missing_student_sectioning_objective(self) -> None:
        instance = make_synthetic_instance()
        instance.student_weight = 8
        instance.students[1] = Student(id=1, course_ids=[1])

        result = CspAlgorithm().run(instance, RunConfig(time_limit_s=5))

        self.assertEqual(result.status, "unsupported")
        self.assertEqual(
            result.termination_reason,
            "unsupported_student_objective",
        )

    def test_csp_rejects_unmodeled_soft_global_objective(self) -> None:
        instance = make_synthetic_instance()
        instance.distributions.append(
            Distribution(
                type="MaxDays(1)",
                required=False,
                penalty=2,
                class_ids=[1, 2],
            )
        )

        result = CspAlgorithm().run(instance, RunConfig(time_limit_s=5))

        self.assertEqual(result.status, "unsupported")
        self.assertEqual(result.termination_reason, "unsupported_soft_objective")

    def test_cpsat_minimizes_weighted_placement_penalties(self) -> None:
        instance = make_synthetic_instance()
        for class_id, starts in ((1, (10, 14)), (2, (12, 16))):
            instance.classes[class_id].room_required = False
            instance.classes[class_id].placements = [
                Placement(
                    room_id=None,
                    days="1",
                    start=start,
                    length=2,
                    weeks="1",
                    time_penalty=5 if start == 10 else 3 if start == 16 else 0,
                    room_penalty=0,
                )
                for start in starts
            ]

        result = CpSatAlgorithm().run(instance, RunConfig(time_limit_s=30))

        self.assertEqual(result.status, "complete")
        self.assertTrue(result.successful)
        self.assertEqual(result.objective_score, 0)
        self.assertEqual(result.schedule.assignments[1].start, 14)
        self.assertEqual(result.schedule.assignments[2].start, 12)

    def test_cpsat_optimizes_weighted_soft_distribution_penalties(self) -> None:
        instance = make_soft_not_overlap_instance((10, 12))

        result = CpSatAlgorithm().run(instance, RunConfig(time_limit_s=30))

        self.assertEqual(result.status, "complete")
        self.assertTrue(result.successful)
        self.assertEqual(result.schedule.assignments[2].start, 12)
        self.assertEqual(result.objective_score, 0)

    def test_cpsat_scores_forced_soft_distribution_penalty(self) -> None:
        instance = make_soft_not_overlap_instance((10,))

        result = CpSatAlgorithm().run(instance, RunConfig(time_limit_s=30))

        self.assertEqual(result.status, "complete")
        self.assertTrue(result.successful)
        self.assertEqual(result.objective_score, 15)
        self.assertEqual(
            result.validation.objective_components["soft_distribution_penalty"],
            15,
        )
        self.assertEqual(result.termination_reason, "objective_optimum_proven")

    def test_cpsat_soft_precedence_matches_independent_objective_score(self) -> None:
        instance = make_synthetic_instance()
        for cls in instance.classes.values():
            cls.room_required = False
        instance.distribution_weight = 3
        instance.distributions.append(
            Distribution(
                type="Precedence",
                required=False,
                penalty=5,
                class_ids=[1, 2],
            )
        )
        for class_id, start in ((1, 12), (2, 10)):
            instance.classes[class_id].placements = [
                Placement(
                    room_id=None,
                    days="1",
                    start=start,
                    length=2,
                    weeks="1",
                    time_penalty=0,
                    room_penalty=0,
                )
            ]

        result = CpSatAlgorithm().run(instance, RunConfig(time_limit_s=30))

        self.assertEqual(result.status, "complete")
        self.assertTrue(result.successful)
        self.assertEqual(result.objective_score, 15)

    def test_cpsat_rejects_unmodeled_soft_global_objective(self) -> None:
        instance = make_synthetic_instance()
        instance.distributions.append(
            Distribution(
                type="MaxDays(1)",
                required=False,
                penalty=2,
                class_ids=[1, 2],
            )
        )

        result = CpSatAlgorithm().run(instance, RunConfig(time_limit_s=30))

        self.assertEqual(result.status, "unsupported")
        self.assertIn("MaxDays(1)", result.error or "")

    def test_cpsat_rejects_missing_student_objective_inputs(self) -> None:
        instance = make_synthetic_instance()
        instance.student_weight = 8
        instance.students[1] = Student(id=1, course_ids=[1])

        result = CpSatAlgorithm().run(instance, RunConfig(time_limit_s=30))

        self.assertEqual(result.status, "unsupported")
        self.assertIn("jointly optimize student section choices", result.error or "")

    def test_csp_proves_synthetic_room_conflict_infeasible(self) -> None:
        result = CspAlgorithm().run(
            make_synthetic_instance(impossible=True),
            RunConfig(time_limit_s=5),
        )

        self.assertEqual(result.status, "infeasible_proven")
        self.assertFalse(result.successful)

    def test_csp_enforces_explicit_room_capacity(self) -> None:
        instance = make_synthetic_instance()
        instance.classes[1].expected_enrollment = 50

        result = CspAlgorithm().run(instance, RunConfig(time_limit_s=5))

        self.assertEqual(result.status, "infeasible_proven")
        self.assertEqual(result.validation.room_capacity_violations, [])

    def test_csp_preserves_partial_assignment_at_node_limit(self) -> None:
        result = CspAlgorithm().run(
            make_synthetic_instance(),
            RunConfig(time_limit_s=5, node_limit=2),
        )

        self.assertEqual(result.status, "partial")
        self.assertGreater(result.assignment_coverage, 0)
        self.assertFalse(result.validation.valid_complete)
        self.assertEqual(result.termination_reason, "node_limit")

    def test_csp_timeout_is_not_reported_as_infeasible(self) -> None:
        result = CspAlgorithm().run(
            make_synthetic_instance(),
            RunConfig(time_limit_s=0),
        )

        self.assertEqual(result.status, "timeout_unknown")
        self.assertNotEqual(result.status, "infeasible_proven")

    def test_csp_honors_pre_requested_cancellation(self) -> None:
        cancelled = Event()
        cancelled.set()
        result = CspAlgorithm().run(
            make_synthetic_instance(),
            RunConfig(time_limit_s=5, cancellation_event=cancelled),
        )

        self.assertEqual(result.status, "cancelled")
        self.assertEqual(result.termination_reason, "cancelled")

    def test_cpsat_finds_independently_valid_complete_schedule(self) -> None:
        result = CpSatAlgorithm().run(
            make_synthetic_instance(),
            RunConfig(time_limit_s=30),
        )

        self.assertEqual(result.status, "complete")
        self.assertTrue(result.successful)

    def test_cpsat_proves_synthetic_room_conflict_infeasible(self) -> None:
        result = CpSatAlgorithm().run(
            make_synthetic_instance(impossible=True),
            RunConfig(time_limit_s=30),
        )

        self.assertEqual(result.status, "infeasible_proven")
        self.assertFalse(result.successful)

    def test_cpsat_enforces_explicit_room_capacity(self) -> None:
        instance = make_synthetic_instance()
        instance.classes[1].expected_enrollment = 50

        result = CpSatAlgorithm().run(instance, RunConfig(time_limit_s=30))

        self.assertEqual(result.status, "infeasible_proven")
    def test_cpsat_enforces_required_pairwise_distribution(self) -> None:
        instance = make_synthetic_instance()
        for cls in instance.classes.values():
            cls.room_required = False
            cls.placements = [
                Placement(
                    room_id=None,
                    days=placement.days,
                    start=placement.start,
                    length=placement.length,
                    weeks=placement.weeks,
                    time_penalty=placement.time_penalty,
                    room_penalty=placement.room_penalty,
                )
                for placement in cls.placements
            ]
        instance.distributions.append(
            Distribution(
                type="SameStart",
                required=True,
                penalty=0,
                class_ids=[1, 2],
            )
        )

        result = CpSatAlgorithm().run(instance, RunConfig(time_limit_s=30))

        self.assertEqual(result.status, "complete")
        self.assertTrue(result.successful)
        self.assertEqual(
            result.schedule.assignments[1].start,
            result.schedule.assignments[2].start,
        )

    def test_cpsat_enforces_max_day_load(self) -> None:
        instance = make_synthetic_instance()
        instance.distributions.append(
            Distribution(
                type="MaxDayLoad(3)",
                required=True,
                penalty=0,
                class_ids=[1, 2],
            )
        )

        result = CpSatAlgorithm().run(instance, RunConfig(time_limit_s=30))

        self.assertEqual(result.status, "infeasible_proven")

    def test_cpsat_enforces_three_class_max_breaks_and_validator_agrees(self) -> None:
        instance = make_max_breaks_instance((10, 20, 15))

        result = CpSatAlgorithm().run(instance, RunConfig(time_limit_s=30))

        self.assertEqual(result.status, "complete")
        self.assertTrue(result.successful)
        report = validate_schedule_independently(instance, result.schedule)
        self.assertTrue(report.valid_complete)
        self.assertEqual(report.required_distribution_violations, [])

    def test_cpsat_accepts_three_class_gap_equal_to_limit(self) -> None:
        instance = make_max_breaks_instance((10, 17, 22))

        result = CpSatAlgorithm().run(instance, RunConfig(time_limit_s=30))

        self.assertEqual(result.status, "complete")
        self.assertTrue(result.successful)
        self.assertTrue(
            validate_schedule_independently(instance, result.schedule).valid_complete
        )

    def test_cpsat_preserves_two_class_max_breaks_support(self) -> None:
        instance = make_synthetic_instance()
        instance.slots_per_day = 48
        for cls in instance.classes.values():
            cls.room_required = False
            cls.placements = [
                Placement(
                    room_id=None,
                    days="1",
                    start=start,
                    length=2,
                    weeks="1",
                    time_penalty=0,
                    room_penalty=0,
                )
                for start in ((10,) if cls.id == 1 else (18,))
            ]
        instance.distributions.append(
            Distribution(
                type="MaxBreaks(0,5)",
                required=True,
                penalty=0,
                class_ids=[1, 2],
            )
        )

        result = CpSatAlgorithm().run(instance, RunConfig(time_limit_s=30))

        self.assertEqual(result.status, "infeasible_proven")

    def test_cpsat_proves_three_class_max_breaks_violation_infeasible(self) -> None:
        instance = make_max_breaks_instance(
            (10, 18, 26), max_breaks=1, gap_limit=5
        )
        result = CpSatAlgorithm().run(instance, RunConfig(time_limit_s=30))

        self.assertEqual(result.status, "infeasible_proven")
        schedule = Schedule(instance)
        for class_id, cls in instance.classes.items():
            schedule.assign(class_id, cls.placements[0])
        report = validate_schedule_independently(instance, schedule)
        self.assertFalse(report.valid_complete)
        self.assertEqual(
            report.required_distribution_violations[0]["type"],
            "MaxBreaks(1,5)",
        )

    def test_cpsat_preserves_explicit_rejection_of_unknown_hard_rule(self) -> None:
        instance = make_synthetic_instance()
        instance.distributions.append(
            Distribution(
                type="UnknownHardRule",
                required=True,
                penalty=0,
                class_ids=[1, 2],
            )
        )

        result = CpSatAlgorithm().run(instance, RunConfig(time_limit_s=30))

        self.assertEqual(result.status, "unsupported")
        self.assertIn("UnknownHardRule", result.error or "")

    def test_cpsat_zero_time_budget_is_timeout_not_infeasible(self) -> None:
        result = CpSatAlgorithm().run(
            make_synthetic_instance(),
            RunConfig(time_limit_s=0),
        )

        self.assertEqual(result.status, "timeout_unknown")
        self.assertNotEqual(result.status, "infeasible_proven")

    def test_cpsat_honors_pre_requested_cancellation(self) -> None:
        cancelled = Event()
        cancelled.set()
        result = CpSatAlgorithm().run(
            make_synthetic_instance(),
            RunConfig(time_limit_s=5, cancellation_event=cancelled),
        )

        self.assertEqual(result.status, "cancelled")
        self.assertEqual(result.termination_reason, "cancelled_before_model_build")


if __name__ == "__main__":
    unittest.main()
