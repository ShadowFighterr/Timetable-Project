from __future__ import annotations

from dataclasses import dataclass

from parser import (
    Instance,
    Class,
    Placement,
)


@dataclass
class Assignment:
    class_id: int
    placement: Placement


class Schedule:

    def __init__(self, instance: Instance):

        self.instance = instance

        # class_id -> Placement
        self.assignments: dict[int, Placement] = {}

    # ========================================================
    # Assignment operations
    # ========================================================

    def assign(
        self,
        class_id: int,
        placement: Placement,
    ) -> None:

        cls = self.instance.classes[class_id]

        if placement not in cls.placements:
            raise ValueError(
                f"Placement is not valid for class {class_id}"
            )

        self.assignments[class_id] = placement

    def unassign(self, class_id: int) -> None:

        self.assignments.pop(class_id, None)

    def is_assigned(self, class_id: int) -> bool:

        return class_id in self.assignments

    def get_placement(
        self,
        class_id: int,
    ) -> Placement | None:

        return self.assignments.get(class_id)

    def get_class(
        self,
        class_id: int,
    ) -> Class:

        return self.instance.classes[class_id]

    # ========================================================
    # Schedule statistics
    # ========================================================

    @property
    def assigned_count(self) -> int:

        return len(self.assignments)

    @property
    def total_classes(self) -> int:

        return len(self.instance.classes)

    @property
    def is_complete(self) -> bool:

        return (
            self.assigned_count
            == self.total_classes
        )

    # ========================================================
    # Domain helpers
    # ========================================================

    def get_domain(
        self,
        class_id: int,
    ) -> list[Placement]:

        return self.instance.classes[class_id].placements

    def domain_size(self, class_id: int) -> int:

        return len(
            self.instance.classes[class_id].placements
        )

    # ========================================================
    # Hierarchy helpers
    # ========================================================

    def get_course(self, course_id: int):

        return self.instance.courses[course_id]

    def get_config(self, config_id: int):

        return self.instance.configs[config_id]

    def get_subpart(self, subpart_id: int):

        return self.instance.subparts[subpart_id]

    def get_class_subpart(self, class_id: int):

        cls = self.instance.classes[class_id]

        return self.instance.subparts[
            cls.subpart_id
        ]

    def get_class_config(self, class_id: int):

        cls = self.instance.classes[class_id]

        return self.instance.configs[
            cls.config_id
        ]

    def get_class_course(self, class_id: int):

        cls = self.instance.classes[class_id]

        return self.instance.courses[
            cls.course_id
        ]

    def get_sibling_classes(
        self,
        class_id: int,
    ) -> list[Class]:

        cls = self.instance.classes[class_id]

        subpart = self.instance.subparts[
            cls.subpart_id
        ]

        return [
            self.instance.classes[sibling_id]
            for sibling_id in subpart.class_ids
            if sibling_id != class_id
        ]

    def get_parent_class(
        self,
        class_id: int,
    ) -> Class | None:

        cls = self.instance.classes[class_id]

        if cls.parent_id is None:
            return None

        return self.instance.classes[
            cls.parent_id
        ]

    # ========================================================
    # Copy
    # ========================================================

    def copy(self) -> "Schedule":

        new_schedule = Schedule(self.instance)

        new_schedule.assignments = (
            self.assignments.copy()
        )

        return new_schedule

    # ========================================================
    # Debugging
    # ========================================================

    def describe_class(
        self,
        class_id: int,
    ) -> str:

        cls = self.instance.classes[class_id]

        placement = self.assignments.get(
            class_id
        )

        if placement is None:

            room = "UNASSIGNED"
            days = "-"
            start = "-"
            length = "-"
            weeks = "-"

        else:

            room = (
                "NO ROOM"
                if placement.room_id is None
                else str(placement.room_id)
            )

            days = placement.days
            start = placement.start
            length = placement.length
            weeks = placement.weeks

        return (
            f"Class {class_id}: "
            f"course={cls.course_id}, "
            f"config={cls.config_id}, "
            f"subpart={cls.subpart_id}, "
            f"parent={cls.parent_id}, "
            f"room={room}, "
            f"days={days}, "
            f"start={start}, "
            f"length={length}, "
            f"weeks={weeks}"
        )

    def __repr__(self) -> str:

        return (
            f"Schedule("
            f"{self.assigned_count}/"
            f"{self.total_classes} "
            f"classes assigned)"
        )


# ============================================================
# FACTORY
# ============================================================

def create_empty_schedule(
    instance: Instance,
) -> Schedule:

    return Schedule(instance)


def create_first_placement_schedule(
    instance: Instance,
) -> Schedule:

    schedule = Schedule(instance)

    for class_id, cls in instance.classes.items():

        if not cls.placements:
            continue

        schedule.assign(
            class_id,
            cls.placements[0],
        )

    return schedule


# ============================================================
# HIERARCHY SUMMARY
# ============================================================

def print_hierarchy_summary(
    instance: Instance,
    course_limit: int = 10,
) -> None:

    print()
    print("=" * 60)
    print("COURSE HIERARCHY")
    print("=" * 60)

    for course_id in sorted(instance.courses)[:course_limit]:

        course = instance.courses[course_id]

        print()
        print(
            f"Course {course.id}: "
            f"{len(course.config_ids)} configuration(s)"
        )

        for config_id in course.config_ids:

            config = instance.configs[config_id]

            print(
                f"  Config {config.id}: "
                f"{len(config.subpart_ids)} subpart(s)"
            )

            for subpart_id in config.subpart_ids:

                subpart = instance.subparts[subpart_id]

                print(
                    f"    Subpart {subpart.id}: "
                    f"{len(subpart.class_ids)} class(es)"
                )

                for class_id in subpart.class_ids:

                    cls = instance.classes[class_id]

                    parent = (
                        "-"
                        if cls.parent_id is None
                        else str(cls.parent_id)
                    )

                    print(
                        f"      Class {cls.id}: "
                        f"parent={parent}, "
                        f"placements="
                        f"{len(cls.placements)}"
                    )


# ========================================================
# TEST
# ========================================================

if __name__ == "__main__":

    from parser import parse_instance, validate_instance

    instance = parse_instance(
        "data/pu-d5-spr17.xml"
    )

    validate_instance(instance)

    print(
        f"Loaded instance: {instance.name}"
    )

    print(
        f"Classes: {len(instance.classes)}"
    )

    print(
        f"Courses: {len(instance.courses)}"
    )

    print(
        f"Configurations: "
        f"{len(instance.configs)}"
    )

    print(
        f"Subparts: {len(instance.subparts)}"
    )

    schedule = create_empty_schedule(
        instance
    )

    print(
        f"Empty schedule: {schedule}"
    )

    print_hierarchy_summary(
        instance,
        course_limit=5,
    )