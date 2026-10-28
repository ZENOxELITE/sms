import argparse
import csv
import json
import os
import secrets
import sys
import tempfile
import time
from getpass import getpass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from dotenv import load_dotenv


DEPARTMENT = "Computer Science"
PROGRAM_DEPARTMENTS = {
    "BS Software Engineering": "Software Engineering",
}
PROGRAMS = (
    ("BS Cyber Security Technology", "cys"),
    ("BS Software Engineering", "se"),
    ("BS Software Engineering Technology", "set"),
)
SEMESTERS = range(1, 9)
ACCOUNTS_PER_COHORT = 40
TEACHER_COUNT = 25
OUTPUT_FILE = Path(".demo-data") / "demo_credentials.csv"
PROFILE_BATCH_SIZE = 100
DEMO_TERM = "Fall 2026 (synthetic presentation)"
FIRST_NAMES = (
    "Aariz", "Ayesha", "Daniyal", "Fatima", "Hamza", "Hania", "Hassan",
    "Hiba", "Ibrahim", "Iqra", "Javeria", "Kashif", "Laiba", "Mahad",
    "Mahnoor", "Maryam", "Muneeb", "Nida", "Rayan", "Rida", "Saad",
    "Sana", "Shayan", "Sofia", "Talha", "Tania", "Umar", "Zainab",
    "Zara", "Zubair", "Anaya", "Bilal", "Eman", "Farhan", "Hammad",
    "Mariam", "Mikaal", "Noor", "Rehan", "Sami",
)
FAMILY_NAMES = (
    "Ahmed", "Ali", "Ansari", "Ashraf", "Bashir", "Chaudhry", "Farooq",
    "Hameed", "Hassan", "Hussain", "Iqbal", "Javed", "Khan", "Khawaja",
    "Malik", "Mirza", "Mustafa", "Nadeem", "Qureshi", "Raza", "Rizvi",
    "Saeed", "Siddiqui", "Syed", "Tariq", "Usman", "Wahid", "Yousuf",
    "Zafar", "Zaidi", "Zaman", "Abbasi", "Akhtar", "Anwar", "Butt",
    "Dar", "Hashmi", "Memon", "Sheikh", "Shah",
)
COURSE_TITLES = {
    "cys": (
        "Programming Fundamentals", "Data Structures and Algorithms",
        "Computer Networks and Security", "Secure Software Development",
        "Digital Forensics Fundamentals", "Ethical Hacking Fundamentals",
        "Incident Response and Threat Analysis", "Cybersecurity Capstone Project",
    ),
    "se": (
        "Programming Fundamentals", "Object-Oriented Programming",
        "Data Structures and Algorithms", "Database Systems",
        "Software Requirements Engineering", "Software Architecture and Design",
        "Software Quality and Testing", "Software Engineering Capstone Project",
    ),
    "set": (
        "Programming for Software Technology", "Web Application Development",
        "Mobile Application Development", "User Experience Design",
        "Cloud Computing Foundations", "DevOps and Software Deployment",
        "Software Testing Automation", "Applied Software Technology Project",
    ),
}


def _display_name(index):
    first_name = FIRST_NAMES[index % len(FIRST_NAMES)]
    family_name = FAMILY_NAMES[(index // len(FIRST_NAMES)) % len(FAMILY_NAMES)]
    return f"{first_name} {family_name}"


def _require_seed_departments(client):
    departments = client.request_json(
        "GET",
        "/rest/v1/departments?" + urlencode({"select": "name"}),
    )
    available = {
        item.get("name") for item in departments
        if isinstance(item, dict) and item.get("name")
    }
    required = {DEPARTMENT, *PROGRAM_DEPARTMENTS.values()}
    missing = sorted(required - available)
    if missing:
        raise RuntimeError(
            "Required departments are missing: "
            + ", ".join(missing)
            + ". Add them before seeding presentation data."
        )


def expected_demo_names():
    names = {}
    for number in range(1, TEACHER_COUNT + 1):
        username = f"demo.teacher.{number:03d}"
        names[username] = _display_name(1200 + number - 1)

    program_indexes = {code: index for index, (_program, code) in enumerate(PROGRAMS)}
    for program, code in PROGRAMS:
        for semester in SEMESTERS:
            cohort_index = program_indexes[code] * len(SEMESTERS) + semester - 1
            for number in range(1, ACCOUNTS_PER_COHORT + 1):
                username = f"demo.{code}.s{semester}.{number:03d}"
                name_index = cohort_index * ACCOUNTS_PER_COHORT + number - 1
                names[username] = _display_name(name_index)
    return names


def build_demo_records():
    records = []
    display_names = expected_demo_names()
    for number in range(1, TEACHER_COUNT + 1):
        username = f"demo.teacher.{number:03d}"
        records.append({
            "full_name": display_names[username],
            "username": username,
            "email": f"{username}@example.invalid",
            "password": secrets.token_urlsafe(18),
            "role": "teacher",
            "department": DEPARTMENT,
        })

    for program, code in PROGRAMS:
        for semester in SEMESTERS:
            for number in range(1, ACCOUNTS_PER_COHORT + 1):
                username = f"demo.{code}.s{semester}.{number:03d}"
                records.append({
                    "full_name": display_names[username],
                    "username": username,
                    "email": f"{username}@example.invalid",
                    "password": secrets.token_urlsafe(18),
                    "role": "student",
                    "department": PROGRAM_DEPARTMENTS.get(program, DEPARTMENT),
                    "student_number": f"DEMO-{code.upper()}-S{semester:02d}-{number:03d}",
                    "program": program,
                    "semester": semester,
                })
    return records


def build_presentation_academic_records(profiles):
    teachers = sorted(
        (
            profile for profile in profiles
            if profile.get("role") == "teacher"
            and profile.get("username", "").startswith("demo.teacher.")
            and profile.get("department") == DEPARTMENT
        ),
        key=lambda profile: profile["username"],
    )
    students_by_cohort = {}
    for profile in profiles:
        username = profile.get("username", "")
        if profile.get("role") != "student" or not username.startswith("demo."):
            continue
        key = (profile.get("program"), profile.get("semester"))
        students_by_cohort.setdefault(key, []).append(profile)

    if len(teachers) != TEACHER_COUNT:
        raise RuntimeError(
            f"Expected {TEACHER_COUNT} synthetic Computer Science teachers; "
            f"found {len(teachers)}."
        )
    for program, code in PROGRAMS:
        for semester in SEMESTERS:
            students = students_by_cohort.get((program, semester), [])
            if len(students) != ACCOUNTS_PER_COHORT:
                raise RuntimeError(
                    f"Expected {ACCOUNTS_PER_COHORT} synthetic students in "
                    f"{program}, semester {semester}; found {len(students)}."
                )

    courses = []
    assignments = []
    enrollments = []
    for program_index, (program, code) in enumerate(PROGRAMS):
        for semester in SEMESTERS:
            course_code = f"DEMO-{code.upper()}-S{semester:02d}"
            courses.append({
                "code": course_code,
                "name": COURSE_TITLES[code][semester - 1],
                "department": PROGRAM_DEPARTMENTS.get(program, DEPARTMENT),
                "credits": 3,
                "program": program,
                "semester": semester,
                "is_sample": False,
                "is_demo": True,
            })
            course_index = program_index * len(SEMESTERS) + semester - 1
            teacher = teachers[course_index % len(teachers)]
            assignments.append({
                "course_code": course_code,
                "profile_id": teacher["id"],
            })
            students = students_by_cohort[(program, semester)]
            enrollments.extend({
                "course_code": course_code,
                "student_id": student["id"],
                "term": DEMO_TERM,
            } for student in students)
    return courses, assignments, enrollments


class SupabaseAdmin:
    def __init__(self, project_url, service_role_key):
        self.project_url = project_url.rstrip("/")
        self.service_role_key = service_role_key

    def request_json(self, method, path, payload=None, extra_headers=None):
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {
            "apikey": self.service_role_key,
            "Authorization": f"Bearer {self.service_role_key}",
            "Content-Type": "application/json",
        }
        if path.startswith("/rest/v1/"):
            headers["Prefer"] = "return=minimal"
        if extra_headers:
            headers.update(extra_headers)
        request = Request(
            f"{self.project_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        for attempt in range(5):
            try:
                with urlopen(request, timeout=45) as response:
                    content = response.read()
                return json.loads(content) if content else None
            except HTTPError as error:
                detail = error.read().decode("utf-8", errors="replace")
                if error.code not in (429, 500, 502, 503, 504) or attempt == 4:
                    raise RuntimeError(
                        f"Supabase returned HTTP {error.code}: {detail}"
                    ) from error
                time.sleep(min(2 ** attempt, 15))
            except (URLError, TimeoutError) as error:
                if attempt == 4:
                    raise RuntimeError(f"Could not reach Supabase: {error}") from error
                time.sleep(min(2 ** attempt, 15))
        raise RuntimeError("Supabase request retries were exhausted.")

    def list_auth_users(self):
        users = []
        page = 1
        per_page = 1000
        while True:
            query = urlencode({"page": page, "per_page": per_page})
            result = self.request_json("GET", f"/auth/v1/admin/users?{query}")
            batch = result.get("users", []) if isinstance(result, dict) else []
            users.extend(batch)
            if len(batch) < per_page:
                return users
            page += 1

    def create_auth_user(self, record):
        return self.request_json("POST", "/auth/v1/admin/users", {
            "email": record["email"],
            "password": record["password"],
            "email_confirm": True,
        })

    def delete_auth_user(self, user_id):
        return self.request_json(
            "DELETE", f"/auth/v1/admin/users/{quote(user_id, safe='')}"
        )

    def insert_profiles(self, profiles):
        batch_count = (len(profiles) + PROFILE_BATCH_SIZE - 1) // PROFILE_BATCH_SIZE
        for batch_number, offset in enumerate(
            range(0, len(profiles), PROFILE_BATCH_SIZE), start=1
        ):
            batch = profiles[offset:offset + PROFILE_BATCH_SIZE]
            self.request_json("POST", "/rest/v1/profiles", batch)
            print(f"Inserted profile records: {batch_number}/{batch_count} batches")

    def update_profile_names(self, profiles):
        batch_count = (len(profiles) + PROFILE_BATCH_SIZE - 1) // PROFILE_BATCH_SIZE
        for batch_number, offset in enumerate(
            range(0, len(profiles), PROFILE_BATCH_SIZE), start=1
        ):
            batch = profiles[offset:offset + PROFILE_BATCH_SIZE]
            path = "/rest/v1/profiles?on_conflict=id"
            self.request_json(
                "POST",
                path,
                batch,
                extra_headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            )
            print(f"Updated display names: {batch_number}/{batch_count} batches")

    def list_demo_profiles(self):
        profiles = []
        offset = 0
        query = urlencode({
            "select": "id,username,role,department,program,semester",
            "username": "like.demo.*",
            "order": "username.asc",
        })
        while True:
            end = offset + PROFILE_BATCH_SIZE - 1
            batch = self.request_json(
                "GET",
                f"/rest/v1/profiles?{query}",
                extra_headers={"Range": f"{offset}-{end}"},
            )
            if not isinstance(batch, list):
                raise RuntimeError("Supabase returned an invalid demo profile list.")
            profiles.extend(batch)
            if len(batch) < PROFILE_BATCH_SIZE:
                return profiles
            offset += PROFILE_BATCH_SIZE

    def mark_demo_profiles(self):
        self.request_json(
            "PATCH",
            "/rest/v1/profiles?username=like.demo.*",
            {"is_demo": True},
        )

    def update_demo_student_departments(self):
        self.request_json(
            "PATCH",
            "/rest/v1/profiles?username=like.demo.se.*&role=eq.student"
            "&program=eq.BS%20Software%20Engineering",
            {"department": PROGRAM_DEPARTMENTS["BS Software Engineering"]},
        )

    def upsert_records(self, table, records, conflict_columns):
        results = []
        batch_count = (len(records) + PROFILE_BATCH_SIZE - 1) // PROFILE_BATCH_SIZE
        path = (
            f"/rest/v1/{table}?"
            + urlencode({"on_conflict": conflict_columns})
        )
        for batch_number, offset in enumerate(
            range(0, len(records), PROFILE_BATCH_SIZE), start=1
        ):
            batch = records[offset:offset + PROFILE_BATCH_SIZE]
            result = self.request_json(
                "POST",
                path,
                batch,
                extra_headers={
                    "Prefer": "resolution=merge-duplicates,return=representation"
                },
            )
            if isinstance(result, list):
                results.extend(result)
            print(f"Upserted {table}: {batch_number}/{batch_count} batches")
        return results


def write_credentials(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=(
            "role", "full_name", "department", "program", "semester",
            "student_number", "username", "email", "password",
        ))
        writer.writeheader()
        for record in records:
            writer.writerow({key: record.get(key, "") for key in writer.fieldnames})


def update_credentials_names(path, names):
    if not path.is_file():
        return 0

    updated_rows = []
    with path.open("r", encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        if not reader.fieldnames or "username" not in reader.fieldnames:
            raise RuntimeError(f"{path} is missing its username column.")
        for row in reader:
            username = row.get("username", "")
            if username in names:
                row["full_name"] = names[username]
            updated_rows.append(row)

    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f"{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary_path = Path(output.name)
            writer = csv.DictWriter(output, fieldnames=reader.fieldnames)
            writer.writeheader()
            writer.writerows(updated_rows)
        os.replace(temporary_path, path)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()
    return sum(row.get("username") in names for row in updated_rows)


def refresh_demo_names(client, credential_path=OUTPUT_FILE):
    names = expected_demo_names()
    existing_profiles = client.list_demo_profiles()
    profiles = [
        {"id": profile["id"], "full_name": names[profile["username"]]}
        for profile in existing_profiles
        if profile.get("username") in names and profile.get("id")
    ]
    if not profiles:
        raise RuntimeError("No matching synthetic demo profiles were found.")
    client.update_profile_names(profiles)
    credential_count = update_credentials_names(credential_path, names)
    return len(profiles), credential_count


def seed_presentation_academic_records(client):
    _require_seed_departments(client)

    profiles = client.list_demo_profiles()
    if len(profiles) != TEACHER_COUNT + len(PROGRAMS) * len(SEMESTERS) * ACCOUNTS_PER_COHORT:
        raise RuntimeError(
            "Expected all 985 demo profiles before creating courses and rosters; "
            f"found {len(profiles)}."
        )
    courses, assignments, enrollments = build_presentation_academic_records(profiles)

    client.mark_demo_profiles()
    client.update_demo_student_departments()
    saved_courses = client.upsert_records("courses", courses, "code")
    course_ids = {
        course["code"]: course["id"] for course in saved_courses
        if course.get("code") and course.get("id") is not None
    }
    if len(course_ids) != len(courses):
        raise RuntimeError(
            "Supabase did not return all 24 demo course IDs. "
            "Rerun this command; its writes are safe to repeat."
        )

    staff_rows = [
        {"course_id": course_ids[row["course_code"]], "profile_id": row["profile_id"]}
        for row in assignments
    ]
    enrollment_rows = [
        {
            "course_id": course_ids[row["course_code"]],
            "student_id": row["student_id"],
            "term": row["term"],
        }
        for row in enrollments
    ]
    client.upsert_records("course_staff", staff_rows, "course_id,profile_id")
    client.upsert_records(
        "enrollments", enrollment_rows, "course_id,student_id,term"
    )
    return len(courses), len(staff_rows), len(enrollment_rows)


def seed_demo_accounts(client, records, credential_path=OUTPUT_FILE):
    if credential_path.exists():
        raise RuntimeError(
            f"{credential_path} already exists; move it securely before retrying."
        )

    existing_users = client.list_auth_users()
    existing_emails = {
        user.get("email", "").lower()
        for user in existing_users
        if isinstance(user.get("email"), str)
    }
    duplicates = sorted(
        record["email"] for record in records
        if record["email"].lower() in existing_emails
    )
    if duplicates:
        raise RuntimeError(
            "Demo email accounts already exist; no records were created. "
            "Remove or rename the existing demo accounts before retrying."
        )

    _require_seed_departments(client)

    created_user_ids = []
    profiles = []
    try:
        for index, record in enumerate(records, start=1):
            result = client.create_auth_user(record)
            user = result.get("user", result) if isinstance(result, dict) else None
            user_id = user.get("id") if isinstance(user, dict) else None
            if not user_id:
                raise RuntimeError("Supabase did not return an ID for a new Auth user.")
            created_user_ids.append(user_id)
            profile = {
                "full_name": record["full_name"],
                "username": record["username"],
                "role": record["role"],
                "department": record["department"],
                "student_number": record.get("student_number"),
                "program": record.get("program"),
                "semester": record.get("semester"),
            }
            profile["id"] = user_id
            profiles.append(profile)
            if index % 50 == 0 or index == len(records):
                print(f"Created Auth accounts: {index}/{len(records)}")

        client.insert_profiles(profiles)
        write_credentials(credential_path, records)
    except Exception as error:
        rollback_errors = []
        for user_id in reversed(created_user_ids):
            try:
                client.delete_auth_user(user_id)
            except Exception as rollback_error:
                rollback_errors.append(str(rollback_error))
        if rollback_errors:
            try:
                write_credentials(credential_path, records[:len(created_user_ids)])
            except FileExistsError:
                pass
            raise RuntimeError(
                f"{error} Rollback was incomplete; keep the credentials at "
                f"{credential_path} safe and remove any remaining demo accounts."
            ) from error
        raise RuntimeError(
            f"{error} Newly created Auth accounts were rolled back."
        ) from error

    return len(profiles)


def main():
    parser = argparse.ArgumentParser(
        description="Create synthetic demo teachers and students in Supabase."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Create the demo users; without this flag the script only previews.",
    )
    parser.add_argument(
        "--refresh-names",
        action="store_true",
        help="Replace existing demo profile names with realistic synthetic names.",
    )
    parser.add_argument(
        "--seed-academic-data",
        action="store_true",
        help="Create operational demo courses, assign demo teachers, and enroll demo students.",
    )
    args = parser.parse_args()
    selected_operations = sum((
        args.apply,
        args.refresh_names,
        args.seed_academic_data,
    ))
    if selected_operations > 1:
        parser.error("Choose only one operation flag.")
    records = build_demo_records() if args.apply else []
    if args.apply and args.refresh_names:
        parser.error("--apply and --refresh-names cannot be used together.")
    if not args.apply and not args.refresh_names and not args.seed_academic_data:
        records = build_demo_records()
    print(
        f"Prepared {TEACHER_COUNT} synthetic teachers and "
        f"{len(PROGRAMS) * len(SEMESTERS) * ACCOUNTS_PER_COHORT} synthetic students "
        f"({ACCOUNTS_PER_COHORT} in each of 24 program/semester cohorts)."
    )
    print(
        "Synthetic teachers, Cyber Security students, and Software Engineering "
        "Technology students will be assigned to Computer Science. "
        "Software Engineering students will be assigned to Software Engineering."
    )

    if not args.apply and not args.refresh_names and not args.seed_academic_data:
        print(f"Credentials will be saved privately to {OUTPUT_FILE}.")
        print("Preview only. Pass --apply to create the Supabase accounts.")
        return 0

    load_dotenv()
    project_url = os.getenv("SUPABASE_URL")
    service_role_key = getpass(
        "Supabase service-role key (input hidden): "
    )
    if not project_url or not service_role_key:
        print("Set SUPABASE_URL and provide the service-role key.", file=sys.stderr)
        return 1
    if args.refresh_names:
        confirmation = input(
            "This updates names for matching synthetic demo profiles. "
            "Type UPDATE DEMO NAMES: "
        )
        if confirmation != "UPDATE DEMO NAMES":
            print("Cancelled; no profile names were changed.")
            return 1
    elif args.seed_academic_data:
        confirmation = input(
            "This creates 24 operational synthetic courses, 24 teacher assignments, "
            "and 960 demo enrollments. Type CREATE PRESENTATION RECORDS: "
        )
        if confirmation != "CREATE PRESENTATION RECORDS":
            print("Cancelled; no academic records were changed.")
            return 1
    else:
        confirmation = input(
            "This creates 985 login-enabled demo accounts. Type CREATE DEMO DATA: "
        )
        if confirmation != "CREATE DEMO DATA":
            print("Cancelled; no accounts were created.")
            return 1

    try:
        client = SupabaseAdmin(project_url, service_role_key)
        if args.refresh_names:
            updated, credential_count = refresh_demo_names(client)
        elif args.seed_academic_data:
            course_count, assignment_count, enrollment_count = (
                seed_presentation_academic_records(client)
            )
        else:
            created = seed_demo_accounts(client, records)
    except (RuntimeError, OSError) as error:
        print(f"Demo data operation failed: {error}", file=sys.stderr)
        return 1

    if args.refresh_names:
        print(f"Updated display names on {updated} synthetic profiles.")
        if OUTPUT_FILE.is_file():
            print(f"Updated {credential_count} names in {OUTPUT_FILE}.")
        else:
            print(f"No credentials file found at {OUTPUT_FILE}; passwords were not changed.")
        return 0
    if args.seed_academic_data:
        print(
            f"Ready: {course_count} synthetic demo courses, "
            f"{assignment_count} teacher assignments, and "
            f"{enrollment_count} student enrollments."
        )
        print(
            "These are fictional presentation records; course entries are labeled "
            "synthetic in the admin portal."
        )
        return 0

    print(
        f"Created {created} synthetic accounts. Keep {OUTPUT_FILE} private; "
        "it contains their passwords."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
