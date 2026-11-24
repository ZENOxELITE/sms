import unittest

from scripts.seed_university_timetable import (
    CURRICULUM,
    SLOTS,
    TERM_WEEKS,
    assign_teachers,
    build_weekly_timetable,
    planned_courses,
    session_rows,
)


def _courses_with_ids():
    courses = planned_courses()
    for index, course in enumerate(courses, start=1):
        course["id"] = index
    return courses


class UniversityTimetableTests(unittest.TestCase):
    def test_every_semester_gets_four_new_subjects_with_unique_codes(self):
        courses = planned_courses()
        self.assertEqual(len(courses), sum(len(s) * 4 for s in CURRICULUM.values()))
        self.assertEqual(len({course["code"] for course in courses}), len(courses))

    def test_unstaffed_courses_get_balanced_department_teachers(self):
        courses = _courses_with_ids()
        teachers = {
            "Software Engineering": ["se-1", "se-2"],
            "Software Engineering Technology": ["set-1", "set-2"],
            "Cyber Security": ["cys-1", "cys-2"],
        }
        staffed, new_rows = assign_teachers(courses, [{"course_id": 1, "profile_id": "x"}], teachers)
        self.assertEqual(staffed[1], ["x"])
        self.assertEqual(len(new_rows), len(courses) - 1)
        for row in new_rows:
            course = next(c for c in courses if c["id"] == row["course_id"])
            self.assertIn(row["profile_id"], teachers[course["department"]])
        loads = {}
        for row in new_rows:
            loads[row["profile_id"]] = loads.get(row["profile_id"], 0) + 1
        self.assertLessEqual(max(loads.values()) - min(loads.values()), 1)

    def test_timetable_has_no_cohort_or_teacher_clashes(self):
        courses = _courses_with_ids()
        teachers = {"Software Engineering": ["t1", "t2", "t3", "t4"],
                    "Software Engineering Technology": ["t5", "t6", "t7", "t8"],
                    "Cyber Security": ["t9", "t10", "t11", "t12"]}
        staffed, _rows = assign_teachers(courses, [], teachers)
        timetable = build_weekly_timetable(courses, staffed)
        cohort_slots, teacher_slots = set(), set()
        for course in courses:
            slots = timetable[course["id"]]
            self.assertEqual(len(slots), 2)
            self.assertNotEqual(slots[0][0], slots[1][0])
            for slot in slots:
                cohort_key = (course["program"], course["semester"], slot)
                self.assertNotIn(cohort_key, cohort_slots)
                cohort_slots.add(cohort_key)
                for teacher in staffed[course["id"]]:
                    self.assertNotIn((teacher, slot), teacher_slots)
                    teacher_slots.add((teacher, slot))
                self.assertFalse(slot[0] == 4 and SLOTS[slot[1]].hour == 12)

    def test_sessions_cover_each_term_week(self):
        course = dict(planned_courses()[0], id=1)
        rows = session_rows(course, [(0, 0), (2, 0)])
        self.assertEqual(len(rows), TERM_WEEKS * 2)
        self.assertTrue(all(row["ends_at"] > row["starts_at"] for row in rows))
        self.assertTrue(rows[0]["location"].startswith("SE Block"))


if __name__ == "__main__":
    unittest.main()
