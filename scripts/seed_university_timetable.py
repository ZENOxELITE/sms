"""Turn the demo data into a working university term.

What it does (safe to run again; it only adds what is missing):
  * puts each program, its courses, students and teachers in its own department
  * makes one HOD the head of each program department
  * adds the remaining subjects of every semester (5 courses per semester)
  * gives every course a teacher from its department
  * enrolls every student in all courses of their program and semester
  * builds a clash-free weekly timetable (2 lectures per course per week)

It signs in as a campus administrator, so Supabase row-level security applies:
    set SMS_ADMIN_USERNAME=<admin username>
    set SMS_ADMIN_PASSWORD=<admin password>
    python scripts/seed_university_timetable.py
"""

import os
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

TERM = "Fall 2026 (synthetic presentation)"
TERM_WEEKS_START = date(2026, 11, 16)  # a Monday
TERM_WEEKS = 5

PROGRAM_DEPARTMENTS = {
    "BS Software Engineering": "Software Engineering",
    "BS Software Engineering Technology": "Software Engineering Technology",
    "BS Cyber Security Technology": "Cyber Security",
}
PROGRAM_CODES = {
    "BS Software Engineering": "SE",
    "BS Software Engineering Technology": "SET",
    "BS Cyber Security Technology": "CYS",
}
# Which HOD account leads which department.
DEPARTMENT_HODS = {
    "Software Engineering": "muneerhod",
    "Software Engineering Technology": "aliraza",
    "Cyber Security": "fatimahod",
}
BUILDINGS = {
    "Software Engineering": "SE Block",
    "Software Engineering Technology": "SET Block",
    "Cyber Security": "Cyber Block",
}

# Subjects added beside each semester's existing course.
CURRICULUM = {
    "BS Software Engineering": {
        1: ["Calculus and Analytic Geometry", "Applied Physics", "Functional English",
            "Introduction to Software Engineering"],
        2: ["Discrete Structures", "Linear Algebra", "Communication and Presentation Skills",
            "Digital Logic Design"],
        3: ["Software Construction and Development", "Computer Organization and Assembly Language",
            "Probability and Statistics", "Islamic Studies"],
        4: ["Operating Systems", "Software Design and Modelling", "Human Computer Interaction",
            "Technical Writing"],
        5: ["Computer Networks", "Web Engineering", "Design and Analysis of Algorithms",
            "Professional Practices"],
        6: ["Software Project Management", "Artificial Intelligence", "Mobile Application Development",
            "Information Security"],
        7: ["Software Re-engineering", "Cloud Computing", "Final Year Project I", "Entrepreneurship"],
        8: ["Software Process Improvement", "Machine Learning", "Software Engineering Economics",
            "Big Data Analytics"],
    },
    "BS Software Engineering Technology": {
        1: ["Applied Calculus", "Functional English", "Introduction to Information Technology",
            "Applied Physics Lab"],
        2: ["Object-Oriented Programming Lab", "Discrete Mathematics", "Database Fundamentals",
            "Communication Skills"],
        3: ["Data Structures Lab", "Operating System Administration", "Computer Networks Technology",
            "Statistics for Technologists"],
        4: ["Database Administration", "Software Engineering Practices", "Front-End Frameworks",
            "Islamic Studies"],
        5: ["Server-Side Development", "Agile Project Management", "Network Administration",
            "Technical Report Writing"],
        6: ["Containerization and Orchestration", "Information Security Practices",
            "API Design and Integration", "Professional Ethics"],
        7: ["Site Reliability Engineering", "Data Analytics Tools", "Industrial Training",
            "Entrepreneurship"],
        8: ["Emerging Technologies Seminar", "Quality Assurance Practices", "Systems Integration",
            "Pakistan Studies"],
    },
    "BS Cyber Security Technology": {
        1: ["Introduction to Cyber Security", "Calculus and Analytic Geometry", "Functional English",
            "Digital Logic Design"],
        2: ["Object-Oriented Programming", "Discrete Structures", "Linux System Administration",
            "Communication Skills"],
        3: ["Operating Systems", "Cryptography Fundamentals", "Probability and Statistics",
            "Islamic Studies"],
        4: ["Database Security", "Network Security", "Computer Architecture", "Technical Writing"],
        5: ["Web Application Security", "Security Risk Management", "Cyber Law and Ethics",
            "Design and Analysis of Algorithms"],
        6: ["Malware Analysis", "Cloud Security", "Wireless and Mobile Security",
            "Professional Practices"],
        7: ["Security Operations Center", "Penetration Testing", "Final Year Project I",
            "Entrepreneurship"],
        8: ["Cyber Threat Intelligence", "Blockchain Security", "Information Security Governance",
            "Pakistan Studies"],
    },
}

# 90-minute lecture slots. Friday skips the midday slot for Jummah prayers.
SLOTS = [time(8, 30), time(10, 15), time(12, 0), time(14, 0), time(15, 45)]
LECTURE = timedelta(minutes=90)
DAY_PAIRS = [(0, 2), (1, 3), (2, 4), (0, 3), (1, 4), (0, 4)]


def _slot_allowed(day, slot_index):
    return not (day == 4 and SLOTS[slot_index] == time(12, 0))


def planned_courses():
    """New course rows for every program semester."""
    rows = []
    for program, semesters in CURRICULUM.items():
        code = PROGRAM_CODES[program]
        for semester, titles in semesters.items():
            for number, title in enumerate(titles, start=2):
                rows.append({
                    "code": f"{code}-{semester}0{number}",
                    "name": title,
                    "department": PROGRAM_DEPARTMENTS[program],
                    "credits": 1 if title.endswith("Lab") else 3,
                    "program": program,
                    "semester": semester,
                    "is_sample": False,
                    "is_demo": True,
                })
    return rows


def assign_teachers(courses, staff, teachers_by_department):
    """Keep existing assignments; give every unstaffed course the least-loaded department teacher."""
    staffed = {}
    for row in staff:
        staffed.setdefault(row["course_id"], []).append(row["profile_id"])
    load = {}
    for teacher_ids in staffed.values():
        for teacher_id in teacher_ids:
            load[teacher_id] = load.get(teacher_id, 0) + 1
    new_rows = []
    for course in sorted(courses, key=lambda item: (item["program"], item["semester"], item["code"])):
        if staffed.get(course["id"]):
            continue
        teachers = teachers_by_department.get(course["department"], [])
        if not teachers:
            raise RuntimeError(f"No teachers in {course['department']} for {course['code']}.")
        teacher_id = min(teachers, key=lambda tid: (load.get(tid, 0), teachers.index(tid)))
        load[teacher_id] = load.get(teacher_id, 0) + 1
        staffed[course["id"]] = [teacher_id]
        new_rows.append({"course_id": course["id"], "profile_id": teacher_id})
    return staffed, new_rows


def build_weekly_timetable(courses, staffed):
    """Pick two weekly lecture slots per course with no cohort or teacher clashes.

    Returns {course_id: [(day, slot_index), (day, slot_index)]}.
    """
    cohort_busy = set()
    teacher_busy = set()
    timetable = {}
    ordered = sorted(courses, key=lambda item: (item["program"], item["semester"], item["code"]))
    for course in ordered:
        cohort = (course["program"], course["semester"])
        teachers = staffed.get(course["id"], [])
        def free(slot):
            return (
                _slot_allowed(*slot)
                and (cohort, slot) not in cohort_busy
                and not any((teacher, slot) in teacher_busy for teacher in teachers)
            )

        # Prefer the same time on two well-spaced days, then any two different days.
        candidates = [
            [(first, index), (second, index)]
            for index in range(len(SLOTS)) for first, second in DAY_PAIRS
        ] + [
            [(first, i), (second, j)]
            for first in range(5) for second in range(first + 1, 5)
            for i in range(len(SLOTS)) for j in range(len(SLOTS))
        ]
        chosen = next((pair for pair in candidates if all(free(slot) for slot in pair)), None)
        if not chosen:
            raise RuntimeError(f"Could not fit {course['code']} into the weekly timetable.")
        for slot in chosen:
            cohort_busy.add((cohort, slot))
            for teacher in teachers:
                teacher_busy.add((teacher, slot))
        timetable[course["id"]] = chosen
    return timetable


def session_rows(course, weekly_slots):
    building = BUILDINGS.get(course["department"], "Main Block")
    room = f"{building} - Room {course['semester']}0{1 + (course['semester'] % 3)}"
    rows = []
    for week in range(TERM_WEEKS):
        monday = TERM_WEEKS_START + timedelta(weeks=week)
        for day, slot_index in weekly_slots:
            starts = datetime.combine(monday + timedelta(days=day), SLOTS[slot_index])
            rows.append({
                "course_id": course["id"],
                "starts_at": starts.isoformat(),
                "ends_at": (starts + LECTURE).isoformat(),
                "location": room,
            })
    return rows


def _chunks(rows, size=500):
    for start in range(0, len(rows), size):
        yield rows[start:start + size]


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sms_project.settings")
    import django

    django.setup()
    from auth_sessions import get_session
    from portal import services
    from portal_data import _read
    from supabase_client import create_supabase_client

    username = os.getenv("SMS_ADMIN_USERNAME")
    password = os.getenv("SMS_ADMIN_PASSWORD")
    if not username or not password:
        raise SystemExit("Set SMS_ADMIN_USERNAME and SMS_ADMIN_PASSWORD to an administrator account.")
    email = services._resolve_login_email(username)
    result = services._authenticate_credentials(email, password) if email else None
    if not result:
        raise SystemExit("Administrator sign-in failed.")
    client = create_supabase_client(get_session(result[1])["access_token"])

    profiles = _read(client, "profiles", "id,role,username,department,program,semester")
    if not any(p["role"] == "admin" and p["username"] == username for p in profiles):
        raise SystemExit("This account is not an administrator.")

    # 1. Departments follow programs: courses, students, then HODs.
    for program, department in PROGRAM_DEPARTMENTS.items():
        client.table("courses").update({"department": department}).eq("program", program).execute()
        client.table("profiles").update({"department": department}).eq("role", "student").eq(
            "program", program).execute()
    hod_by_username = {p["username"]: p for p in profiles if p["role"] == "hod"}
    for department, hod_username in DEPARTMENT_HODS.items():
        hod = hod_by_username.get(hod_username)
        if hod:
            client.table("profiles").update({"department": department}).eq("id", hod["id"]).execute()
        else:
            print(f"HOD account {hod_username} was not found; {department} has no head yet.")

    # 2. Remaining subjects of every semester.
    client.table("courses").upsert(planned_courses(), on_conflict="code").execute()
    courses = [
        course for course in _read(client, "courses", "*")
        if not course.get("is_sample") and course.get("program") in PROGRAM_DEPARTMENTS
        and course.get("semester")
    ]

    # 3. Teachers: keep current assignments, group teachers by the department they teach in.
    staff = _read(client, "course_staff", "course_id,profile_id")
    teacher_ids = {p["id"] for p in profiles if p["role"] == "teacher"}
    course_by_id = {course["id"]: course for course in courses}
    teaching_department = {}
    for row in staff:
        course = course_by_id.get(row["course_id"])
        if course and row["profile_id"] in teacher_ids:
            teaching_department.setdefault(row["profile_id"], course["department"])
    departments = list(PROGRAM_DEPARTMENTS.values())
    spare = sorted(
        (p for p in profiles if p["role"] == "teacher" and p["id"] not in teaching_department),
        key=lambda p: p["username"],
    )
    for index, teacher in enumerate(spare):
        smallest = min(departments, key=lambda d: (list(teaching_department.values()).count(d),
                                                   departments.index(d)))
        teaching_department[teacher["id"]] = smallest
    teachers_by_department = {}
    for teacher in sorted((p for p in profiles if p["id"] in teaching_department),
                          key=lambda p: p["username"]):
        teachers_by_department.setdefault(teaching_department[teacher["id"]], []).append(teacher["id"])
    for teacher_id, department in teaching_department.items():
        client.table("profiles").update({"department": department}).eq("id", teacher_id).execute()
    staffed, new_staff = assign_teachers(courses, staff, teachers_by_department)
    if new_staff:
        client.table("course_staff").upsert(new_staff, on_conflict="course_id,profile_id").execute()

    # 4. Every student takes all courses of their program semester.
    courses_by_cohort = {}
    for course in courses:
        courses_by_cohort.setdefault((course["program"], course["semester"]), []).append(course)
    enrollments = [
        {"course_id": course["id"], "student_id": student["id"], "term": TERM}
        for student in profiles if student["role"] == "student"
        for course in courses_by_cohort.get((student.get("program"), student.get("semester")), [])
    ]
    for chunk in _chunks(enrollments):
        client.table("enrollments").upsert(chunk, on_conflict="course_id,student_id,term").execute()

    # 5. Weekly timetable for courses that have no lectures yet.
    scheduled = {row["course_id"] for row in _read(client, "class_sessions", "course_id")}
    timetable = build_weekly_timetable(courses, staffed)
    sessions = [
        row for course in courses if course["id"] not in scheduled
        for row in session_rows(course, timetable[course["id"]])
    ]
    for chunk in _chunks(sessions):
        client.table("class_sessions").insert(chunk).execute()

    print(f"Courses in the term: {len(courses)}")
    print(f"New teacher assignments: {len(new_staff)}")
    print(f"Enrollments checked: {len(enrollments)}")
    print(f"Lectures scheduled: {len(sessions)}")


if __name__ == "__main__":
    main()
