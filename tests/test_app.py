import re
import time
import unittest
import os
from types import SimpleNamespace
from urllib.error import HTTPError
from io import BytesIO
from unittest.mock import MagicMock, patch

from flask import g

import app as app_module
from auth_sessions import delete_session
from portal_data import build_live_page


class FakeQuery:
    def __init__(self, result):
        self.result = result

    def select(self, _columns):
        return self

    def eq(self, _column, _value):
        return self

    def limit(self, _count):
        return self

    def execute(self):
        return SimpleNamespace(data=self.result)


class FakeTableClient:
    def __init__(self, profile):
        self.profile = profile

    def table(self, _name):
        return FakeQuery([self.profile])


class FakeWriteQuery:
    def __init__(self, writes):
        self.writes = writes

    def insert(self, payload):
        self.writes.append(payload)
        return self

    def upsert(self, payload, **_kwargs):
        self.writes.append(payload)
        return self

    def select(self, _columns):
        return self

    def eq(self, _column, _value):
        return self

    def limit(self, _count):
        return self

    def execute(self):
        return SimpleNamespace(data=[])


class FakeWriteClient:
    def __init__(self):
        self.writes = []

    def table(self, _name):
        return FakeWriteQuery(self.writes)


class FakeReadQuery:
    def __init__(self, rows):
        self.rows = rows
        self.filters = []

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

    def execute(self):
        rows = [
            row for row in self.rows
            if all(row.get(column) == value if not isinstance(value, list) else row.get(column) in value
                   for column, value in self.filters)
        ]
        return SimpleNamespace(data=rows)


class FakeReadClient:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return FakeReadQuery(self.tables.get(name, []))


class PortalAppTests(unittest.TestCase):
    def setUp(self):
        app_module.app.config.update(TESTING=True, SECRET_KEY="test-secret")
        self.client = app_module.app.test_client()

    def _csrf(self):
        response = self.client.get("/")
        match = re.search(rb'name="csrf_token" value="([^"]+)"', response.data)
        self.assertIsNotNone(match)
        return match.group(1).decode()

    def test_login_page_offers_email_and_username_without_role_choice(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'name="login_method"', response.data)
        self.assertIn(b'value="email">Email', response.data)
        self.assertIn(b'value="username">Username', response.data)
        self.assertNotIn(b'data-role=', response.data)

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

    def test_portal_requires_authentication(self):
        response = self.client.get("/portal/student/dashboard")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/")

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
        self.assertEqual(response.location, "/portal/teacher/dashboard")
        cookie = self.client.get_cookie(app_module.app.config["SESSION_COOKIE_NAME"])
        self.assertIsNotNone(cookie)
        self.assertNotIn("access-secret-token", cookie.value)
        self.assertNotIn("refresh-secret-token", cookie.value)
        with self.client.session_transaction() as browser_session:
            delete_session(browser_session.get("auth_session_id"))

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
        self.assertEqual(response.location, "/portal/teacher/dashboard")
        lookup.assert_not_called()
        with self.client.session_transaction() as browser_session:
            delete_session(browser_session.get("auth_session_id"))

    def test_user_cannot_open_a_different_role_portal(self):
        profile = {"id": "teacher-1", "role": "teacher", "full_name": "Teacher"}
        user = SimpleNamespace(id="teacher-1", email="teacher@example.test")

        def set_test_user(_session_id):
            g.profile = profile
            g.user = user
            g.supabase = None
            return profile

        with patch.object(app_module, "_set_authenticated_user", side_effect=set_test_user):
            with self.client.session_transaction() as browser_session:
                browser_session["auth_session_id"] = "test-session"
            response = self.client.get("/portal/admin/dashboard")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/portal/teacher/dashboard")

    def test_portal_renders_live_data(self):
        profile = {"id": "student-1", "role": "student", "full_name": "Live Student"}
        user = SimpleNamespace(id="student-1", email="student@example.test")

        def set_test_user(_session_id):
            g.profile = profile
            g.user = user
            g.supabase = object()
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
                with self.client.session_transaction() as browser_session:
                    browser_session["auth_session_id"] = "test-session"
                response = self.client.get("/portal/student/attendance")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Live Supabase data", response.data)
        self.assertIn(b"Live course", response.data)
        self.assertIn(b"Schedule an exam", response.data)
        self.assertIn(b"Scheduled exams", response.data)

    def test_student_feedback_submits_to_supabase_client(self):
        profile = {"id": "student-1", "role": "student", "full_name": "Live Student"}
        user = SimpleNamespace(id="student-1", email="student@example.test")
        database = FakeWriteClient()

        def set_test_user(_session_id):
            g.profile = profile
            g.user = user
            g.supabase = database
            return profile

        token = self._csrf()
        with patch.object(app_module, "_set_authenticated_user", side_effect=set_test_user):
            with self.client.session_transaction() as browser_session:
                browser_session["auth_session_id"] = "test-session"
            response = self.client.post(
                "/portal/student/feedback",
                data={"csrf_token": token, "subject": "Test subject", "message": "Test message"},
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/portal/student/feedback")
        self.assertEqual(database.writes, [{
            "student_id": "student-1",
            "request_type": "feedback",
            "subject": "Test subject",
            "message": "Test message",
        }])

    def test_admin_can_schedule_exam_in_supabase(self):
        profile = {"id": "admin-1", "role": "admin", "full_name": "Test Admin"}
        user = SimpleNamespace(id="admin-1", email="admin@example.test")
        database = FakeWriteClient()

        def set_test_user(_session_id):
            g.profile = profile
            g.user = user
            g.supabase = database
            return profile

        token = self._csrf()
        with patch.object(app_module, "_set_authenticated_user", side_effect=set_test_user):
            with self.client.session_transaction() as browser_session:
                browser_session["auth_session_id"] = "test-session"
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
        self.assertEqual(response.location, "/portal/admin/courses")
        self.assertEqual(database.writes, [{
            "course_id": 12,
            "title": "Midterm",
            "exam_type": "midterm",
            "starts_at": "2026-05-15T09:30",
            "location": "Room 2",
        }])

    def test_admin_can_create_department_assigned_account(self):
        profile = {"id": "admin-1", "role": "admin", "full_name": "Test Admin"}
        user = SimpleNamespace(id="admin-1", email="admin@example.test")

        def set_test_user(_session_id):
            g.profile = profile
            g.user = user
            g.supabase = object()
            g.access_token = "admin-access-token"
            return profile

        token = self._csrf()
        with patch.object(app_module, "_set_authenticated_user", side_effect=set_test_user):
            with patch.object(app_module, "_create_campus_account", return_value={"user_id": "new-user"}) as create_account:
                with self.client.session_transaction() as browser_session:
                    browser_session["auth_session_id"] = "test-session"
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
                    },
                )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/portal/admin/users")
        create_account.assert_called_once_with({
            "email": "student@example.test",
            "password": "temporary-password",
            "full_name": "New Student",
            "username": "newstudent",
            "role": "student",
            "department": "Health Sciences",
            "student_number": "STU-1001",
        }, "admin-access-token")

    def test_admin_user_page_has_role_and_department_fields(self):
        client = FakeReadClient({
            "profiles": [{"id": "admin-1", "full_name": "Admin", "username": "admin1",
                          "role": "admin", "department": "Administration"}],
            "departments": [{"name": "Health Sciences"}],
        })

        page = build_live_page("admin", "users", {"id": "admin-1"}, client)

        self.assertEqual(page["table_title"], "Campus accounts")
        self.assertEqual(page["form_action"], "create-account")
        fields = {field["name"]: field for field in page["form_fields"]}
        self.assertIn(("hod", "HOD"), fields["role"]["options"])
        self.assertIn(("Health Sciences", "Health Sciences"), fields["department"]["options"])
        self.assertFalse(fields["student_number"]["required"])

    def test_admin_users_route_renders_account_creation_form(self):
        profile = {"id": "admin-1", "role": "admin", "full_name": "Test Admin"}
        user = SimpleNamespace(id="admin-1", email="admin@example.test")
        database = FakeReadClient({
            "profiles": [{"id": "admin-1", "full_name": "Test Admin", "username": "admin1",
                          "role": "admin", "department": "Administration"}],
            "departments": [{"name": "Health Sciences"}],
        })

        def set_test_user(_session_id):
            g.profile = profile
            g.user = user
            g.supabase = database
            return profile

        with patch.object(app_module, "_set_authenticated_user", side_effect=set_test_user):
            with self.client.session_transaction() as browser_session:
                browser_session["auth_session_id"] = "test-session"
            response = self.client.get("/portal/admin/users")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Create a campus account", response.data)
        self.assertIn(b"Health Sciences", response.data)
        self.assertIn(b"HOD", response.data)
        self.assertIn(b'name="student_number"', response.data)

    def test_admin_department_page_adds_departments(self):
        client = FakeReadClient({
            "departments": [{"name": "Health Sciences", "created_at": "2026-01-01T00:00:00Z"}],
        })

        page = build_live_page("admin", "departments", {"id": "admin-1"}, client)

        self.assertEqual(page["table_title"], "Departments")
        self.assertEqual(page["form_action"], "add-department")
        self.assertEqual(page["form_fields"][0]["name"], "name")

    def test_admin_can_add_department(self):
        profile = {"id": "admin-1", "role": "admin", "full_name": "Test Admin"}
        user = SimpleNamespace(id="admin-1", email="admin@example.test")
        database = FakeWriteClient()

        def set_test_user(_session_id):
            g.profile = profile
            g.user = user
            g.supabase = database
            return profile

        token = self._csrf()
        with patch.object(app_module, "_set_authenticated_user", side_effect=set_test_user):
            with self.client.session_transaction() as browser_session:
                browser_session["auth_session_id"] = "test-session"
            response = self.client.post(
                "/portal/admin/departments",
                data={"csrf_token": token, "action": "add-department", "name": "Clinical Psychology"},
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/portal/admin/departments")
        self.assertEqual(database.writes, [{"name": "Clinical Psychology"}])

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


if __name__ == "__main__":
    unittest.main()
