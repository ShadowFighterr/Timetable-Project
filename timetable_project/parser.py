from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import xml.etree.ElementTree as ET


# ============================================================
# DATA CLASSES
# ============================================================

@dataclass
class Room:
    id: int
    capacity: int | None
    unavailable: list[tuple[str, int, int, str]] = field(default_factory=list)
    travel: dict[int, int] = field(default_factory=dict)


@dataclass
class Placement:
    """
    One complete placement option for a class.

    A placement consists of:
      - room
      - time pattern
      - penalties
    """

    room_id: int | None

    days: str
    start: int
    length: int
    weeks: str

    time_penalty: int
    room_penalty: int

    @property
    def total_penalty(self) -> int:
        return self.time_penalty + self.room_penalty


@dataclass
class Class:
    id: int
    course_id: int
    config_id: int
    subpart_id: int

    limit: int | None
    parent_id: int | None
    room_required: bool

    placements: list[Placement] = field(default_factory=list)
    expected_enrollment: int | None = None
    instructor_ids: list[int] = field(default_factory=list)
    student_group_ids: list[int] = field(default_factory=list)


@dataclass
class Subpart:
    id: int
    config_id: int
    class_ids: list[int] = field(default_factory=list)


@dataclass
class Config:
    id: int
    course_id: int
    subpart_ids: list[int] = field(default_factory=list)


@dataclass
class Course:
    id: int
    config_ids: list[int] = field(default_factory=list)


@dataclass
class Distribution:
    type: str
    required: bool
    penalty: int
    class_ids: list[int]


@dataclass
class Student:
    id: int
    course_ids: list[int]
    assigned_class_ids: list[int] = field(default_factory=list)


@dataclass
class Instance:
    name: str

    nr_days: int
    slots_per_day: int
    nr_weeks: int

    rooms: dict[int, Room]

    courses: dict[int, Course]
    configs: dict[int, Config]
    subparts: dict[int, Subpart]
    classes: dict[int, Class]

    distributions: list[Distribution]
    students: dict[int, Student]

    time_weight: int
    room_weight: int
    distribution_weight: int
    student_weight: int

    # --------------------------------------------------------
    # Hierarchy helpers
    # --------------------------------------------------------

    def get_course_classes(self, course_id: int) -> list[Class]:
        """Return all classes belonging to a course."""
        return [
            cls
            for cls in self.classes.values()
            if cls.course_id == course_id
        ]

    def get_config_classes(self, config_id: int) -> list[Class]:
        """Return all classes belonging to a configuration."""
        return [
            cls
            for cls in self.classes.values()
            if cls.config_id == config_id
        ]

    def get_subpart_classes(self, subpart_id: int) -> list[Class]:
        """Return all alternative classes in a subpart."""
        subpart = self.subparts[subpart_id]

        return [
            self.classes[class_id]
            for class_id in subpart.class_ids
        ]

    def get_course_configs(self, course_id: int) -> list[Config]:
        course = self.courses[course_id]

        return [
            self.configs[config_id]
            for config_id in course.config_ids
        ]

    def get_config_subparts(self, config_id: int) -> list[Subpart]:
        config = self.configs[config_id]

        return [
            self.subparts[subpart_id]
            for subpart_id in config.subpart_ids
        ]

    def get_parent_chain(self, class_id: int) -> list[int]:
        """
        Return the parent chain of a class.

        Example:

            Lab3 -> Rec7 -> Lec4

        returns:

            [Rec7, Lec4]
        """

        result = []

        current = self.classes[class_id]

        while current.parent_id is not None:
            result.append(current.parent_id)
            current = self.classes[current.parent_id]

        return result


# ============================================================
# TIME UTILITIES
# ============================================================

def bit_overlap(a: str, b: str) -> bool:
    """
    True if two binary strings share at least one active position.
    """

    return any(x == "1" and y == "1" for x, y in zip(a, b))


def time_intervals_overlap(
    start1: int,
    length1: int,
    start2: int,
    length2: int,
) -> bool:
    end1 = start1 + length1
    end2 = start2 + length2

    return start1 < end2 and start2 < end1


def periods_overlap(
    days1: str,
    start1: int,
    length1: int,
    weeks1: str,
    days2: str,
    start2: int,
    length2: int,
    weeks2: str,
) -> bool:

    if not bit_overlap(weeks1, weeks2):
        return False

    if not bit_overlap(days1, days2):
        return False

    return time_intervals_overlap(
        start1,
        length1,
        start2,
        length2,
    )


def placement_overlaps_unavailability(
    placement: Placement,
    unavailable: tuple[str, int, int, str],
) -> bool:

    days, start, length, weeks = unavailable

    return periods_overlap(
        placement.days,
        placement.start,
        placement.length,
        placement.weeks,
        days,
        start,
        length,
        weeks,
    )


# ============================================================
# XML PARSER
# ============================================================

def parse_instance(xml_path: str | Path) -> Instance:

    xml_path = Path(xml_path)

    tree = ET.parse(xml_path)
    root = tree.getroot()

    # --------------------------------------------------------
    # Root
    # --------------------------------------------------------

    name = root.attrib["name"]

    nr_days = int(root.attrib["nrDays"])
    slots_per_day = int(root.attrib["slotsPerDay"])
    nr_weeks = int(root.attrib["nrWeeks"])

    # --------------------------------------------------------
    # Optimization weights
    # --------------------------------------------------------

    optimization = root.find("optimization")

    if optimization is None:
        raise ValueError("Missing <optimization> element")

    time_weight = int(optimization.attrib.get("time", 0))
    room_weight = int(optimization.attrib.get("room", 0))
    distribution_weight = int(
        optimization.attrib.get("distribution", 0)
    )
    student_weight = int(
        optimization.attrib.get("student", 0)
    )

    # --------------------------------------------------------
    # Rooms
    # --------------------------------------------------------

    rooms: dict[int, Room] = {}

    rooms_element = root.find("rooms")

    if rooms_element is not None:

        for room_element in rooms_element.findall("room"):

            room_id = int(room_element.attrib["id"])
            capacity_value = room_element.attrib.get("capacity")
            capacity = (
                None
                if capacity_value is None
                else int(capacity_value)
            )

            unavailable = []

            for unavailable_element in room_element.findall(
                "unavailable"
            ):
                unavailable.append(
                    (
                        unavailable_element.attrib["days"],
                        int(unavailable_element.attrib["start"]),
                        int(unavailable_element.attrib["length"]),
                        unavailable_element.attrib["weeks"],
                    )
                )

            travel = {}

            for travel_element in room_element.findall("travel"):
                destination = int(travel_element.attrib["room"])
                value = int(travel_element.attrib["value"])

                travel[destination] = value

            rooms[room_id] = Room(
                id=room_id,
                capacity=capacity,
                unavailable=unavailable,
                travel=travel,
            )

    # --------------------------------------------------------
    # Courses / Configurations / Subparts / Classes
    # --------------------------------------------------------

    courses: dict[int, Course] = {}
    configs: dict[int, Config] = {}
    subparts: dict[int, Subpart] = {}
    classes: dict[int, Class] = {}

    courses_element = root.find("courses")

    if courses_element is None:
        raise ValueError("Missing <courses> element")

    for course_element in courses_element.findall("course"):

        course_id = int(course_element.attrib["id"])

        course = Course(id=course_id)

        courses[course_id] = course

        for config_element in course_element.findall("config"):

            config_id = int(config_element.attrib["id"])

            config = Config(
                id=config_id,
                course_id=course_id,
            )

            configs[config_id] = config
            course.config_ids.append(config_id)

            for subpart_element in config_element.findall("subpart"):

                subpart_id = int(subpart_element.attrib["id"])

                subpart = Subpart(
                    id=subpart_id,
                    config_id=config_id,
                )

                subparts[subpart_id] = subpart
                config.subpart_ids.append(subpart_id)

                for class_element in subpart_element.findall("class"):

                    class_id = int(class_element.attrib["id"])

                    limit_value = class_element.attrib.get("limit")
                    limit = (
                        None
                        if limit_value is None
                        else int(limit_value)
                    )

                    parent_id = class_element.attrib.get(
                        "parent"
                    )

                    if parent_id is not None:
                        parent_id = int(parent_id)

                    room_required = (
                        class_element.attrib.get(
                            "room",
                            "true",
                        ).lower()
                        != "false"
                    )

                    cls = Class(
                        id=class_id,
                        course_id=course_id,
                        config_id=config_id,
                        subpart_id=subpart_id,
                        limit=limit,
                        parent_id=parent_id,
                        room_required=room_required,
                    )

                    # ------------------------------------------------
                    # Parse time options
                    # ------------------------------------------------

                    times = []

                    for time_element in class_element.findall("time"):

                        times.append(
                            (
                                time_element.attrib["days"],
                                int(time_element.attrib["start"]),
                                int(time_element.attrib["length"]),
                                time_element.attrib["weeks"],
                                int(
                                    time_element.attrib.get(
                                        "penalty",
                                        "0",
                                    )
                                ),
                            )
                        )

                    # ------------------------------------------------
                    # Parse room options
                    # ------------------------------------------------

                    room_options = []

                    if room_required:

                        for room_element in class_element.findall(
                            "room"
                        ):

                            room_options.append(
                                (
                                    int(room_element.attrib["id"]),
                                    int(
                                        room_element.attrib.get(
                                            "penalty",
                                            "0",
                                        )
                                    ),
                                )
                            )

                    else:

                        # A roomless class receives a single
                        # room=None option.
                        room_options = [
                            (None, 0)
                        ]

                    # ------------------------------------------------
                    # Generate complete placements
                    # ------------------------------------------------

                    for (
                        days,
                        start,
                        length,
                        weeks,
                        time_penalty,
                    ) in times:

                        for room_id, room_penalty in room_options:

                            placement = Placement(
                                room_id=room_id,
                                days=days,
                                start=start,
                                length=length,
                                weeks=weeks,
                                time_penalty=time_penalty,
                                room_penalty=room_penalty,
                            )

                            # Check room availability.
                            if room_id is not None:

                                room = rooms[room_id]

                                unavailable = any(
                                    placement_overlaps_unavailability(
                                        placement,
                                        u,
                                    )
                                    for u in room.unavailable
                                )

                                if unavailable:
                                    continue

                            cls.placements.append(placement)

                    classes[class_id] = cls
                    subpart.class_ids.append(class_id)

    # --------------------------------------------------------
    # Distributions
    # --------------------------------------------------------

    distributions: list[Distribution] = []

    distributions_element = root.find("distributions")

    if distributions_element is not None:

        for distribution_element in distributions_element.findall(
            "distribution"
        ):

            distribution_type = distribution_element.attrib["type"]

            required = (
                distribution_element.attrib.get(
                    "required",
                    "false",
                ).lower()
                == "true"
            )

            penalty = int(
                distribution_element.attrib.get(
                    "penalty",
                    "0",
                )
            )

            class_ids = [
                int(class_element.attrib["id"])
                for class_element
                in distribution_element.findall("class")
            ]

            distributions.append(
                Distribution(
                    type=distribution_type,
                    required=required,
                    penalty=penalty,
                    class_ids=class_ids,
                )
            )

    # --------------------------------------------------------
    # Students
    # --------------------------------------------------------

    students: dict[int, Student] = {}

    students_element = root.find("students")

    if students_element is not None:

        for student_element in students_element.findall("student"):

            student_id = int(student_element.attrib["id"])

            course_ids = [
                int(course_element.attrib["id"])
                for course_element
                in student_element.findall("course")
            ]

            students[student_id] = Student(
                id=student_id,
                course_ids=course_ids,
            )

    solution_element = root.find("solution")
    if solution_element is not None:
        for solution_class in solution_element.findall("class"):
            class_id = int(solution_class.attrib["id"])
            if class_id not in classes:
                raise ValueError(
                    f"Solution references unknown class {class_id}"
                )
            for assigned_student in solution_class.findall("student"):
                student_id = int(assigned_student.attrib["id"])
                if student_id not in students:
                    raise ValueError(
                        f"Solution references unknown student {student_id}"
                    )
                students[student_id].assigned_class_ids.append(class_id)

    # --------------------------------------------------------
    # Build instance
    # --------------------------------------------------------

    instance = Instance(
        name=name,
        nr_days=nr_days,
        slots_per_day=slots_per_day,
        nr_weeks=nr_weeks,
        rooms=rooms,
        courses=courses,
        configs=configs,
        subparts=subparts,
        classes=classes,
        distributions=distributions,
        students=students,
        time_weight=time_weight,
        room_weight=room_weight,
        distribution_weight=distribution_weight,
        student_weight=student_weight,
    )

    return instance


# ============================================================
# VALIDATION / SUMMARY
# ============================================================

def validate_instance(instance: Instance) -> None:

    # --------------------------------------------------------
    # Course -> Config
    # --------------------------------------------------------

    for course in instance.courses.values():

        for config_id in course.config_ids:

            assert config_id in instance.configs

            config = instance.configs[config_id]

            assert config.course_id == course.id

    # --------------------------------------------------------
    # Config -> Subpart
    # --------------------------------------------------------

    for config in instance.configs.values():

        for subpart_id in config.subpart_ids:

            assert subpart_id in instance.subparts

            subpart = instance.subparts[subpart_id]

            assert subpart.config_id == config.id

    # --------------------------------------------------------
    # Subpart -> Class
    # --------------------------------------------------------

    for subpart in instance.subparts.values():

        for class_id in subpart.class_ids:

            assert class_id in instance.classes

            cls = instance.classes[class_id]

            assert cls.subpart_id == subpart.id
            assert cls.config_id == subpart.config_id

    # --------------------------------------------------------
    # Parent relationships
    # --------------------------------------------------------

    for cls in instance.classes.values():

        assert cls.limit is None or cls.limit >= 0, (
            f"Class {cls.id} has a negative enrollment limit"
        )

        if cls.parent_id is None:
            continue

        assert cls.parent_id in instance.classes, (
            f"Class {cls.id} references missing "
            f"parent {cls.parent_id}"
        )

        parent = instance.classes[cls.parent_id]

        assert parent.course_id == cls.course_id, (
            f"Class {cls.id} and parent {cls.parent_id} "
            f"belong to different courses"
        )

    # --------------------------------------------------------
    # Student requests and optional supplied sectioning
    # --------------------------------------------------------

    for student in instance.students.values():
        assert len(student.course_ids) == len(set(student.course_ids)), (
            f"Student {student.id} requests a course more than once"
        )
        for course_id in student.course_ids:
            assert course_id in instance.courses, (
                f"Student {student.id} requests unknown course {course_id}"
            )
        assert len(student.assigned_class_ids) == len(
            set(student.assigned_class_ids)
        ), f"Student {student.id} is assigned to a class more than once"
        for class_id in student.assigned_class_ids:
            assert class_id in instance.classes, (
                f"Student {student.id} is assigned to unknown class {class_id}"
            )
            assert instance.classes[class_id].course_id in student.course_ids, (
                f"Student {student.id} is assigned to class {class_id} "
                "without requesting its course"
            )

    # --------------------------------------------------------
    # Placements
    # --------------------------------------------------------

    for room in instance.rooms.values():
        assert room.capacity is None or room.capacity >= 0, (
            f"Room {room.id} has a negative capacity"
        )

    for cls in instance.classes.values():

        assert len(cls.placements) > 0, (
            f"Class {cls.id} has no legal placements"
        )


def print_summary(instance: Instance) -> None:

    total_placements = sum(
        len(cls.placements)
        for cls in instance.classes.values()
    )

    roomless = sum(
        not cls.room_required
        for cls in instance.classes.values()
    )

    fixed = sum(
        len(cls.placements) == 1
        for cls in instance.classes.values()
    )

    print(f"Instance:        {instance.name}")
    print(f"Days:            {instance.nr_days}")
    print(f"Slots per day:   {instance.slots_per_day}")
    print(f"Weeks:           {instance.nr_weeks}")
    print()

    print(f"Rooms:           {len(instance.rooms)}")
    print(f"Courses:         {len(instance.courses)}")
    print(f"Configurations:  {len(instance.configs)}")
    print(f"Subparts:        {len(instance.subparts)}")
    print(f"Classes:         {len(instance.classes)}")
    print()

    print(f"Placements:      {total_placements}")
    print()

    print(f"Distributions:   {len(instance.distributions)}")

    required = sum(
        d.required
        for d in instance.distributions
    )

    soft = len(instance.distributions) - required

    print(f"  Required:      {required}")
    print(f"  Soft:          {soft}")
    print()

    print(f"Students:        {len(instance.students)}")

    enrollments = sum(
        len(student.course_ids)
        for student in instance.students.values()
    )

    print(f"Enrollments:     {enrollments}")
    print()

    print(f"Fixed classes:   {fixed}")
    print(f"Roomless classes:{roomless}")
    print()

    print("Configurations per course:")

    config_distribution = {}

    for course in instance.courses.values():

        count = len(course.config_ids)

        config_distribution[count] = (
            config_distribution.get(count, 0) + 1
        )

    for count in sorted(config_distribution):

        print(
            f"  {count} config(s): "
            f"{config_distribution[count]} course(s)"
        )

    print()

    print("Optimization weights:")
    print(f"  time:           {instance.time_weight}")
    print(f"  room:           {instance.room_weight}")
    print(f"  distribution:   {instance.distribution_weight}")
    print(f"  student:        {instance.student_weight}")


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    xml_path = Path("data") / "pu-d5-spr17.xml"

    instance = parse_instance(xml_path)

    validate_instance(instance)
    print_summary(instance)

    print()
    print("Hierarchy validation: OK")
    print("Placement validation: OK")