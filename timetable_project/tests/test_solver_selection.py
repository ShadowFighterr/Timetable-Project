import unittest

from model import Placement, Schedule
from parser import Class, Distribution, Instance
from solver import CSPSolver, _validate_final_schedule


def _placement(start: int) -> Placement:
    return Placement(
        room_id=None,
        days="10000",
        start=start,
        length=10,
        weeks="10",
        time_penalty=0,
        room_penalty=0,
    )


def _instance_with_domains(domain_sizes, distributions=()):
    classes = {
        class_id: Class(
            id=class_id,
            course_id=class_id,
            config_id=class_id,
            subpart_id=class_id,
            limit=0,
            parent_id=None,
            room_required=False,
            placements=[
                _placement(start)
                for start in starts
            ],
        )
        for class_id, starts in domain_sizes.items()
    }
    return Instance(
        name="selection-test",
        nr_days=5,
        slots_per_day=288,
        nr_weeks=2,
        rooms={},
        courses={},
        configs={},
        subparts={},
        classes=classes,
        distributions=list(distributions),
        students={},
        time_weight=0,
        room_weight=0,
        distribution_weight=0,
        student_weight=0,
    )


class VariableSelectionTests(unittest.TestCase):
    def test_final_validation_uses_constraint_report_schema(self) -> None:
        instance = _instance_with_domains({1: [20]})
        schedule = Schedule(instance)
        schedule.assign(1, instance.classes[1].placements[0])

        violations, feasible = _validate_final_schedule(instance, schedule)

        self.assertEqual(
            violations,
            {
                "unassigned": 0,
                "room": 0,
                "required_distribution": 0,
                "other": 0,
            },
        )
        self.assertTrue(feasible)

    def test_static_baseline_uses_original_domain_size(self) -> None:
        instance = _instance_with_domains(
            {
                1: [10, 20, 30, 40],
                2: [10, 20, 30],
                3: [10],
            },
            [
                Distribution(
                    type="SameStart",
                    required=True,
                    penalty=0,
                    class_ids=[1, 3],
                )
            ],
        )
        solver = CSPSolver(instance, variable_selection="static")
        solver.assign(3, instance.classes[3].placements[0])

        selected_class, values = solver.select_unassigned_class()

        self.assertEqual(selected_class, 2)
        self.assertEqual(len(values), 3)

    def test_dynamic_mrv_uses_current_legal_domain_sizes(self) -> None:
        instance = _instance_with_domains(
            {
                1: [10, 20, 30, 40],
                2: [10, 20, 30],
                3: [10],
            },
            [
                Distribution(
                    type="SameStart",
                    required=True,
                    penalty=0,
                    class_ids=[1, 3],
                )
            ],
        )
        solver = CSPSolver(instance, variable_selection="dynamic")
        solver.assign(3, instance.classes[3].placements[0])

        selected_class, values = solver.select_unassigned_class()

        self.assertEqual(selected_class, 1)
        self.assertEqual(len(values), 1)

    def test_dynamic_mrv_degree_tie_break_counts_only_unassigned_neighbors(self) -> None:
        distributions = [
            Distribution(
                type="SameStart",
                required=True,
                penalty=0,
                class_ids=[1, 4],
            ),
            Distribution(
                type="SameStart",
                required=True,
                penalty=0,
                class_ids=[2, 3],
            ),
            Distribution(
                type="SameStart",
                required=True,
                penalty=0,
                class_ids=[2, 5],
            ),
        ]
        instance = _instance_with_domains(
            {
                1: [20, 20],
                2: [10, 10],
                3: [10],
                4: [20, 20],
                5: [10],
            },
            distributions,
        )
        solver = CSPSolver(instance, variable_selection="dynamic")
        solver.assign(3, instance.classes[3].placements[0])
        solver.assign(5, instance.classes[5].placements[0])

        selected_class, values = solver.select_unassigned_class()

        self.assertEqual(selected_class, 1)
        self.assertEqual(len(values), 2)

    def test_dynamic_selector_returns_none_when_all_classes_assigned(self) -> None:
        instance = _instance_with_domains({1: [10]})
        solver = CSPSolver(instance, variable_selection="dynamic")
        solver.assign(1, instance.classes[1].placements[0])

        selected_class, values = solver.select_unassigned_class()

        self.assertIsNone(selected_class)
        self.assertEqual(values, [])

    def test_unknown_strategy_is_rejected(self) -> None:
        instance = _instance_with_domains({1: [10]})

        with self.assertRaises(ValueError):
            CSPSolver(instance, variable_selection="other")


if __name__ == "__main__":
    unittest.main()
