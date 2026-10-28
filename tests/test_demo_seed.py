import csv
import unittest
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

from scripts.seed_demo_accounts import (
    ACCOUNTS_PER_COHORT,
    DEPARTMENT,
    PROGRAM_DEPARTMENTS,
    PROGRAMS,
    SEMESTERS,
    TEACHER_COUNT,
    build_demo_records,
    build_presentation_academic_records,
    expected_demo_names,
    refresh_demo_names,
    seed_presentation_academic_records,
    seed_demo_accounts,
)


class DemoSeedTests(unittest.TestCase):
    def test_generates_25_teachers_and_40_students_in_each_cohort(self):
        records = build_demo_records()
        teachers = [record for record in records if record["role"] == "teacher"]
        students = [record for record in records if record["role"] == "student"]
        cohort_counts = Counter(
            (record["program"], record["semester"]) for record in students
        )

        self.assertEqual(len(teachers), TEACHER_COUNT)
        self.assertTrue(all(record["department"] == DEPARTMENT for record in teachers))
        self.assertEqual(
            len(students),
            len(PROGRAMS) * len(SEMESTERS) * ACCOUNTS_PER_COHORT,
        )
        self.assertEqual(len(cohort_counts), 24)
        self.assertEqual(set(cohort_counts.values()), {ACCOUNTS_PER_COHORT})
        self.assertTrue(all(
            record["department"] == PROGRAM_DEPARTMENTS.get(record["program"], DEPARTMENT)
            for record in students
        ))
        self.assertEqual(len({record["email"] for record in records}), len(records))
        self.assertEqual(len({record["username"] for record in records}), len(records))
        self.assertTrue(all(record["email"].endswith("@example.invalid") for record in records))
        self.assertEqual(len({record["full_name"] for record in records}), len(records))
        self.assertTrue(all(not record["full_name"].startswith("Demo ") for record in records))

    def test_refresh_updates_only_known_profile_names_and_preserves_passwords(self):
        names = expected_demo_names()
        existing_profiles = [
            {"id": f"user-{index}", "username": username}
            for index, username in enumerate(names)
        ]
        client = MagicMock()
        client.list_demo_profiles.return_value = existing_profiles

        with TemporaryDirectory() as directory:
            credentials_path = Path(directory) / "demo_credentials.csv"
            records = build_demo_records()
            with credentials_path.open("w", encoding="utf-8", newline="") as output:
                writer = csv.DictWriter(output, fieldnames=(
                    "role", "full_name", "department", "program", "semester",
                    "student_number", "username", "email", "password",
                ))
                writer.writeheader()
                writer.writerows(records)

            updated_profiles, updated_credentials = refresh_demo_names(
                client, credentials_path
            )

            self.assertEqual(updated_profiles, 985)
            self.assertEqual(updated_credentials, 985)
            client.update_profile_names.assert_called_once()
            updated_rows = client.update_profile_names.call_args.args[0]
            self.assertTrue(all(
                row["full_name"] == names[existing_profiles[index]["username"]]
                for index, row in enumerate(updated_rows)
            ))
            with credentials_path.open("r", encoding="utf-8", newline="") as source:
                credential_rows = list(csv.DictReader(source))

        self.assertEqual(len(credential_rows), 985)
        self.assertEqual(
            {row["username"]: row["password"] for row in credential_rows},
            {row["username"]: row["password"] for row in records},
        )
        self.assertTrue(all(
            row["full_name"] == names[row["username"]]
            for row in credential_rows
        ))

    def test_existing_credentials_file_blocks_database_changes(self):
        client = MagicMock()
        path = MagicMock()
        path.exists.return_value = True

        with self.assertRaisesRegex(RuntimeError, "already exists"):
            seed_demo_accounts(client, [], path)

        client.list_auth_users.assert_not_called()

    def test_presentation_courses_assignments_and_rosters_match_each_cohort(self):
        accounts = build_demo_records()
        profiles = [
            {
                "id": f"profile-{index}",
                "username": record["username"],
                "role": record["role"],
                "department": record["department"],
                "program": record.get("program"),
                "semester": record.get("semester"),
            }
            for index, record in enumerate(accounts)
        ]

        courses, assignments, enrollments = build_presentation_academic_records(profiles)

        self.assertEqual(len(courses), 24)
        self.assertEqual(len(assignments), 24)
        self.assertEqual(len(enrollments), 960)
        self.assertTrue(all(course["is_demo"] and not course["is_sample"] for course in courses))
        self.assertEqual(
            {
                course["department"] for course in courses
                if course["program"] == "BS Software Engineering"
            },
            {"Software Engineering"},
        )
        self.assertEqual(
            {row["course_code"] for row in assignments},
            {course["code"] for course in courses},
        )
        self.assertEqual(
            {row["term"] for row in enrollments},
            {"Fall 2026 (synthetic presentation)"},
        )
        for course in courses:
            matching_enrollments = [
                row for row in enrollments if row["course_code"] == course["code"]
            ]
            self.assertEqual(len(matching_enrollments), 40)

    def test_presentation_data_refuses_incomplete_cohorts(self):
        with self.assertRaisesRegex(RuntimeError, "Expected 25 synthetic"):
            build_presentation_academic_records([])

    def test_academic_seed_upserts_courses_staff_and_enrollments(self):
        records = build_demo_records()
        profiles = [
            {
                "id": f"profile-{index}",
                "username": record["username"],
                "role": record["role"],
                "department": record["department"],
                "program": record.get("program"),
                "semester": record.get("semester"),
            }
            for index, record in enumerate(records)
        ]
        client = MagicMock()
        client.request_json.return_value = [
            {"name": DEPARTMENT},
            {"name": "Software Engineering"},
        ]
        client.list_demo_profiles.return_value = profiles

        def upsert(table, rows, _conflict_columns):
            if table == "courses":
                return [
                    {"id": index + 1, "code": row["code"]}
                    for index, row in enumerate(rows)
                ]
            return rows

        client.upsert_records.side_effect = upsert

        self.assertEqual(
            seed_presentation_academic_records(client),
            (24, 24, 960),
        )
        client.mark_demo_profiles.assert_called_once_with()
        client.update_demo_student_departments.assert_called_once_with()
        self.assertEqual(
            [call.args[0] for call in client.upsert_records.call_args_list],
            ["courses", "course_staff", "enrollments"],
        )

    def test_seed_inserts_uniform_profile_rows_and_writes_credentials(self):
        records = build_demo_records()
        client = MagicMock()
        client.list_auth_users.return_value = []
        client.request_json.return_value = [
            {"name": DEPARTMENT},
            {"name": "Software Engineering"},
        ]
        client.create_auth_user.side_effect = [
            {"id": f"user-{index}"} for index in range(len(records))
        ]

        with TemporaryDirectory() as directory:
            credentials_path = Path(directory) / "demo_credentials.csv"
            created_count = seed_demo_accounts(client, records, credentials_path)

            self.assertEqual(created_count, 985)
            self.assertTrue(credentials_path.is_file())

        all_profiles = [
            profile
            for call in client.insert_profiles.call_args_list
            for profile in call.args[0]
        ]
        expected_keys = {
            "id", "full_name", "username", "role", "department",
            "student_number", "program", "semester",
        }
        self.assertEqual(len(all_profiles), 985)
        self.assertTrue(all(set(profile) == expected_keys for profile in all_profiles))
        self.assertTrue(all(
            profile["student_number"] is None
            and profile["program"] is None
            and profile["semester"] is None
            for profile in all_profiles[:TEACHER_COUNT]
        ))


if __name__ == "__main__":
    unittest.main()
