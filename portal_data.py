from datetime import datetime
from concurrent.futures import ThreadPoolExecutor


def _read(client, table, columns="*"):
    response = client.table(table).select(columns).limit(200).execute()
    return response.data


def _where(client, table, column, value, columns="*"):
    response = client.table(table).select(columns).eq(column, value).limit(200).execute()
    return response.data


def _in(client, table, column, values, columns="*"):
    if not values:
        return []
    response = client.table(table).select(columns).in_(column, values).limit(200).execute()
    return response.data


def _parallel_reads(client, *queries):
    with ThreadPoolExecutor(max_workers=len(queries)) as executor:
        futures = [
            executor.submit(_read, client, table, columns)
            for table, columns in queries
        ]
        return [future.result() for future in futures]


def _parallel_execute(*queries):
    with ThreadPoolExecutor(max_workers=len(queries)) as executor:
        futures = [executor.submit(query.execute) for query in queries]
        return [future.result().data for future in futures]


def _table(page, title, columns, records):
    page["table_title"] = title
    page["columns"] = columns
    page["rows"] = records


def _date(value):
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%d %b %Y %H:%M")
    except (ValueError, AttributeError, TypeError):
        return str(value)


def _student_courses(client, profile):
    enrollments = _where(client, "enrollments", "student_id", profile["id"], "course_id,term")
    ids = list({row["course_id"] for row in enrollments})
    return _in(client, "courses", "id", ids), enrollments


def _staff_courses(client, profile):
    assigned = _where(client, "course_staff", "profile_id", profile["id"], "course_id")
    return _in(client, "courses", "id", list({row["course_id"] for row in assigned}))


def _course_sessions(client, courses):
    return _in(client, "class_sessions", "course_id", [course["id"] for course in courses])


def _enrolled_students(client, course_ids):
    enrollments = _in(client, "enrollments", "course_id", course_ids, "student_id,course_id")
    profile_ids = list({row["student_id"] for row in enrollments})
    profiles = _in(client, "profiles", "id", profile_ids, "id,full_name,student_number")
    profile_lookup = {profile["id"]: profile for profile in profiles}
    return enrollments, profile_lookup


def build_live_page(role, section, profile, client):
    page = {
        "key": section,
        "title": section.replace("-", " ").replace("_", " ").title(),
        "summary": "Live information from the Supabase project.",
        "metrics": [],
        "columns": [],
        "rows": [],
        "form_fields": [],
        "form_title": "",
    }
    uid = profile["id"]
    if section == "profile":
        page["title"] = "Student profile"
        page["summary"] = "Your account information."
        page["metrics"] = [
            ("Name", profile.get("full_name") or ""),
            ("Student ID", profile.get("student_number") or "Not assigned"),
            ("Department", profile.get("department") or "Not assigned"),
        ]
        return page

    if role == "student":
        courses, _enrollments = _student_courses(client, profile)
        course_by_id = {course["id"]: course for course in courses}
        course_ids = list(course_by_id)
        if section == "datasheet":
            exams = _in(client, "exams", "course_id", course_ids)
            exams.sort(key=lambda item: item.get("starts_at") or "")
            _table(page, "Exam datasheet", ["Course", "Exam", "Type", "Date", "Location"],
                   [[course_by_id.get(item.get("course_id"), {}).get("name", ""),
                     item.get("title", ""), item.get("exam_type", "").title(),
                     _date(item.get("starts_at")), item.get("location", "")]
                    for item in exams])
        elif section in ("dashboard", "timetable"):
            sessions = _course_sessions(client, courses)
            sessions.sort(key=lambda item: item.get("starts_at") or "")
            _table(page, "Upcoming classes" if section == "dashboard" else page["title"],
                   ["Date", "Course", "Location"],
                   [[_date(item.get("starts_at")), course_by_id.get(item.get("course_id"), {}).get("name", ""),
                     item.get("location", "")] for item in sessions])
            if section == "dashboard":
                page["title"] = "Dashboard"
                page["metrics"] = [
                    ("Enrolled courses", str(len(courses))),
                    ("Student ID", profile.get("student_number") or "Not assigned"),
                ]
        elif section == "attendance":
            if course_ids:
                sessions, records = _parallel_execute(
                    client.table("class_sessions").select("*").in_("course_id", course_ids).limit(200),
                    client.table("attendance_records").select("*").eq("student_id", uid).limit(200),
                )
            else:
                sessions, records = [], []
            session_by_id = {item["id"]: item for item in sessions}
            _table(page, "Attendance records", ["Date", "Course", "Status"],
                   [[_date(session_by_id.get(item.get("session_id"), {}).get("starts_at")),
                     course_by_id.get(session_by_id.get(item.get("session_id"), {}).get("course_id"), {}).get("name", ""),
                     item.get("status", "")]
                    for item in records if item.get("session_id") in session_by_id])
        elif section == "results":
            grades = _where(client, "grades", "student_id", uid)
            _table(page, "Results", ["Course", "Grade", "Term", "Published"],
                   [[course_by_id.get(item.get("course_id"), {}).get("name", ""), item.get("grade", ""),
                     item.get("term", ""), "Yes" if item.get("published") else "Pending"] for item in grades])
        elif section == "notifications":
            notices = _where(client, "announcements", "published", True)
            notices.sort(key=lambda item: item.get("published_at") or "", reverse=True)
            _table(page, "Published announcements", ["Date", "Title", "Announcement"],
                   [[_date(item.get("published_at")), item.get("title", ""), item.get("body", "")] for item in notices])
        elif section == "invoices":
            invoices = _where(client, "invoices", "student_id", uid)
            _table(page, "Invoices", ["Description", "Amount", "Due date", "Status"],
                   [[item.get("description", ""), item.get("amount", ""), item.get("due_date", ""), item.get("status", "")]
                    for item in invoices])
        elif section in ("feedback", "complaints"):
            requests = _where(client, "student_requests", "student_id", uid)
            kind = "feedback" if section == "feedback" else "complaint"
            requests = [item for item in requests if item.get("request_type") == kind]
            _table(page, "Your submissions", ["Subject", "Status", "Submitted"],
                   [[item.get("subject", ""), item.get("status", ""), _date(item.get("created_at"))] for item in requests])
            page["form_title"] = "New " + kind
            page["form_action"] = "submit-request"
            page["form_fields"] = [
                {"name": "subject", "label": "Subject", "type": "text", "required": True},
                {"name": "message", "label": "Message", "type": "textarea", "required": True},
            ]
        return page

    if role == "teacher":
        courses = _staff_courses(client, profile)
        course_by_id = {course["id"]: course for course in courses}
        course_ids = list(course_by_id)
        if section in ("dashboard", "classes"):
            _table(page, "Assigned courses", ["Course", "Code", "Credits"],
                   [[item.get("name", ""), item.get("code", ""), item.get("credits", "")] for item in courses])
            if section == "dashboard":
                course_enrollments, _profiles = _enrolled_students(client, course_ids)
                page["title"] = "Dashboard"
                page["metrics"] = [
                    ("Assigned courses", str(len(courses))),
                    ("Enrolled students", str(len({item["student_id"] for item in course_enrollments}))),
                ]
        elif section in ("attendance-entry", "results-entry"):
            sessions = _course_sessions(client, courses)
            enrollments, student_lookup = _enrolled_students(client, course_ids)
            students = []
            for enrollment in enrollments:
                student = student_lookup.get(enrollment["student_id"])
                if student and student not in students:
                    students.append(student)
            page["form_title"] = "Record attendance" if section == "attendance-entry" else "Enter a grade"
            page["form_action"] = section
            page["form_fields"] = [
                {"name": "course_id", "label": "Course", "type": "select", "required": True,
                 "options": [(str(item["id"]), f'{item["name"]} ({item["code"]})') for item in courses]},
                {"name": "student_id", "label": "Student", "type": "select", "required": True,
                 "options": [(item["id"], f'{item.get("full_name", "")} ({item.get("student_number") or "No ID"})') for item in students]},
            ]
            if section == "attendance-entry":
                page["form_fields"].insert(1, {
                    "name": "session_id", "label": "Class session", "type": "select", "required": True,
                    "options": [(str(item["id"]), f'{course_by_id.get(item["course_id"], {}).get("code", "")} - {_date(item.get("starts_at"))}')
                                for item in sessions],
                })
                page["form_fields"].append({
                    "name": "status", "label": "Attendance", "type": "select", "required": True,
                    "options": [(value, value.title()) for value in ("present", "absent", "late", "excused")],
                })
            else:
                page["form_fields"].extend([
                    {"name": "grade", "label": "Grade", "type": "text", "required": True},
                    {"name": "term", "label": "Term", "type": "text", "required": True},
                ])
            page["form_ready"] = bool(courses and students and (section != "attendance-entry" or sessions))
        return page

    department = profile.get("department")
    if role == "hod":
        courses = _where(client, "courses", "department", department) if department else []
        ids = [item["id"] for item in courses]
        if section in ("dashboard", "department"):
            enrollments = _in(client, "enrollments", "course_id", ids)
            _table(page, "Department courses", ["Course", "Code", "Credits"],
                   [[item.get("name", ""), item.get("code", ""), item.get("credits", "")] for item in courses])
            page["metrics"] = [("Department courses", str(len(courses))), ("Enrollments", str(len(enrollments)))]
        elif section == "review":
            sessions = _course_sessions(client, courses)
            _table(page, "Department class sessions", ["Course", "Date", "Location"],
                   [[next((c.get("name", "") for c in courses if c["id"] == item["course_id"]), ""),
                     _date(item.get("starts_at")), item.get("location", "")] for item in sessions])
        return page

    if role == "admin":
        if section in ("dashboard", "users"):
            if section == "users":
                profiles, departments = _parallel_reads(
                    client,
                    ("profiles", "id,full_name,username,role,department,student_number"),
                    ("departments", "name"),
                )
            else:
                profiles = _read(client, "profiles", "id,full_name,username,role,department,student_number")
            _table(page, "Campus accounts", ["Name", "Username", "Role", "Department", "Student ID"],
                   [[item.get("full_name", ""), item.get("username") or "", item.get("role", ""),
                     item.get("department") or "",
                     item.get("student_number") or ""] for item in profiles])
            if section == "dashboard":
                courses = _read(client, "courses", "id")
                page["title"] = "Dashboard"
                page["metrics"] = [
                    ("Student accounts", str(sum(item.get("role") == "student" for item in profiles))),
                    ("Staff accounts", str(sum(item.get("role") in ("teacher", "hod", "admin") for item in profiles))),
                    ("Courses", str(len(courses))),
                ]
            else:
                page["form_title"] = "Create a campus account"
                page["form_action"] = "create-account"
                page["form_fields"] = [
                    {"name": "email", "label": "Email address", "type": "email", "required": True},
                    {"name": "full_name", "label": "Full name", "type": "text", "required": True},
                    {"name": "username", "label": "Username", "type": "text", "required": True},
                    {"name": "password", "label": "Initial password (8+ characters)", "type": "password", "required": True},
                    {"name": "role", "label": "Role", "type": "select", "required": True,
                     "options": [(value, label) for value, label in (
                         ("student", "Student"), ("teacher", "Teacher"), ("hod", "HOD"))]},
                    {"name": "department", "label": "Department", "type": "select", "required": True,
                     "options": [(item["name"], item["name"]) for item in departments]},
                    {"name": "student_number", "label": "Student number (students only)", "type": "text",
                     "required": False},
                ]
                page["form_ready"] = bool(departments)
                if not departments:
                    page["extra_forms"] = []
                    page["form_note"] = "Add a department before creating campus accounts."
        elif section == "departments":
            departments = _read(client, "departments", "name,created_at")
            _table(page, "Departments", ["Department", "Added"],
                   [[item.get("name", ""), _date(item.get("created_at"))] for item in departments])
            page["form_title"] = "Add a department"
            page["form_action"] = "add-department"
            page["form_fields"] = [
                {"name": "name", "label": "Department name", "type": "text", "required": True},
            ]
        elif section == "courses":
            courses, departments, profiles = _parallel_reads(
                client,
                ("courses", "id,name,code,department,credits"),
                ("departments", "name"),
                ("profiles", "id,full_name,role,student_number"),
            )
            _table(page, "Courses", ["Course", "Code", "Department", "Credits"],
                   [[item.get("name", ""), item.get("code", ""), item.get("department", ""), item.get("credits", "")]
                    for item in courses])
            page["form_title"] = "Add a course"
            page["form_action"] = "add-course"
            page["form_fields"] = [
                {"name": "name", "label": "Course name", "type": "text", "required": True},
                {"name": "code", "label": "Course code", "type": "text", "required": True},
                {"name": "department", "label": "Department", "type": "select", "required": True,
                 "options": [(item["name"], item["name"]) for item in departments]},
                {"name": "credits", "label": "Credits", "type": "number", "required": True},
            ]
            students = [item for item in profiles if item.get("role") == "student"]
            teachers = [item for item in profiles if item.get("role") == "teacher"]
            course_options = [(str(item["id"]), f'{item["code"]} - {item["name"]}') for item in courses]
            page["extra_forms"] = [
                {
                    "title": "Schedule a class",
                    "action": "add-session",
                    "ready": bool(courses),
                    "fields": [
                        {"name": "course_id", "label": "Course", "type": "select", "required": True, "options": course_options},
                        {"name": "starts_at", "label": "Starts", "type": "datetime-local", "required": True},
                        {"name": "ends_at", "label": "Ends", "type": "datetime-local", "required": True},
                        {"name": "location", "label": "Location", "type": "text", "required": True},
                    ],
                },
                {
                    "title": "Schedule an exam",
                    "action": "add-exam",
                    "ready": bool(courses),
                    "fields": [
                        {"name": "course_id", "label": "Course", "type": "select", "required": True, "options": course_options},
                        {"name": "title", "label": "Exam name", "type": "text", "required": True},
                        {"name": "exam_type", "label": "Exam type", "type": "select", "required": True,
                         "options": [(value, value.title()) for value in ("quiz", "midterm", "final", "exam")]},
                        {"name": "starts_at", "label": "Date and time", "type": "datetime-local", "required": True},
                        {"name": "location", "label": "Location", "type": "text", "required": True},
                    ],
                },
                {
                    "title": "Assign a teacher",
                    "action": "assign-teacher",
                    "ready": bool(courses and teachers),
                    "fields": [
                        {"name": "course_id", "label": "Course", "type": "select", "required": True, "options": course_options},
                        {"name": "profile_id", "label": "Teacher", "type": "select", "required": True,
                         "options": [(item["id"], item.get("full_name", "")) for item in teachers]},
                    ],
                },
                {
                    "title": "Enroll a student",
                    "action": "enroll-student",
                    "ready": bool(courses and students),
                    "fields": [
                        {"name": "course_id", "label": "Course", "type": "select", "required": True, "options": course_options},
                        {"name": "student_id", "label": "Student", "type": "select", "required": True,
                         "options": [(item["id"], f'{item.get("full_name", "")} ({item.get("student_number") or "No ID"})')
                                     for item in students]},
                        {"name": "term", "label": "Term", "type": "text", "required": True},
                    ],
                },
            ]
            exams = _in(client, "exams", "course_id", [item["id"] for item in courses])
            course_by_id = {item["id"]: item for item in courses}
            exams.sort(key=lambda item: item.get("starts_at") or "")
            page["extra_tables"] = [{
                "title": "Scheduled exams",
                "columns": ["Course", "Exam", "Type", "Date", "Location"],
                "rows": [[course_by_id.get(item.get("course_id"), {}).get("name", ""),
                          item.get("title", ""), item.get("exam_type", "").title(),
                          _date(item.get("starts_at")), item.get("location", "")]
                         for item in exams],
            }]
        elif section == "announcements":
            announcements = _read(client, "announcements", "title,body,audience,published,published_at")
            _table(page, "Announcements", ["Title", "Audience", "Status", "Published"],
                   [[item.get("title", ""), item.get("audience", ""), "Published" if item.get("published") else "Draft",
                     _date(item.get("published_at"))] for item in announcements])
            page["form_title"] = "Publish an announcement"
            page["form_action"] = "add-announcement"
            page["form_fields"] = [
                {"name": "title", "label": "Title", "type": "text", "required": True},
                {"name": "body", "label": "Message", "type": "textarea", "required": True},
                {"name": "audience", "label": "Audience", "type": "select", "required": True,
                 "options": [(value, value.title()) for value in ("all", "student", "teacher")]},
            ]
        return page
    return page
