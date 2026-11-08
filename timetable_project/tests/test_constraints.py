import unittest

from model import Schedule
from parser import Distribution, Instance, Placement, Room
from constraints import required_distribution_violation


class RequiredNotOverlapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.instance = Instance(
            name="test",
            nr_days=5,
            slots_per_day=288,
            nr_weeks=2,
            rooms={},
            courses={},
            configs={},
            subparts={},
            classes={},
            distributions=[],
            students={},
            time_weight=0,
            room_weight=0,
            distribution_weight=0,
            student_weight=0,
        )
        self.distribution = Distribution(
            type="NotOverlap",
            required=True,
            penalty=0,
            class_ids=[1, 2, 3],
        )
        self.schedule = Schedule(self.instance)

    @staticmethod
    def placement(
        start: int,
        *,
        days: str = "10000",
        weeks: str = "10",
        length: int = 10,
    ) -> Placement:
        return Placement(
            room_id=None,
            days=days,
            start=start,
            length=length,
            weeks=weeks,
            time_penalty=0,
            room_penalty=0,
        )

    def test_partial_assignment_with_overlap_is_violation(self) -> None:
        self.schedule.assignments[1] = self.placement(20)
        self.schedule.assignments[2] = self.placement(25)

        self.assertTrue(
            required_distribution_violation(
                self.instance,
                self.distribution,
                self.schedule,
            )
        )

    def test_partial_assignment_without_overlap_is_not_violation(self) -> None:
        self.schedule.assignments[1] = self.placement(20)
        self.schedule.assignments[2] = self.placement(30)

        self.assertFalse(
            required_distribution_violation(
                self.instance,
                self.distribution,
                self.schedule,
            )
        )

    def test_complete_distribution_with_overlap_is_violation(self) -> None:
        self.schedule.assignments[1] = self.placement(20)
        self.schedule.assignments[2] = self.placement(25)
        self.schedule.assignments[3] = self.placement(
            40,
            days="01000",
        )

        self.assertTrue(
            required_distribution_violation(
                self.instance,
                self.distribution,
                self.schedule,
            )
        )

    def test_complete_distribution_without_overlap_is_not_violation(self) -> None:
        self.schedule.assignments[1] = self.placement(20)
        self.schedule.assignments[2] = self.placement(30)
        self.schedule.assignments[3] = self.placement(
            20,
            days="01000",
        )

        self.assertFalse(
            required_distribution_violation(
                self.instance,
                self.distribution,
                self.schedule,
            )
        )


class RequiredSameAttendeesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.instance = Instance(
            name="test",
            nr_days=5,
            slots_per_day=288,
            nr_weeks=2,
            rooms={
                1: Room(id=1, capacity=20, travel={2: 5}),
                2: Room(id=2, capacity=20, travel={1: 8}),
            },
            courses={},
            configs={},
            subparts={},
            classes={},
            distributions=[],
            students={},
            time_weight=0,
            room_weight=0,
            distribution_weight=0,
            student_weight=0,
        )
        self.distribution = Distribution(
            type="SameAttendees",
            required=True,
            penalty=0,
            class_ids=[1, 2, 3],
        )
        self.schedule = Schedule(self.instance)

    @staticmethod
    def placement(
        start: int,
        *,
        room_id: int | None = 1,
        days: str = "10000",
        weeks: str = "10",
        length: int = 10,
    ) -> Placement:
        return Placement(
            room_id=room_id,
            days=days,
            start=start,
            length=length,
            weeks=weeks,
            time_penalty=0,
            room_penalty=0,
        )

    def _violates(self) -> bool:
        return required_distribution_violation(
            self.instance,
            self.distribution,
            self.schedule,
        )

    def test_partial_assignment_with_overlap_is_violation(self) -> None:
        self.schedule.assignments[1] = self.placement(20)
        self.schedule.assignments[2] = self.placement(25)

        self.assertTrue(self._violates())

    def test_partial_assignment_with_insufficient_travel_is_violation(self) -> None:
        self.schedule.assignments[1] = self.placement(
            20,
            room_id=1,
        )
        self.schedule.assignments[2] = self.placement(
            28,
            room_id=2,
        )

        self.assertTrue(self._violates())

    def test_partial_assignment_without_violation_is_not_violation(self) -> None:
        self.schedule.assignments[1] = self.placement(
            20,
            room_id=1,
        )
        self.schedule.assignments[2] = self.placement(
            35,
            room_id=2,
        )

        self.assertFalse(self._violates())

    def test_partial_assignment_accepts_exact_directional_travel_boundary(self) -> None:
        self.schedule.assignments[1] = self.placement(
            20,
            room_id=1,
        )
        self.schedule.assignments[2] = self.placement(
            35,
            room_id=2,
        )

        self.assertFalse(self._violates())

    def test_partial_assignment_without_common_day_is_not_violation(self) -> None:
        self.schedule.assignments[1] = self.placement(20)
        self.schedule.assignments[2] = self.placement(
            20,
            days="01000",
        )

        self.assertFalse(self._violates())

    def test_partial_assignment_without_common_week_is_not_violation(self) -> None:
        self.schedule.assignments[1] = self.placement(20, weeks="10")
        self.schedule.assignments[2] = self.placement(20, weeks="01")

        self.assertFalse(self._violates())

    def test_complete_distribution_with_violation_is_violation(self) -> None:
        self.schedule.assignments[1] = self.placement(20)
        self.schedule.assignments[2] = self.placement(25)
        self.schedule.assignments[3] = self.placement(
            50,
            days="01000",
        )

        self.assertTrue(self._violates())

    def test_complete_distribution_without_violation_is_not_violation(self) -> None:
        self.schedule.assignments[1] = self.placement(
            20,
            room_id=1,
        )
        self.schedule.assignments[2] = self.placement(
            35,
            room_id=2,
        )
        self.schedule.assignments[3] = self.placement(
            20,
            days="01000",
        )

        self.assertFalse(self._violates())


class RequiredPairwisePartialViolationTests(unittest.TestCase):
    def test_partial_different_time_violation_is_rejected(self) -> None:
        instance = Instance(
            name="test",
            nr_days=5,
            slots_per_day=288,
            nr_weeks=2,
            rooms={},
            courses={},
            configs={},
            subparts={},
            classes={},
            distributions=[],
            students={},
            time_weight=0,
            room_weight=0,
            distribution_weight=0,
            student_weight=0,
        )
        schedule = Schedule(instance)
        schedule.assignments[1] = Placement(
            room_id=None,
            days="10000",
            start=20,
            length=10,
            weeks="10",
            time_penalty=0,
            room_penalty=0,
        )
        schedule.assignments[2] = Placement(
            room_id=None,
            days="10000",
            start=25,
            length=10,
            weeks="10",
            time_penalty=0,
            room_penalty=0,
        )
        distribution = Distribution(
            type="DifferentTime",
            required=True,
            penalty=0,
            class_ids=[1, 2, 3],
        )

        self.assertTrue(
            required_distribution_violation(
                instance,
                distribution,
                schedule,
            )
        )

    def test_partial_different_room_violation_is_rejected(self) -> None:
        instance = Instance(
            name="test",
            nr_days=5,
            slots_per_day=288,
            nr_weeks=2,
            rooms={},
            courses={},
            configs={},
            subparts={},
            classes={},
            distributions=[],
            students={},
            time_weight=0,
            room_weight=0,
            distribution_weight=0,
            student_weight=0,
        )
        schedule = Schedule(instance)
        schedule.assignments[1] = Placement(
            room_id=1,
            days="10000",
            start=20,
            length=10,
            weeks="10",
            time_penalty=0,
            room_penalty=0,
        )
        schedule.assignments[2] = Placement(
            room_id=1,
            days="10000",
            start=30,
            length=10,
            weeks="10",
            time_penalty=0,
            room_penalty=0,
        )
        distribution = Distribution(
            type="DifferentRoom",
            required=True,
            penalty=0,
            class_ids=[1, 2, 3],
        )

        self.assertTrue(
            required_distribution_violation(
                instance,
                distribution,
                schedule,
            )
        )


if __name__ == "__main__":
    unittest.main()
