import base64
import json
import re
import time
import unittest
import os
from types import SimpleNamespace
from urllib.error import HTTPError
from io import BytesIO
from urllib.parse import urlsplit
from unittest.mock import MagicMock, patch

import app as app_module
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner
from starlette.middleware.sessions import SessionMiddleware
from auth_sessions import delete_session
from portal_data import _in, _where, build_live_page


class FakeQuery:
    def __init__(self, result):
        self.result = result

    def select(self, _columns):
        return self

    def eq(self, _column, _value):
        return self

    def limit(self, _count):
        return self

    def range(self, _start, _end):
        return self

    def execute(self):
        return SimpleNamespace(data=self.result)


class FakeTableClient:
    def __init__(self, profile):
        self.profile = profile

    def table(self, _name):
        return FakeQuery([self.profile])


class FakeWriteQuery:
    def __init__(self, writes, table_name, read_results):
        self.writes = writes
        self.table_name = table_name
        self.read_results = read_results
        self.filters = []
        self.is_delete = False

    def insert(self, payload):
        self.writes.append(payload)
        return self

    def delete(self):
        self.is_delete = True
        return self

    def upsert(self, payload, **_kwargs):
        self.writes.append(payload)
        return self

    def select(self, _columns):
        return self

    def in_(self, _column, _values):
        return self

    def eq(self, column, value):
        if self.is_delete:
            self.filters.append((column, value))
        return self

    def limit(self, _count):
        return self

    def range(self, _start, _end):
        return self

    def execute(self):
        if self.is_delete:
            self.writes.append({"delete": self.table_name, "filters": self.filters})
            return SimpleNamespace(data=[dict(self.filters)])
        return SimpleNamespace(data=self.read_results.get(self.table_name, []))


class FakeWriteClient:
    def __init__(self, read_results=None):
        self.writes = []
        self.read_results = read_results or {}

    def table(self, name):
        return FakeWriteQuery(self.writes, name, self.read_results)


class FakeReadQuery:
    def __init__(self, rows):
        self.rows = rows
        self.filters = []
        self.offset = 0
        self.end = None

    def select(self, _columns):
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def in_(self, column, values):
        self.filters.append((column, values))
        return self

    def limit(self, _count):
        return self

    def range(self, start, end):
        self.offset = start
        self.end = end
        return self

    def execute(self):
        rows = [
            row for row in self.rows
            if all(row.get(column) == value if not isinstance(value, list) else row.get(column) in value
                   for column, value in self.filters)
        ]
        page = rows[self.offset:] if self.end is None else rows[self.offset:self.end + 1]
        return SimpleNamespace(data=page)


class FakeReadClient:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return FakeReadQuery(self.tables.get(name, []))


class PortalAppTests(unittest.TestCase):
    def setUp(self):
        for middleware in app_module.app.user_middleware:
            if middleware.cls is SessionMiddleware:
                middleware.kwargs["secret_key"] = "test-secret"
        self.client = TestClient(app_module.app, follow_redirects=False)

    def _set_session(self, **values):
        session = self._read_session()
        session.update(values)
        session.setdefault("csrf_token", "test-csrf-token")
        payload = base64.b64encode(json.dumps(session).encode("utf-8"))
        cookie = TimestampSigner("test-secret").sign(payload).decode("utf-8")
        self.client.cookies.set("session", cookie)

    def _read_session(self):
        cookie = self.client.cookies.get("session")
        if not cookie:
            return {}
        payload = TimestampSigner("test-secret").unsign(cookie)
        return json.loads(base64.b64decode(payload))

    def _location(self, response):
        return urlsplit(response.headers["location"]).path

    def _csrf(self):
        response = self.client.get("/")
        match = re.search(rb'name="csrf_token" value="([^"]+)"', response.content)
        self.assertIsNotNone(match)
        return match.group(1).decode()

    def test_login_page_offers_email_and_username_without_role_choice(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'name="login_method"', response.content)
        self.assertIn(b'value="email">Email', response.content)
        self.assertIn(b'value="username">Username', response.content)
        self.assertIn(b"logo_sms_wordmark.jpg", response.content)
        self.assertNotIn(b'data-role=', response.content)

    def test_username_lookup_calls_private_edge_function(self):
        response_body = MagicMock()
        response_body.__enter__.return_value.read.return_value = b'{"email":"student@example.test"}'
        with patch.dict(os.environ, {
            "SUPABASE_URL": "https://project.example.test",
            "SUPABASE_ANON_KEY": "public-key",
            "SUPABASE_USERNAME_LOOKUP_SECRET": "server-only-secret",
        }):
            with patch.object(app_module, "urlopen", return_value=response_body) as open_request:
                email = app_module._resolve_login_email("Student_01")

        self.assertEqual(email, "student@example.test")
        lookup_request = open_request.call_args.args[0]
        self.assertEqual(lookup_request.full_url, "https://project.example.test/functions/v1/username-lookup")
        self.assertEqual(lookup_request.get_header("Authorization"), "Bearer public-key")
        self.assertEqual(lookup_request.get_header("X-username-lookup-secret"), "server-only-secret")
        self.assertEqual(lookup_request.data, b'{"username": "student_01"}')

    def test_username_lookup_401_reports_shared_secret_mismatch(self):
        unauthorized = HTTPError(
            "https://project.example.test/functions/v1/username-lookup",
            401,
            "Unauthorized",
            {},
            BytesIO(b'{"error":"Unauthorized"}'),
        )
        with patch.dict(os.environ, {
            "SUPABASE_URL": "https://project.example.test",
            "SUPABASE_ANON_KEY": "public-key",
            "SUPABASE_USERNAME_LOOKUP_SECRET": "server-only-secret",
        }):
            with patch.object(app_module, "urlopen", side_effect=unauthorized):
                with self.assertRaisesRegex(RuntimeError, "shared secret"):
                    app_module._resolve_login_email("student_01")

    def test_account_creation_reports_supabase_gateway_error_message(self):
        unauthorized = HTTPError(
            "https://project.example.test/functions/v1/admin-create-account",
            401,
            "Unauthorized",
            {},
            BytesIO(b'{"message":"Invalid JWT"}'),
        )
        with patch.dict(os.environ, {
            "SUPABASE_URL": "https://project.example.test",
            "SUPABASE_ANON_KEY": "public-key",
        }):
            with patch.object(app_module, "urlopen", side_effect=unauthorized):
                with self.assertRaisesRegex(RuntimeError, "Invalid JWT"):
                    app_module._create_campus_account(
                        {"email": "student@example.test"},
                        "admin-access-token",
                    )

    def test_account_creation_sends_user_token_in_explicit_header(self):
        success = MagicMock()
        success.__enter__.return_value.read.return_value = b'{"user_id":"new-user"}'
        with patch.dict(os.environ, {
            "SUPABASE_URL": "https://project.example.test",
            "SUPABASE_ANON_KEY": "public-key",
        }):
            with patch.object(app_module, "urlopen", return_value=success) as open_request:
                result = app_module._create_campus_account(
                    {"email": "student@example.test"},
                    "admin-access-token",
                )

        self.assertEqual(result, {"user_id": "new-user"})
        function_request = open_request.call_args.args[0]
        self.assertEqual(
            function_request.get_header("X-supabase-user-access-token"),
            "admin-access-token",
        )
        self.assertEqual(
            function_request.get_header("Authorization"),
            "Bearer admin-access-token",
        )

    def test_account_creation_rejects_missing_user_token_before_request(self):
        with patch.dict(os.environ, {
            "SUPABASE_URL": "https://project.example.test",
            "SUPABASE_ANON_KEY": "public-key",
        }):
            with patch.object(app_module, "urlopen") as open_request:
                with self.assertRaisesRegex(RuntimeError, "signed-in Supabase session"):
                    app_module._create_campus_account(
                        {"email": "student@example.test"},
                        "",
                    )

        open_request.assert_not_called()

    def test_account_creation_lists_missing_local_configuration(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(
                RuntimeError,
                r"Set SUPABASE_URL and SUPABASE_ANON_KEY in the \.env file beside app.py",
            ):
                app_module._create_campus_account(
                    {"email": "student@example.test"},
                    "admin-access-token",
                )

    def test_portal_requires_authentication(self):
        response = self.client.get("/portal/student/dashboard")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self._location(response), "/")

    def test_post_without_csrf_token_is_rejected(self):
        response = self.client.post("/logout")
        self.assertEqual(response.status_code, 400)

    def test_login_uses_database_role_and_keeps_tokens_out_of_cookie(self):
        user = SimpleNamespace(id="user-123", email="teacher@example.test")
        auth_session = SimpleNamespace(
            access_token="access-secret-token",
            refresh_token="refresh-secret-token",
            expires_at=int(time.time()) + 3600,
            expires_in=3600,
        )
        profile = {
            "id": "user-123",
            "role": "teacher",
            "full_name": "Test Teacher",
            "department": "Science",
        }
        auth_client = SimpleNamespace(
            auth=SimpleNamespace(
                sign_in_with_password=lambda _credentials: SimpleNamespace(user=user, session=auth_session),
                get_user=lambda _token: SimpleNamespace(user=user),
            )
        )
        profile_client = FakeTableClient(profile)

        with patch.object(app_module, "_resolve_login_email", return_value="teacher@example.test"):
            with patch.object(
                app_module,
                "create_supabase_client",
                side_effect=[auth_client, auth_client, profile_client],
            ):
                response = self.client.post(
                    "/login",
                    data={
                        "csrf_token": self._csrf(),
                        "login_method": "username",
                        "identifier": "testteacher",
                        "password": "example",
                    },
                )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self._location(response), "/portal/teacher/dashboard")
        cookie = self.client.cookies.get("session")
        self.assertIsNotNone(cookie)
        self.assertNotIn("access-secret-token", cookie)
        self.assertNotIn("refresh-secret-token", cookie)
        delete_session(self._read_session().get("auth_session_id"))

    def test_email_login_skips_username_lookup(self):
        user = SimpleNamespace(id="user-123", email="teacher@example.test")
        auth_session = SimpleNamespace(
            access_token="access-secret-token",
            refresh_token="refresh-secret-token",
            expires_at=int(time.time()) + 3600,
            expires_in=3600,
        )
        profile = {
            "id": "user-123",
            "role": "teacher",
            "full_name": "Test Teacher",
            "department": "Science",
        }
        auth_client = SimpleNamespace(
            auth=SimpleNamespace(
                sign_in_with_password=lambda credentials: SimpleNamespace(user=user, session=auth_session)
                if credentials == {"email": "teacher@example.test", "password": "example"}
                else self.fail("Email login sent unexpected credentials."),
                get_user=lambda _token: SimpleNamespace(user=user),
            )
        )

        with patch.object(app_module, "_resolve_login_email") as lookup:
            with patch.object(
                app_module,
                "create_supabase_client",
                side_effect=[auth_client, auth_client, FakeTableClient(profile)],
            ):
                response = self.client.post(
                    "/login",
                    data={
                        "csrf_token": self._csrf(),
                        "login_method": "email",
                        "identifier": "Teacher@Example.Test",
                        "password": "example",
                    },
                )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self._location(response), "/portal/teacher/dashboard")
        lookup.assert_not_called()
        delete_session(self._read_session().get("auth_session_id"))

    def test_user_cannot_open_a_different_role_portal(self):
        profile = {"id": "teacher-1", "role": "teacher", "full_name": "Teacher"}
        user = SimpleNamespace(id="teacher-1", email="teacher@example.test")

        def set_test_user(_request, _session_id):
            _request.state.profile = profile
            _request.state.user = user
            _request.state.supabase = None
            return profile

        with patch.object(app_module, "_set_authenticated_user", side_effect=set_test_user):
            self._set_session(auth_session_id="test-session")
            response = self.client.get("/portal/admin/dashboard")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self._location(response), "/portal/teacher/dashboard")

    def test_portal_renders_live_data(self):
        profile = {"id": "student-1", "role": "student", "full_name": "Live Student"}
        user = SimpleNamespace(id="student-1", email="student@example.test")

        def set_test_user(_request, _session_id):
            _request.state.profile = profile
            _request.state.user = user
            _request.state.supabase = object()
            return profile

        page = {
            "key": "attendance",
            "title": "Attendance",
            "summary": "Live information from Supabase.",
            "metrics": [],
            "columns": ["Course"],
            "rows": [["Live course"]],
            "form_fields": [],
            "extra_forms": [{
                "title": "Schedule an exam",
                "action": "add-exam",
                "ready": True,
                "fields": [{"name": "title", "label": "Exam name", "type": "text"}],
            }],
            "extra_tables": [{
                "title": "Scheduled exams",
                "columns": ["Exam"],
                "rows": [["Midterm"]],
            }],
        }
        with patch.object(app_module, "_set_authenticated_user", side_effect=set_test_user):
            with patch.object(app_module, "build_live_page", return_value=page):
                self._set_session(auth_session_id="test-session")
                response = self.client.get("/portal/student/attendance")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Live Supabase data", response.content)
        self.assertIn(b"Live course", response.content)
        self.assertIn(b"Schedule an exam", response.content)
        self.assertIn(b"Scheduled exams", response.content)
        self.assertEqual(response.content.count(b'class="table-search"'), 2)
        self.assertEqual(response.content.count(b'data-page-change='), 4)

    def test_student_feedback_submits_to_supabase_client(self):
        profile = {"id": "student-1", "role": "student", "full_name": "Live Student"}
        user = SimpleNamespace(id="student-1", email="student@example.test")
        database = FakeWriteClient()

        def set_test_user(_request, _session_id):
            _request.state.profile = profile
            _request.state.user = user
            _request.state.supabase = database
            return profile

        token = self._csrf()
        with patch.object(app_module, "_set_authenticated_user", side_effect=set_test_user):
            self._set_session(auth_session_id="test-session")
            response = self.client.post(
                "/portal/student/feedback",
                data={"csrf_token": token, "subject": "Test subject", "message": "Test message"},
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self._location(response), "/portal/student/feedback")
        self.assertEqual(database.writes, [{
            "student_id": "student-1",
            "request_type": "feedback",
            "subject": "Test subject",
            "message": "Test message",
        }])

    def test_admin_can_schedule_exam_in_supabase(self):
        profile = {"id": "admin-1", "role": "admin", "full_name": "Test Admin"}
        user = SimpleNamespace(id="admin-1", email="admin@example.test")
        database = FakeWriteClient({
            "courses": [{"id": 12, "is_sample": False}],
        })

        def set_test_user(_request, _session_id):
            _request.state.profile = profile
            _request.state.user = user
            _request.state.supabase = database
            return profile

        token = self._csrf()
        with patch.object(app_module, "_set_authenticated_user", side_effect=set_test_user):
            self._set_session(auth_session_id="test-session")
            response = self.client.post(
                "/portal/admin/courses",
                data={
                    "csrf_token": token,
                    "action": "add-exam",
                    "course_id": "12",
                    "title": "Midterm",
                    "exam_type": "midterm",
                    "starts_at": "2026-05-15T09:30",
                    "location": "Room 2",
                },
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self._location(response), "/portal/admin/courses")
        self.assertEqual(database.writes, [{
            "course_id": 12,
            "title": "Midterm",
            "exam_type": "midterm",
            "starts_at": "2026-05-15T09:30",
            "location": "Room 2",
        }])

    def test_admin_cannot_schedule_unofficial_sample_course(self):
        profile = {"id": "admin-1", "role": "admin", "full_name": "Test Admin"}
        user = SimpleNamespace(id="admin-1", email="admin@example.test")
        database = FakeWriteClient({
            "courses": [{
                "id": 12,
                "name": "Sample Security Foundations",
                "code": "SAMP-CYS-101",
                "department": "Computer Science",
                "credits": 3,
                "program": "BS Cyber Security Technology",
                "semester": 1,
                "is_sample": True,
            }],
            "departments": [{"name": "Computer Science"}],
        })

        def set_test_user(_request, _session_id):
            _request.state.profile = profile
            _request.state.user = user
            _request.state.supabase = database
            return profile

        token = self._csrf()
        with patch.object(app_module, "_set_authenticated_user", side_effect=set_test_user):
            self._set_session(auth_session_id="test-session")
            response = self.client.post(
                "/portal/admin/courses",
                data={
                    "csrf_token": token,
                    "action": "add-exam",
                    "course_id": "12",
                    "title": "Midterm",
                    "exam_type": "midterm",
                    "starts_at": "2026-05-15T09:30",
                    "location": "Room 2",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(database.writes, [])
        self.assertIn(b"cannot be scheduled, assigned, or enrolled", response.content)

    def test_admin_can_add_a_course_to_a_program_semester(self):
        profile = {"id": "admin-1", "role": "admin", "full_name": "Test Admin"}
        user = SimpleNamespace(id="admin-1", email="admin@example.test")
        database = FakeWriteClient({
            "departments": [{"name": "Computer Science"}],
        })

        def set_test_user(_request, _session_id):
            _request.state.profile = profile
            _request.state.user = user
            _request.state.supabase = database
            return profile

        token = self._csrf()
        with patch.object(app_module, "_set_authenticated_user", side_effect=set_test_user):
            self._set_session(auth_session_id="test-session")
            response = self.client.post(
                "/portal/admin/courses",
                data={
                    "csrf_token": token,
                    "action": "add-course",
                    "name": "Sample Secure Programming",
                    "code": "samp-cys-109",
                    "department": "Computer Science",
                    "credits": "3",
                    "program": "BS Cyber Security Technology",
                    "semester": "1",
                },
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(database.writes, [{
            "name": "Sample Secure Programming",
            "code": "SAMP-CYS-109",
            "department": "Computer Science",
            "credits": 3,
            "program": "BS Cyber Security Technology",
            "semester": 1,
        }])

    def test_admin_course_page_shows_unofficial_curriculum_entries(self):
        client = FakeReadClient({
            "courses": [{
                "id": 1,
                "name": "Programming Fundamentals",
                "code": "SAMP-CYS-101",
                "department": "Computer Science",
                "credits": 3,
                "program": "BS Cyber Security Technology",
                "semester": 1,
                "is_sample": True,
            }],
            "departments": [{"name": "Computer Science"}],
            "profiles": [],
        })

        page = build_live_page("admin", "courses", {"id": "admin-1"}, client)

        self.assertIn("Sample curriculum (unofficial)", page["rows"][0])
        self.assertIn("not official or complete Ziauddin study schemes", page["curriculum_note"])

    def test_admin_course_page_offers_synthetic_courses_for_demo_operations(self):
        client = FakeReadClient({
            "courses": [
                {"id": 1, "name": "Unofficial Sample", "code": "SAMP-1",
                 "department": "Computer Science", "credits": 3,
                 "is_sample": True, "is_demo": False},
                {"id": 2, "name": "Programming Fundamentals", "code": "DEMO-CYS-S01",
                 "department": "Computer Science", "credits": 3,
                 "program": "BS Cyber Security Technology", "semester": 1,
                 "is_sample": False, "is_demo": True},
            ],
            "departments": [{"name": "Computer Science"}],
            "profiles": [
                {"id": "teacher-1", "full_name": "Sample Teacher", "role": "teacher",
                 "is_demo": True},
                {"id": "student-1", "full_name": "Sample Student", "role": "student",
                 "student_number": "SAMPLE-1", "is_demo": True},
            ],
            "exams": [],
        })

        page = build_live_page("admin", "courses", {"id": "admin-1"}, client)

        self.assertIn("Synthetic presentation sample", page["rows"][1])
        self.assertEqual(page["extra_forms"][0]["ready"], True)
        self.assertEqual(page["extra_forms"][2]["ready"], True)
        self.assertEqual(page["extra_forms"][3]["ready"], True)
        self.assertIn("(synthetic sample)", page["extra_forms"][0]["fields"][0]["options"][0][1])
        self.assertIn("fictional", page["curriculum_note"])

    def test_admin_can_create_department_assigned_account(self):
        profile = {"id": "admin-1", "role": "admin", "full_name": "Test Admin"}
        user = SimpleNamespace(id="admin-1", email="admin@example.test")

        def set_test_user(_request, _session_id):
            _request.state.profile = profile
            _request.state.user = user
            _request.state.supabase = object()
            _request.state.access_token = "admin-access-token"
            return profile

        token = self._csrf()
        with patch.object(app_module, "_set_authenticated_user", side_effect=set_test_user):
            with patch.object(app_module, "_create_campus_account", return_value={"user_id": "new-user"}) as create_account:
                self._set_session(auth_session_id="test-session")
                response = self.client.post(
                    "/portal/admin/users",
                    data={
                        "csrf_token": token,
                        "action": "create-account",
                        "email": "student@example.test",
                        "password": "temporary-password",
                        "full_name": "New Student",
                        "username": "newstudent",
                        "role": "student",
                        "department": "Health Sciences",
                        "student_number": "STU-1001",
                        "program": "BS Software Engineering",
                        "semester": "2",
                    },
                )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self._location(response), "/portal/admin/users")
        create_account.assert_called_once_with({
            "email": "student@example.test",
            "password": "temporary-password",
            "full_name": "New Student",
            "username": "newstudent",
            "role": "student",
            "department": "Health Sciences",
            "student_number": "STU-1001",
            "program": "BS Software Engineering",
            "semester": "2",
        }, "admin-access-token")

    def test_admin_user_page_has_role_and_department_fields(self):
        client = FakeReadClient({
            "profiles": [
                {"id": "admin-1", "full_name": "Admin", "username": "admin1",
                 "role": "admin", "department": "Administration"},
                {"id": "student-1", "full_name": "Student", "username": "student1",
                 "role": "student", "department": "Computer Science",
                 "is_demo": True},
            ],
            "departments": [{"name": "Health Sciences"}],
        })

        page = build_live_page("admin", "users", {"id": "admin-1"}, client)

        self.assertEqual(page["table_title"], "Campus accounts")
        self.assertEqual(page["form_action"], "create-account")
        self.assertEqual(page["row_actions"], [None, "student-1"])
        self.assertEqual(page["row_action"], "delete-account")
        fields = {field["name"]: field for field in page["form_fields"]}
        self.assertIn(("hod", "HOD"), fields["role"]["options"])
        self.assertIn(("Health Sciences", "Health Sciences"), fields["department"]["options"])
        self.assertFalse(fields["student_number"]["required"])
        self.assertIn(
            ("BS Software Engineering", "BS Software Engineering"),
            fields["program"]["options"],
        )
        self.assertIn(("2", "Semester 2"), fields["semester"]["options"])
        self.assertIn("Synthetic sample", page["rows"][1])

    def test_demo_student_page_discloses_synthetic_data(self):
        page = build_live_page(
            "student",
            "profile",
            {
                "id": "student-1",
                "full_name": "Synthetic Student",
                "student_number": "DEMO-001",
                "department": "Computer Science",
                "program": "BS Software Engineering",
                "semester": 2,
                "is_demo": True,
            },
            FakeReadClient({}),
        )

        self.assertIn("synthetic presentation account", page["record_note"])

    def test_admin_user_page_loads_profiles_past_first_page(self):
        profiles = [
            {"id": f"student-{index}", "full_name": f"Student {index}",
             "username": f"student{index}", "role": "student",
             "department": "Computer Science", "student_number": f"STU-{index}"}
            for index in range(450)
        ]
        profiles.append({
            "id": "admin-1", "full_name": "Admin", "username": "admin1",
            "role": "admin", "department": "Administration",
        })
        client = FakeReadClient({
            "profiles": profiles,
            "departments": [{"name": "Computer Science"}],
        })

        page = build_live_page("admin", "users", {"id": "admin-1"}, client)

        self.assertEqual(len(page["rows"]), 451)
        self.assertEqual(len(page["row_actions"]), 451)

    def test_admin_users_route_renders_account_creation_form(self):
        profile = {"id": "admin-1", "role": "admin", "full_name": "Test Admin"}
        user = SimpleNamespace(id="admin-1", email="admin@example.test")
        database = FakeReadClient({
            "profiles": [
                {"id": "admin-1", "full_name": "Test Admin", "username": "admin1",
                 "role": "admin", "department": "Administration"},
                {"id": "student-1", "full_name": "Test Student", "username": "student1",
                 "role": "student", "department": "Computer Science"},
            ],
            "departments": [{"name": "Health Sciences"}],
        })

        def set_test_user(_request, _session_id):
            _request.state.profile = profile
            _request.state.user = user
            _request.state.supabase = database
            return profile

        with patch.object(app_module, "_set_authenticated_user", side_effect=set_test_user):
            self._set_session(auth_session_id="test-session")
            response = self.client.get("/portal/admin/users")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Create a campus account", response.content)
        self.assertIn(b"Health Sciences", response.content)
        self.assertIn(b"HOD", response.content)
        self.assertIn(b'name="student_number"', response.content)
        self.assertIn(b'name="program"', response.content)
        self.assertIn(b'name="semester"', response.content)
        self.assertIn(b'value="delete-account"', response.content)
        self.assertIn(b'value="student-1"', response.content)

    def test_admin_can_remove_non_admin_account(self):
        profile = {"id": "admin-1", "role": "admin", "full_name": "Test Admin"}
        user = SimpleNamespace(id="admin-1", email="admin@example.test")
        database = FakeReadClient({})

        def set_test_user(_request, _session_id):
            _request.state.profile = profile
            _request.state.user = user
            _request.state.supabase = database
            _request.state.access_token = "admin-access-token"
            return profile

        token = self._csrf()
        with patch.object(app_module, "_set_authenticated_user", side_effect=set_test_user):
            with patch.object(app_module, "_delete_campus_account", return_value={"deleted": True}) as delete_account:
                self._set_session(auth_session_id="test-session")
                response = self.client.post(
                    "/portal/admin/users",
                    data={
                        "csrf_token": token,
                        "action": "delete-account",
                        "profile_id": "12345678-1234-5678-1234-567812345678",
                    },
                )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self._location(response), "/portal/admin/users")
        delete_account.assert_called_once_with(
            "12345678-1234-5678-1234-567812345678",
            "admin-access-token",
        )

    def test_admin_cannot_remove_own_account(self):
        profile = {"id": "12345678-1234-5678-1234-567812345678", "role": "admin"}
        user = SimpleNamespace(id=profile["id"], email="admin@example.test")

        def set_test_user(_request, _session_id):
            _request.state.profile = profile
            _request.state.user = user
            _request.state.supabase = FakeReadClient({})
            _request.state.access_token = "admin-access-token"
            return profile

        token = self._csrf()
        with patch.object(app_module, "_set_authenticated_user", side_effect=set_test_user):
            with patch.object(app_module, "_delete_campus_account") as delete_account:
                self._set_session(auth_session_id="test-session")
                response = self.client.post(
                    "/portal/admin/users",
                    data={
                        "csrf_token": token,
                        "action": "delete-account",
                        "profile_id": profile["id"],
                    },
                )

        self.assertEqual(response.status_code, 200)
        delete_account.assert_not_called()
        self.assertIn(b"You cannot remove the account you are currently using", response.content)

    def test_admin_department_page_adds_departments(self):
        client = FakeReadClient({
            "departments": [{"name": "Health Sciences", "created_at": "2026-01-01T00:00:00Z"}],
        })

        page = build_live_page("admin", "departments", {"id": "admin-1"}, client)

        self.assertEqual(page["table_title"], "Departments")
        self.assertEqual(page["form_action"], "add-department")
        self.assertEqual(page["row_actions"], ["Health Sciences"])
        self.assertEqual(page["row_action"], "delete-department")
        self.assertEqual(page["form_fields"][0]["name"], "name")

    def test_admin_can_add_department(self):
        profile = {"id": "admin-1", "role": "admin", "full_name": "Test Admin"}
        user = SimpleNamespace(id="admin-1", email="admin@example.test")
        database = FakeWriteClient()

        def set_test_user(_request, _session_id):
            _request.state.profile = profile
            _request.state.user = user
            _request.state.supabase = database
            return profile

        token = self._csrf()
        with patch.object(app_module, "_set_authenticated_user", side_effect=set_test_user):
            self._set_session(auth_session_id="test-session")
            response = self.client.post(
                "/portal/admin/departments",
                data={"csrf_token": token, "action": "add-department", "name": "Clinical Psychology"},
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self._location(response), "/portal/admin/departments")
        self.assertEqual(database.writes, [{"name": "Clinical Psychology"}])

    def test_admin_can_remove_unused_department(self):
        profile = {"id": "admin-1", "role": "admin", "full_name": "Test Admin"}
        user = SimpleNamespace(id="admin-1", email="admin@example.test")
        database = FakeWriteClient()

        def set_test_user(_request, _session_id):
            _request.state.profile = profile
            _request.state.user = user
            _request.state.supabase = database
            return profile

        token = self._csrf()
        with patch.object(app_module, "_set_authenticated_user", side_effect=set_test_user):
            self._set_session(auth_session_id="test-session")
            response = self.client.post(
                "/portal/admin/departments",
                data={
                    "csrf_token": token,
                    "action": "delete-department",
                    "department_name": "Unused Department",
                },
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(database.writes, [{
            "delete": "departments",
            "filters": [("name", "Unused Department")],
        }])

    def test_admin_cannot_remove_department_with_accounts_or_courses(self):
        profile = {"id": "admin-1", "role": "admin", "full_name": "Test Admin"}
        user = SimpleNamespace(id="admin-1", email="admin@example.test")
        database = FakeWriteClient({
            "profiles": [{"id": "student-1"}],
        })

        def set_test_user(_request, _session_id):
            _request.state.profile = profile
            _request.state.user = user
            _request.state.supabase = database
            return profile

        token = self._csrf()
        with patch.object(app_module, "_set_authenticated_user", side_effect=set_test_user):
            self._set_session(auth_session_id="test-session")
            response = self.client.post(
                "/portal/admin/departments",
                data={
                    "csrf_token": token,
                    "action": "delete-department",
                    "department_name": "Computer Science",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(database.writes, [])
        self.assertIn(b"Reassign or remove them first", response.content)

    def test_student_exam_datasheet_uses_enrolled_course_exams(self):
        client = FakeReadClient({
            "enrollments": [{"student_id": "student-1", "course_id": 7, "term": "Spring"}],
            "courses": [{"id": 7, "name": "Biology"}],
            "exams": [{
                "course_id": 7,
                "title": "Midterm",
                "exam_type": "midterm",
                "starts_at": "2026-05-15T09:30:00+00:00",
                "location": "Room 2",
            }],
        })

        page = build_live_page("student", "datasheet", {"id": "student-1"}, client)

        self.assertEqual(page["table_title"], "Exam datasheet")
        self.assertEqual(page["rows"], [["Biology", "Midterm", "Midterm", "15 May 2026 09:30", "Room 2"]])

    def test_filtered_portal_reads_include_all_matching_rows(self):
        rows = [{"id": index, "owner": "student-1"} for index in range(450)]
        rows.extend({"id": 1000 + index, "owner": "another-student"} for index in range(20))
        client = FakeReadClient({"records": rows})

        owned_rows = _where(client, "records", "owner", "student-1")
        selected_rows = _in(client, "records", "id", list(range(450)))

        self.assertEqual(len(owned_rows), 450)
        self.assertEqual(len(selected_rows), 450)
        self.assertTrue(all(row["owner"] == "student-1" for row in owned_rows))

    def test_student_attendance_reads_more_than_one_api_page(self):
        sessions = [
            {"id": index, "course_id": 7, "starts_at": "2026-01-01T09:00:00Z"}
            for index in range(450)
        ]
        attendance = [
            {"session_id": index, "student_id": "student-1", "status": "present"}
            for index in range(450)
        ]
        client = FakeReadClient({
            "enrollments": [{"student_id": "student-1", "course_id": 7}],
            "courses": [{"id": 7, "name": "Software Engineering", "code": "SE101"}],
            "class_sessions": sessions,
            "attendance_records": attendance,
        })

        page = build_live_page("student", "attendance", {"id": "student-1"}, client)

        self.assertEqual(len(page["rows"]), 450)

    def test_student_teacher_and_hod_portals_render_live_role_data(self):
        portal_cases = [
            (
                {"id": "student-1", "role": "student", "full_name": "Test Student"},
                {"enrollments": [{"student_id": "student-1", "course_id": 7}],
                 "courses": [{"id": 7, "name": "Software Engineering", "code": "SE101", "credits": 3}],
                 "class_sessions": [{"id": 3, "course_id": 7, "starts_at": "2026-01-01T09:00:00Z",
                                     "location": "Room 1"}]},
                "/portal/student/dashboard",
                "Software Engineering",
            ),
            (
                {"id": "teacher-1", "role": "teacher", "full_name": "Test Teacher"},
                {"course_staff": [{"profile_id": "teacher-1", "course_id": 7}],
                 "courses": [{"id": 7, "name": "Software Engineering", "code": "SE101", "credits": 3}],
                 "enrollments": [{"student_id": "student-1", "course_id": 7}],
                 "profiles": [{"id": "student-1", "full_name": "Test Student", "student_number": "S-001"}]},
                "/portal/teacher/dashboard",
                "Software Engineering",
            ),
            (
                {"id": "hod-1", "role": "hod", "full_name": "Test HOD", "department": "Software Engineering"},
                {"courses": [{"id": 7, "name": "Software Engineering", "code": "SE101",
                              "credits": 3, "department": "Software Engineering"}],
                 "enrollments": [{"course_id": 7, "student_id": "student-1"}]},
                "/portal/hod/dashboard",
                "Software Engineering",
            ),
        ]

        for profile, tables, path, expected_course in portal_cases:
            with self.subTest(role=profile["role"]):
                user = SimpleNamespace(id=profile["id"], email=f'{profile["role"]}@example.test')
                client = FakeReadClient(tables)

                def set_test_user(_request, _session_id):
                    _request.state.profile = profile
                    _request.state.user = user
                    _request.state.supabase = client
                    return profile

                with patch.object(app_module, "_set_authenticated_user", side_effect=set_test_user):
                    self._set_session(auth_session_id=f'test-{profile["role"]}')
                    response = self.client.get(path)

                self.assertEqual(response.status_code, 200)
                self.assertIn(expected_course.encode(), response.content)
                self.assertIn(b"table-page-status", response.content)
                self.assertIn(b"portal-tables.js", response.content)

    def test_teacher_attendance_form_loads_assigned_students_and_sessions(self):
        client = FakeReadClient({
            "course_staff": [{"profile_id": "teacher-1", "course_id": 7}],
            "courses": [{"id": 7, "name": "Software Engineering", "code": "SE101"}],
            "class_sessions": [{"id": 3, "course_id": 7, "starts_at": "2026-01-01T09:00:00Z"}],
            "enrollments": [{"student_id": "student-1", "course_id": 7}],
            "profiles": [{"id": "student-1", "full_name": "Test Student", "student_number": "S-001"}],
        })

        page = build_live_page("teacher", "attendance-entry", {"id": "teacher-1"}, client)

        self.assertTrue(page["form_ready"])
        self.assertEqual(page["form_action"], "attendance-entry")
        self.assertEqual(page["form_fields"][1]["options"][0][0], "3")
        self.assertEqual(page["form_fields"][2]["options"][0][0], "student-1")

    def test_hod_department_overview_shows_matching_course_and_enrollment_counts(self):
        client = FakeReadClient({
            "courses": [{
                "id": 7,
                "name": "Software Requirements Engineering",
                "code": "DEMO-SE-S05",
                "credits": 3,
                "department": "Software Engineering",
            }],
            "enrollments": [
                {"course_id": 7, "student_id": f"student-{number}"}
                for number in range(40)
            ],
        })

        page = build_live_page(
            "hod",
            "department",
            {"id": "hod-1", "department": "Software Engineering"},
            client,
        )

        self.assertEqual(page["rows"], [["Software Requirements Engineering", "DEMO-SE-S05", 3]])
        self.assertEqual(page["metrics"], [("Department courses", "1"), ("Enrollments", "40")])

    def test_hod_with_no_matching_courses_gets_department_specific_explanation(self):
        page = build_live_page(
            "hod",
            "department",
            {"id": "hod-1", "department": "Software Engineering"},
            FakeReadClient({"courses": []}),
        )

        self.assertIn("Software Engineering department", page["record_note"])
        self.assertIn("same department name", page["record_note"])


if __name__ == "__main__":
    unittest.main()
