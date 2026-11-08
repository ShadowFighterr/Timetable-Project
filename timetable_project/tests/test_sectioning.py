from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from model import Schedule
from api.app import _deserialize_instance, _serialize_instance
from parser import (
    Class,
    Config,
    Course,
    Instance,
    Placement,
    Room,
    Student,
    Subpart,
    parse_instance,
    validate_instance,
)
from sectioning import (
    StudentSectioning,
    sectioning_from_instance,
    solve_sectioning,
    validate_sectioning_independently,
)


def make_sectioning_instance(
    *,
    room_capacity: int = 2,
    section_limit: int = 2,
) -> tuple[Instance, Schedule]:
    classes = {
        101: Class(
            id=101,
            course_id=1,
            config_id=11,
            subpart_id=111,
            limit=section_limit,
            parent_id=None,
            room_required=True,
            placements=[
                Placement(1, "1", 10, 2, "1", 0, 0),
            ],
        ),
        102: Class(
            id=102,
            course_id=1,
            config_id=11,
            subpart_id=111,
            limit=section_limit,
            parent_id=None,
            room_required=True,
            placements=[
                Placement(1, "1", 20, 2, "1", 0, 0),
            ],
        ),
        201: Class(
            id=201,
            course_id=2,
            config_id=21,
            subpart_id=211,
            limit=2,
            parent_id=None,
            room_required=True,
            placements=[
                Placement(2, "1", 10, 2, "1", 0, 0),
            ],
        ),
    }
    instance = Instance(
        name="sectioning-fixture",
        nr_days=1,
        slots_per_day=24,
        nr_weeks=1,
        rooms={
            1: Room(id=1, capacity=room_capacity),
            2: Room(id=2, capacity=2),
        },
        courses={
            1: Course(id=1, config_ids=[11]),
            2: Course(id=2, config_ids=[21]),
        },
        configs={
            11: Config(id=11, course_id=1, subpart_ids=[111]),
            21: Config(id=21, course_id=2, subpart_ids=[211]),
        },
        subparts={
            111: Subpart(id=111, config_id=11, class_ids=[101, 102]),
            211: Subpart(id=211, config_id=21, class_ids=[201]),
        },
        classes=classes,
        distributions=[],
        students={
            1: Student(id=1, course_ids=[1, 2]),
            2: Student(id=2, course_ids=[1]),
        },
        time_weight=3,
        room_weight=1,
        distribution_weight=16,
        student_weight=8,
    )
    schedule = Schedule(instance)
    for class_id, cls in classes.items():
        schedule.assign(class_id, cls.placements[0])
    return instance, schedule


class StudentSectioningTests(unittest.TestCase):
    def test_cp_sat_sectioning_respects_requests_capacity_and_avoids_conflicts(self) -> None:
        instance, schedule = make_sectioning_instance()

        result = solve_sectioning(instance, schedule, time_limit_s=5)

        self.assertEqual(result.status, "optimal")
        self.assertTrue(result.successful)
        self.assertTrue(result.validation.valid_complete)
        self.assertEqual(result.validation.total_requests, 3)
        self.assertEqual(result.validation.assigned_requests, 3)
        self.assertEqual(result.validation.student_conflict_count, 0)
        self.assertEqual(result.objective_score, 0)
        self.assertEqual(
            result.validation.enrollments.get(101, 0)
            + result.validation.enrollments.get(102, 0),
            2,
        )
        self.assertGreaterEqual(result.validation.enrollments.get(102, 0), 1)

    def test_conflict_objective_counts_student_class_pairs_and_weight(self) -> None:
        instance, schedule = make_sectioning_instance()
        instance.students[1].assigned_class_ids = [101]

        result = solve_sectioning(instance, schedule, time_limit_s=5)

        self.assertEqual(result.status, "optimal")
        self.assertTrue(result.successful)
        self.assertEqual(result.validation.student_conflict_count, 1)
        self.assertEqual(result.validation.weighted_student_conflict_cost, 8)
        self.assertEqual(result.objective_score, 8)
        self.assertEqual(
            result.validation.student_conflict_pairs,
            [{"student_id": 1, "class_a": 101, "class_b": 201}],
        )

    def test_validator_rejects_two_sections_from_same_subpart(self) -> None:
        instance, schedule = make_sectioning_instance()
        sectioning = StudentSectioning(
            assignments={
                1: {1: (101, 102), 2: (201,)},
                2: {1: (102,)},
            }
        )

        report = validate_sectioning_independently(
            instance, schedule, sectioning
        )

        self.assertFalse(report.valid_complete)
        self.assertTrue(
            any(
                "exactly one class" in item["reason"]
                for item in report.invalid_selections
            )
        )

    def test_parented_subpart_selection_matches_selected_parent(self) -> None:
        instance, schedule = make_sectioning_instance()
        instance.configs[11].subpart_ids.append(112)
        instance.subparts[112] = Subpart(
            id=112,
            config_id=11,
            class_ids=[103, 104],
        )
        for class_id, parent_id, start in (
            (103, 101, 14),
            (104, 102, 24),
        ):
            cls = Class(
                id=class_id,
                course_id=1,
                config_id=11,
                subpart_id=112,
                limit=2,
                parent_id=parent_id,
                room_required=True,
                placements=[Placement(2, "1", start, 2, "1", 0, 0)],
            )
            instance.classes[class_id] = cls
            schedule.assign(class_id, cls.placements[0])

        result = solve_sectioning(instance, schedule, time_limit_s=5)

        self.assertTrue(result.successful)
        for student_assignments in result.sectioning.assignments.values():
            selected = set(student_assignments[1])
            selected_child = selected & {103, 104}
            self.assertEqual(len(selected_child), 1)
            child_id = next(iter(selected_child))
            expected_parent = 101 if child_id == 103 else 102
            self.assertIn(expected_parent, selected)

        invalid = StudentSectioning(
            assignments={
                1: {1: (101, 104), 2: (201,)},
                2: {1: (102, 104)},
            }
        )
        report = validate_sectioning_independently(
            instance, schedule, invalid
        )
        self.assertFalse(report.valid_complete)
        self.assertTrue(
            any(
                item.get("reason") == "selected class parent is not selected"
                for item in report.invalid_selections
            )
        )

    def test_validator_checks_class_and_room_capacities(self) -> None:
        instance, schedule = make_sectioning_instance(
            room_capacity=1,
            section_limit=1,
        )
        sectioning = StudentSectioning(
            assignments={
                1: {1: (101,), 2: (201,)},
                2: {1: (101,)},
            }
        )

        report = validate_sectioning_independently(
            instance, schedule, sectioning
        )

        self.assertFalse(report.valid_complete)
        self.assertEqual(report.enrollments[101], 2)
        self.assertEqual(
            {
                violation["capacity_type"]
                for violation in report.capacity_violations
            },
            {"class_limit", "room_capacity"},
        )

    def test_solver_proves_infeasible_capacity_instead_of_overfilling(self) -> None:
        instance, schedule = make_sectioning_instance(section_limit=1)
        instance.subparts[111].class_ids = [101]

        result = solve_sectioning(instance, schedule, time_limit_s=5)

        self.assertEqual(result.status, "infeasible")
        self.assertEqual(result.termination_reason, "sectioning_infeasible_proven")
        self.assertFalse(result.successful)

    def test_missing_and_duplicate_requests_are_explicitly_rejected(self) -> None:
        instance, schedule = make_sectioning_instance()
        instance.students[1].course_ids = [999]

        missing = solve_sectioning(instance, schedule, time_limit_s=5)

        self.assertEqual(missing.status, "unsupported")
        self.assertEqual(
            missing.termination_reason,
            "request_without_configuration",
        )

        instance.students[1].course_ids = [1, 1]
        duplicate = solve_sectioning(instance, schedule, time_limit_s=5)
        self.assertEqual(duplicate.status, "unsupported")
        self.assertEqual(
            duplicate.termination_reason,
            "ambiguous_duplicate_request",
        )

    def test_solver_rejects_unknown_class_capacity(self) -> None:
        instance, schedule = make_sectioning_instance()
        instance.classes[101].limit = None

        result = solve_sectioning(instance, schedule, time_limit_s=5)

        self.assertEqual(result.status, "unsupported")
        self.assertEqual(
            result.termination_reason,
            "class_capacity_missing",
        )

    def test_validator_reports_missing_request_section(self) -> None:
        instance, schedule = make_sectioning_instance()
        report = validate_sectioning_independently(
            instance,
            schedule,
            StudentSectioning(assignments={1: {1: (101,)}}),
        )

        self.assertFalse(report.complete)
        self.assertFalse(report.valid_complete)
        self.assertEqual(
            report.missing_requests,
            [
                {"student_id": 1, "course_id": 2},
                {"student_id": 2, "course_id": 1},
            ],
        )

    def test_parser_retains_supplied_solution_section_memberships(self) -> None:
        xml = """<?xml version="1.0"?>
<problem name="sectioning-parser" nrDays="1" slotsPerDay="24" nrWeeks="1">
  <optimization time="0" room="0" distribution="0" student="8"/>
  <rooms><room id="1"/></rooms>
  <courses>
    <course id="1"><config id="11"><subpart id="111">
      <class id="101"><time days="1" start="1" length="1" weeks="1"/><room id="1"/></class>
    </subpart></config></course>
  </courses>
  <distributions/>
  <students><student id="1"><course id="1"/></student></students>
  <solution runtime="0" technique="test" author="test" institution="test" country="test">
    <class id="101" days="1" start="1" weeks="1" room="1"><student id="1"/></class>
  </solution>
</problem>
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "instance.xml"
            path.write_text(xml, encoding="utf-8")
            instance = parse_instance(path)

        validate_instance(instance)
        self.assertIsNone(instance.rooms[1].capacity)
        self.assertIsNone(instance.classes[101].limit)
        self.assertEqual(instance.students[1].assigned_class_ids, [101])
        parsed_sectioning = sectioning_from_instance(instance)
        self.assertEqual(
            parsed_sectioning.assignments,
            {1: {1: (101,)}},
        )

    def test_pu_d5_supplies_requests_and_capacity_bounds_not_preassignments(self) -> None:
        instance_path = (
            Path(__file__).resolve().parents[1]
            / "data"
            / "pu-d5-spr17.xml"
        )
        instance = parse_instance(instance_path)
        validate_instance(instance)

        self.assertEqual(len(instance.students), 13_497)
        self.assertEqual(
            sum(len(student.course_ids) for student in instance.students.values()),
            19_614,
        )
        self.assertEqual(
            sum(
                len(student.assigned_class_ids)
                for student in instance.students.values()
            ),
            0,
        )
        self.assertTrue(all(cls.limit is not None for cls in instance.classes.values()))
        self.assertTrue(all(room.capacity is not None for room in instance.rooms.values()))

    def test_solver_rejects_unknown_room_capacity(self) -> None:
        instance, schedule = make_sectioning_instance()
        instance.rooms[1].capacity = None

        result = solve_sectioning(instance, schedule, time_limit_s=5)

        self.assertEqual(result.status, "unsupported")
        self.assertEqual(
            result.termination_reason,
            "room_capacity_missing",
        )

    def test_job_snapshot_round_trips_student_request_and_section_data(self) -> None:
        instance, _ = make_sectioning_instance()
        instance.students[1].assigned_class_ids = [101]

        restored = _deserialize_instance(_serialize_instance(instance))

        self.assertEqual(restored.students[1].course_ids, [1, 2])
        self.assertEqual(restored.students[1].assigned_class_ids, [101])
        self.assertEqual(restored.courses[1].config_ids, [11])
        self.assertEqual(restored.configs[11].subpart_ids, [111])
        self.assertEqual(restored.subparts[111].class_ids, [101, 102])


if __name__ == "__main__":
    unittest.main()
