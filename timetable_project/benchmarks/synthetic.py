"""Small deterministic instances used for adapter and validator tests."""

from __future__ import annotations

from parser import Class, Distribution, Instance, Placement, Room


def make_synthetic_instance(*, impossible: bool = False) -> Instance:
    second_starts = [10] if impossible else [10, 12]
    placements = {
        1: [
            Placement(
                room_id=1,
                days="1",
                start=10,
                length=2,
                weeks="1",
                time_penalty=0,
                room_penalty=0,
            )
        ],
        2: [
            Placement(
                room_id=1,
                days="1",
                start=start,
                length=2,
                weeks="1",
                time_penalty=0,
                room_penalty=0,
            )
            for start in second_starts
        ],
    }
    classes = {
        class_id: Class(
            id=class_id,
            course_id=class_id,
            config_id=class_id,
            subpart_id=class_id,
            limit=0,
            parent_id=None,
            room_required=True,
            placements=class_placements,
            expected_enrollment=20,
        )
        for class_id, class_placements in placements.items()
    }
    return Instance(
        name="synthetic-room-conflict" if impossible else "synthetic-feasible",
        nr_days=1,
        slots_per_day=24,
        nr_weeks=1,
        rooms={1: Room(id=1, capacity=40)},
        courses={},
        configs={},
        subparts={},
        classes=classes,
        distributions=[],
        students={},
        time_weight=1,
        room_weight=1,
        distribution_weight=1,
        student_weight=0,
    )


def make_synthetic_objective_instance() -> Instance:
    instance = make_synthetic_instance()
    instance.name = "synthetic-positive-objective"
    instance.distribution_weight = 3
    for cls in instance.classes.values():
        cls.room_required = False
        cls.placements = [
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
    instance.distributions = [
        Distribution(
            type="NotOverlap",
            required=False,
            penalty=5,
            class_ids=[1, 2],
        )
    ]
    return instance
