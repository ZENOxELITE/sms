import json
import logging
import os
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request as URLRequest, urlopen
from uuid import UUID

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import pass_context
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from auth_sessions import delete_session, get_session, save_session, update_session
from portal_data import CURRICULUM_PROGRAMS, build_live_page
from supabase_client import create_supabase_client, get_supabase_client

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(BASE_DIR, ".env"))

logger = logging.getLogger("sms")
app = FastAPI(title="Student Management System")
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("FLASK_SECRET_KEY", "development-only-change-me"),
    session_cookie="session",
    same_site="lax",
    https_only=os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true",
)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

PORTALS = {
    "student": {
        "label": "Student",
        "name": "Aman Ahmed Sheikh",
        "identifier": "IU2-0324-972",
        "faculty": "Faculty of Business Administration",
        "navigation": [
            ("dashboard", "Dashboard"), ("profile", "Profile"),
            ("attendance", "Attendance"), ("results", "Results & Exams"),
            ("datasheet", "Exam Datasheet"), ("notifications", "Notifications"),
            ("feedback", "Feedback"), ("timetable", "Time Table"),
            ("invoices", "Invoices"), ("complaints", "Complaints"),
        ],
    },
    "teacher": {
        "label": "Teacher",
        "name": "Hira Farman",
        "identifier": "Faculty account",
        "faculty": "Faculty of Business Administration",
        "navigation": [
            ("dashboard", "Dashboard"), ("classes", "Classes"),
            ("attendance-entry", "Attendance Entry"), ("results-entry", "Results Entry"),
        ],
    },
    "hod": {
        "label": "HOD",
        "name": "Department Head",
        "identifier": "HOD account",
        "faculty": "Faculty of Business Administration",
        "navigation": [
            ("dashboard", "Dashboard"), ("department", "Department Overview"),
            ("review", "Class & Result Review"),
        ],
    },
    "admin": {
        "label": "Admin",
        "name": "System Administrator",
        "identifier": "Administrator account",
        "faculty": "Campus administration",
        "navigation": [
            ("dashboard", "Dashboard"), ("users", "Students & Staff"),
            ("departments", "Departments"), ("courses", "Courses & Classes"),
            ("announcements", "Announcements"),
        ],
    },
}


@pass_context
def get_flashed_messages(context, with_categories=False):
    request = context.get("request")
    if request is None:
        return []
    messages = request.session.pop("_flashes", [])
    if with_categories:
        return messages
    return [message for _category, message in messages]


templates.env.globals["get_flashed_messages"] = get_flashed_messages


def flash(request, message, category="message"):
    messages = request.session.setdefault("_flashes", [])
    messages.append((category, str(message)))


def _csrf_token(request):
    request.session.setdefault("csrf_token", secrets.token_urlsafe(32))
    return request.session["csrf_token"]


def _verify_csrf(request, form):
    expected = request.session.get("csrf_token")
    supplied = form.get("csrf_token") or request.headers.get("X-CSRF-Token")
    if not expected or not supplied or not secrets.compare_digest(str(expected), str(supplied)):
        raise HTTPException(
            status_code=400,
            detail="The form expired. Reload the page and try again.",
        )


def _redirect(request, endpoint, status_code=302, **path_params):
    return RedirectResponse(
        request.url_for(endpoint, **path_params),
        status_code=status_code,
    )


def _login_page(request):
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"csrf_token": _csrf_token(request)},
    )


def _set_authenticated_user(request, session_id):
    auth_session = get_session(session_id)
    if not auth_session:
        return None
    try:
        auth_client = create_supabase_client()
        expires_at = int(auth_session["expires_at"])
        if expires_at <= int(time.time()) + 60:
            refreshed = auth_client.auth.refresh_session(str(auth_session["refresh_token"]))
            refreshed_session = refreshed.session
            if not refreshed_session:
                delete_session(session_id)
                return None
            access_token = refreshed_session.access_token
            refresh_token = refreshed_session.refresh_token
            expires_at = int(
                refreshed_session.expires_at
                or time.time() + refreshed_session.expires_in
            )
            update_session(session_id, access_token, refresh_token, expires_at)
        else:
            access_token = str(auth_session["access_token"])
        user_id = str(auth_session["user_id"])
        profile_client = create_supabase_client(access_token)
        with ThreadPoolExecutor(max_workers=2) as executor:
            user_future = executor.submit(auth_client.auth.get_user, access_token)
            profile_future = executor.submit(
                lambda: profile_client.table("profiles")
                .select("*")
                .eq("id", user_id)
                .limit(1)
                .execute()
            )
            user_response = user_future.result()
            profile_response = profile_future.result()
        user = user_response.user if user_response else None
        if not user or str(user.id) != user_id:
            delete_session(session_id)
            return None
        profile = profile_response.data[0] if profile_response.data else None
        if not profile or profile.get("role") not in PORTALS:
            delete_session(session_id)
            return None
        request.state.user = user
        request.state.profile = profile
        request.state.supabase = profile_client
        request.state.access_token = access_token
        return profile
    except Exception:
        logger.exception("Could not validate the current Supabase session.")
        delete_session(session_id)
        return None


def _current_portal(request):
    profile = request.state.profile
    role = profile["role"]
    portal = PORTALS[role].copy()
    portal["name"] = profile.get("full_name") or request.state.user.email or portal["name"]
    portal["identifier"] = profile.get("student_number") or portal["identifier"]
    portal["faculty"] = profile.get("department") or portal["faculty"]
    return role, portal


def _resolve_login_email(username):
    supabase_url = os.getenv("SUPABASE_URL")
    anon_key = os.getenv("SUPABASE_ANON_KEY")
    lookup_secret = os.getenv("SUPABASE_USERNAME_LOOKUP_SECRET")
    if not supabase_url or not anon_key or not lookup_secret:
        raise RuntimeError("Username sign-in is not configured.")
    request_body = json.dumps({"username": username.strip().lower()}).encode("utf-8")
    lookup_request = URLRequest(
        f"{supabase_url.rstrip('/')}/functions/v1/username-lookup",
        data=request_body,
        headers={
            "apikey": anon_key,
            "Authorization": f"Bearer {anon_key}",
            "Content-Type": "application/json",
            "X-Username-Lookup-Secret": lookup_secret,
        },
        method="POST",
    )
    lookup_request.add_header("Authorization", f"Bearer {anon_key}")
    try:
        with urlopen(lookup_request, timeout=10) as response:
            result = json.loads(response.read())
    except HTTPError as error:
        if error.code == 401:
            raise RuntimeError(
                "Username lookup rejected its shared secret. Make sure SUPABASE_USERNAME_LOOKUP_SECRET "
                "in .env matches the Supabase USERNAME_LOOKUP_SECRET function secret."
            ) from error
        raise RuntimeError(f"Username lookup failed with HTTP {error.code}.") from error
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError("Username lookup request failed.") from error
    email = result.get("email") if isinstance(result, dict) else None
    return email if isinstance(email, str) and email else None


def _function_error_message(error):
    try:
        result = json.loads(error.read())
    except (json.JSONDecodeError, UnicodeDecodeError):
        result = {}
    if not isinstance(result, dict):
        return None
    message = result.get("error")
    if not isinstance(message, str) or not message.strip():
        message = result.get("message")
    return message.strip() if isinstance(message, str) and message.strip() else None


def _create_campus_account(payload, access_token):
    supabase_url = os.getenv("SUPABASE_URL")
    anon_key = os.getenv("SUPABASE_ANON_KEY")
    missing_settings = [
        name for name, value in (
            ("SUPABASE_URL", supabase_url),
            ("SUPABASE_ANON_KEY", anon_key),
        ) if not value
    ]
    if missing_settings:
        raise RuntimeError(
            "Supabase account creation is not configured. Set "
            + " and ".join(missing_settings)
            + " in the .env file beside app.py, then restart FastAPI."
        )
    if not isinstance(access_token, str) or not access_token.strip():
        raise RuntimeError("A signed-in Supabase session is required to create accounts.")
    function_request = URLRequest(
        f"{supabase_url.rstrip('/')}/functions/v1/admin-create-account",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "apikey": anon_key,
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    function_request.add_header("Authorization", f"Bearer {access_token}")
    function_request.add_header("X-Supabase-User-Access-Token", access_token)
    try:
        with urlopen(function_request, timeout=20) as response:
            result = json.loads(response.read())
    except HTTPError as error:
        message = _function_error_message(error)
        raise RuntimeError(
            message or f"Account creation failed with HTTP {error.code}."
        ) from error
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError("Could not reach the account-creation function.") from error
    if not isinstance(result, dict) or not result.get("user_id"):
        raise RuntimeError("The account-creation function returned an invalid response.")
    return result


def _delete_campus_account(profile_id, access_token):
    supabase_url = os.getenv("SUPABASE_URL")
    anon_key = os.getenv("SUPABASE_ANON_KEY")
    if not supabase_url or not anon_key:
        raise RuntimeError("Supabase account removal is not configured.")
    if not isinstance(access_token, str) or not access_token.strip():
        raise RuntimeError("A signed-in Supabase session is required to remove accounts.")
    function_request = URLRequest(
        f"{supabase_url.rstrip('/')}/functions/v1/admin-delete-account",
        data=json.dumps({"profile_id": profile_id}).encode("utf-8"),
        headers={
            "apikey": anon_key,
            "Authorization": f"******",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    function_request.add_header("Authorization", f"Bearer {access_token}")
    function_request.add_header("X-Supabase-User-Access-Token", access_token)
    try:
        with urlopen(function_request, timeout=20) as response:
            result = json.loads(response.read())
    except HTTPError as error:
        message = _function_error_message(error)
        raise RuntimeError(
            message or f"Account removal failed with HTTP {error.code}."
        ) from error
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError("Could not reach the account-removal function.") from error
    if not isinstance(result, dict) or result.get("deleted") is not True:
        raise RuntimeError("The account-removal function returned an invalid response.")
    return result


def _require_active_course(client, course_id):
    courses = client.table("courses").select("id,is_sample,is_demo").eq(
        "id", course_id
    ).limit(1).execute().data
    if not courses:
        raise ValueError("Choose a course from the course list.")
    if courses[0].get("is_sample"):
        raise ValueError(
            "Unofficial sample curriculum entries cannot be scheduled, assigned, or enrolled."
        )


def _authenticate_credentials(email, password):
    auth_client = create_supabase_client()
    response = auth_client.auth.sign_in_with_password({"email": email, "password": password})
    if not response.user or not response.session:
        return None
    expires_at = int(
        response.session.expires_at
        or time.time() + response.session.expires_in
    )
    return (
        response.user,
        save_session(
            response.session.access_token,
            response.session.refresh_token,
            expires_at,
            str(response.user.id),
        ),
    )


@app.get("/", name="login")
async def login(request: Request):
    profile = await run_in_threadpool(
        _set_authenticated_user,
        request,
        request.session.get("auth_session_id"),
    )
    if profile:
        role = profile["role"]
        return _redirect(request, "portal_page", 302, role=role, section="dashboard")
    return _login_page(request)


@app.post("/login", name="login_submit")
async def login_submit(request: Request):
    form = await request.form()
    _verify_csrf(request, form)
    login_method = str(form.get("login_method", "")).strip().lower()
    identifier = str(form.get("identifier", "")).strip()
    password = str(form.get("password", ""))
    if login_method not in {"email", "username"} or not identifier or not password:
        flash(request, "Choose email or username, then enter your account name and password.", "error")
        return _redirect(request, "login")
    if login_method == "email":
        email = identifier.lower()
    else:
        try:
            email = await run_in_threadpool(_resolve_login_email, identifier)
        except RuntimeError as error:
            logger.exception("Username lookup is not available.")
            flash(request, str(error), "error")
            return _redirect(request, "login")
    if not email:
        flash(request, "Username or password is incorrect.", "error")
        return _redirect(request, "login")
    try:
        result = await run_in_threadpool(_authenticate_credentials, email, password)
        if not result:
            flash(
                request,
                "Sign-in did not return an active session. Check your account and email confirmation.",
                "error",
            )
            return _redirect(request, "login")
        user, session_id = result
        request.session.clear()
        request.session["auth_session_id"] = session_id
        request.session["csrf_token"] = secrets.token_urlsafe(32)
        profile = await run_in_threadpool(_set_authenticated_user, request, session_id)
        if not profile:
            request.session.clear()
            flash(
                request,
                "Your account needs a campus profile. Ask an administrator to finish setting it up.",
                "error",
            )
            return _redirect(request, "login")
        return _redirect(
            request, "portal_page", role=profile["role"], section="dashboard"
        )
    except Exception:
        logger.exception("Supabase sign-in failed.")
        flash(
            request,
            "Sign-in failed. Check your email or username and password, then try again.",
            "error",
        )
        return _redirect(request, "login")


@app.post("/password-reset", name="password_reset")
async def password_reset(request: Request):
    form = await request.form()
    _verify_csrf(request, form)
    email = str(form.get("email", "")).strip().lower()
    if not email:
        flash(request, "Enter your account email to request a reset link.", "error")
        return _redirect(request, "login")
    try:
        await run_in_threadpool(
            lambda: create_supabase_client().auth.reset_password_email(email)
        )
    except Exception:
        logger.exception("Supabase password reset request failed.")
        flash(request, "Could not request a password reset. Please try again later.", "error")
        return _redirect(request, "login")
    flash(request, "If the account exists, Supabase will send a password reset email.", "success")
    return _redirect(request, "login")


@app.post("/logout", name="logout")
async def logout(request: Request):
    form = await request.form()
    _verify_csrf(request, form)
    delete_session(request.session.get("auth_session_id"))
    request.session.clear()
    flash(request, "You have signed out.", "success")
    return _redirect(request, "login")


@app.get("/dashboard", name="dashboard")
async def dashboard(request: Request):
    return _redirect(request, "portal_page", 302, role="student", section="dashboard")


@app.get("/portal/{role}", name="portal_home")
async def portal_home(request: Request, role: str):
    profile = await run_in_threadpool(
        _set_authenticated_user,
        request,
        request.session.get("auth_session_id"),
    )
    if not profile:
        request.session.pop("auth_session_id", None)
        flash(request, "Please sign in with an active campus account.", "error")
        return _redirect(request, "login")
    current_role = profile["role"]
    if role != current_role:
        return _redirect(
            request, "portal_page", 302, role=current_role, section="dashboard"
        )
    if role not in PORTALS:
        raise HTTPException(status_code=404)
    return _redirect(
        request, "portal_page", 302, role=role, section="dashboard"
    )


def _handle_portal_post(request, role, section, form):
    profile = request.state.profile
    user = request.state.user
    client = request.state.supabase
    access_token = getattr(request.state, "access_token", None)
    if section in ("feedback", "complaints") and role == "student":
        subject = str(form.get("subject", "")).strip()
        message = str(form.get("message", "")).strip()
        if not subject or not message:
            raise ValueError("Enter a subject and message.")
        client.table("student_requests").insert({
            "student_id": str(user.id),
            "request_type": "feedback" if section == "feedback" else "complaint",
            "subject": subject,
            "message": message,
        }).execute()
        return "Your request was saved."
    if role == "teacher" and section == "attendance-entry":
        client.table("attendance_records").upsert({
            "session_id": int(form.get("session_id", "")),
            "student_id": form.get("student_id", ""),
            "marked_by": str(user.id),
            "status": form.get("status", ""),
        }, on_conflict="session_id,student_id").execute()
        return "Attendance was saved."
    if role == "teacher" and section == "results-entry":
        grade = str(form.get("grade", "")).strip()
        term = str(form.get("term", "")).strip()
        if not grade or not term:
            raise ValueError("Enter a grade and term.")
        client.table("grades").upsert({
            "course_id": int(form.get("course_id", "")),
            "student_id": form.get("student_id", ""),
            "grade": grade,
            "term": term,
            "published": False,
        }, on_conflict="course_id,student_id,term").execute()
        return "The grade was saved as unpublished."
    if role == "admin" and section == "courses":
        action = form.get("action")
        if action == "add-course":
            credits = int(form.get("credits", ""))
            name = str(form.get("name", "")).strip()
            code = str(form.get("code", "")).strip().upper()
            department = str(form.get("department", "")).strip()
            program = str(form.get("program", "")).strip()
            semester_value = str(form.get("semester", "")).strip()
            if credits < 1 or not name or not code or not department:
                raise ValueError("Enter a course name, code, department, and positive credit count.")
            if program and program not in CURRICULUM_PROGRAMS:
                raise ValueError("Choose a department from the program list.")
            if program and not semester_value:
                raise ValueError("Choose a semester for a program course.")
            if semester_value and not program:
                raise ValueError("Choose a program before selecting a semester.")
            try:
                semester = int(semester_value) if semester_value else None
            except ValueError as error:
                raise ValueError("Choose a semester between 1 and 8.") from error
            if semester is not None and not 1 <= semester <= 8:
                raise ValueError("Choose a semester between 1 and 8.")
            allowed_departments = client.table("departments").select("name").eq(
                "name", department
            ).limit(1).execute().data
            if not allowed_departments:
                raise ValueError("Choose a department from the department list.")
            client.table("courses").insert({
                "name": name,
                "code": code,
                "department": department,
                "credits": credits,
                "program": program or None,
                "semester": semester,
            }).execute()
            return "The course was added."
        if action == "add-session":
            course_id = int(form.get("course_id", ""))
            _require_active_course(client, course_id)
            values = {
                "course_id": course_id,
                "starts_at": str(form.get("starts_at", "")).strip(),
                "ends_at": str(form.get("ends_at", "")).strip(),
                "location": str(form.get("location", "")).strip(),
            }
            if not all(values.values()):
                raise ValueError("Complete all class session fields.")
            try:
                starts_at = datetime.fromisoformat(values["starts_at"])
                ends_at = datetime.fromisoformat(values["ends_at"])
            except ValueError as error:
                raise ValueError("Enter valid class start and end times.") from error
            if ends_at <= starts_at:
                raise ValueError("The class end time must be after its start time.")
            client.table("class_sessions").insert(values).execute()
            return "The class session was scheduled."
        if action == "add-exam":
            course_id = int(form.get("course_id", ""))
            _require_active_course(client, course_id)
            exam = {
                "course_id": course_id,
                "title": str(form.get("title", "")).strip(),
                "exam_type": str(form.get("exam_type", "")).strip(),
                "starts_at": str(form.get("starts_at", "")).strip(),
                "location": str(form.get("location", "")).strip(),
            }
            if not all(exam.values()):
                raise ValueError("Complete all exam details.")
            try:
                datetime.fromisoformat(exam["starts_at"])
            except ValueError as error:
                raise ValueError("Enter a valid exam date and time.") from error
            client.table("exams").insert(exam).execute()
            return "The exam was scheduled."
        if action == "assign-teacher":
            course_id = int(form.get("course_id", ""))
            _require_active_course(client, course_id)
            profile_id = str(form.get("profile_id", "")).strip()
            if not profile_id:
                raise ValueError("Choose a teacher.")
            client.table("course_staff").upsert({
                "course_id": course_id,
                "profile_id": profile_id,
            }, on_conflict="course_id,profile_id").execute()
            return "The teacher was assigned to the course."
        if action == "enroll-student":
            student_id = str(form.get("student_id", "")).strip()
            term = str(form.get("term", "")).strip()
            if not student_id or not term:
                raise ValueError("Choose a student and enter a term.")
            course_id = int(form.get("course_id", ""))
            _require_active_course(client, course_id)
            client.table("enrollments").upsert({
                "course_id": course_id,
                "student_id": student_id,
                "term": term,
            }, on_conflict="course_id,student_id,term").execute()
            return "The student was enrolled."
        raise HTTPException(status_code=400, detail="Unknown course management action.")
    if role == "admin" and section == "users":
        action = form.get("action")
        if action == "delete-account":
            profile_id = str(form.get("profile_id", "")).strip()
            try:
                profile_id = str(UUID(profile_id))
            except ValueError as error:
                raise ValueError("Choose a valid campus account to remove.") from error
            if profile_id == str(user.id):
                raise ValueError("You cannot remove the account you are currently using.")
            _delete_campus_account(profile_id, access_token)
            return "The campus account and its linked records were removed."
        if action == "create-account":
            account = {
                "email": str(form.get("email", "")).strip().lower(),
                "password": str(form.get("password", "")),
                "full_name": str(form.get("full_name", "")).strip(),
                "username": str(form.get("username", "")).strip().lower(),
                "role": str(form.get("role", "")).strip().lower(),
                "department": str(form.get("department", "")).strip(),
                "student_number": str(form.get("student_number", "")).strip(),
                "program": str(form.get("program", "")).strip(),
                "semester": str(form.get("semester", "")).strip(),
            }
            if not all(account[key] for key in (
                "email", "password", "full_name", "username", "role", "department"
            )):
                raise ValueError("Complete all required campus account fields.")
            if account["role"] not in {"student", "teacher", "hod"}:
                raise ValueError("Choose student, teacher, or HOD for the new account.")
            if len(account["password"]) < 8:
                raise ValueError("The initial password must contain at least 8 characters.")
            if account["role"] == "student" and not account["student_number"]:
                raise ValueError("Enter the student's student number.")
            if account["program"] or account["semester"]:
                if account["role"] != "student" or account["program"] not in CURRICULUM_PROGRAMS:
                    raise ValueError("Choose a valid program for a student account.")
                if account["semester"] not in {str(value) for value in range(1, 9)}:
                    raise ValueError("Choose a semester between 1 and 8.")
            _create_campus_account(account, access_token)
            return "The campus account was created and assigned to its department."
        raise HTTPException(status_code=400, detail="Unknown account management action.")
    if role == "admin" and section == "departments":
        action = form.get("action")
        if action == "delete-department":
            department_name = str(form.get("department_name", "")).strip()
            if not department_name:
                raise ValueError("Choose a department to remove.")
            linked_profiles = client.table("profiles").select("id").eq(
                "department", department_name
            ).limit(1).execute().data
            linked_courses = client.table("courses").select("id").eq(
                "department", department_name
            ).limit(1).execute().data
            if linked_profiles or linked_courses:
                raise ValueError(
                    "This department still has campus accounts or courses. Reassign or remove them first."
                )
            removed = client.table("departments").delete().eq(
                "name", department_name
            ).select("name").execute().data
            if not removed:
                raise RuntimeError("The department was not found or could not be removed.")
            return "The department was removed."
        if action == "add-department":
            department_name = str(form.get("name", "")).strip()
            if not department_name:
                raise ValueError("Enter a department name.")
            existing = client.table("departments").select("name").eq(
                "name", department_name
            ).limit(1).execute().data
            if existing:
                raise ValueError("That department is already in the list.")
            client.table("departments").insert({"name": department_name}).execute()
            return "The department was added."
        raise HTTPException(status_code=400, detail="Unknown department management action.")
    if role == "admin" and section == "announcements":
        title = str(form.get("title", "")).strip()
        body = str(form.get("body", "")).strip()
        audience = str(form.get("audience", "all"))
        if not title or not body:
            raise ValueError("Enter a title and announcement.")
        client.table("announcements").insert({
            "title": title,
            "body": body,
            "audience": audience,
            "published": True,
            "published_at": datetime.now(timezone.utc).isoformat(),
            "created_by": str(user.id),
        }).execute()
        return "The announcement was published."
    raise HTTPException(status_code=404)


@app.api_route("/portal/{role}/{section}", methods=["GET", "POST"], name="portal_page")
async def portal_page(request: Request, role: str, section: str):
    profile = await run_in_threadpool(
        _set_authenticated_user,
        request,
        request.session.get("auth_session_id"),
    )
    if not profile:
        request.session.pop("auth_session_id", None)
        flash(request, "Please sign in with an active campus account.", "error")
        return _redirect(request, "login")
    current_role, portal = _current_portal(request)
    if role != current_role:
        return _redirect(
            request, "portal_page", role=current_role, section="dashboard"
        )
    if role not in PORTALS or section not in {
        key for key, _label in PORTALS[role]["navigation"]
    }:
        raise HTTPException(status_code=404)
    if request.method == "POST":
        form = await request.form()
        _verify_csrf(request, form)
        try:
            message = await run_in_threadpool(
                _handle_portal_post, request, role, section, form
            )
            flash(request, message, "success")
            return _redirect(request, "portal_page", role=role, section=section)
        except ValueError as error:
            flash(request, str(error), "error")
        except RuntimeError as error:
            logger.warning("Supabase management action could not complete: %s", error)
            flash(request, str(error), "error")
        except HTTPException:
            raise
        except Exception:
            logger.exception("Supabase form submission failed.")
            flash(
                request,
                "Could not save this change. Check your access and database policies, then try again.",
                "error",
            )
    try:
        page = await run_in_threadpool(
            build_live_page, role, section, request.state.profile, request.state.supabase
        )
    except Exception:
        logger.exception("Could not load Supabase data for portal page.")
        page = {
            "key": section,
            "title": section.replace("-", " ").title(),
            "summary": "Supabase data could not be loaded.",
            "metrics": [],
            "columns": [],
            "rows": [],
            "form_fields": [],
            "form_title": "",
            "data_error": "Could not load this page's data. Check your Supabase schema, account access, and Row Level Security policies.",
        }
        status_code = 503
    else:
        status_code = 200
    return templates.TemplateResponse(
        request=request,
        name="portal.html",
        context={
            "role": role,
            "portal": portal,
            "page": page,
            "csrf_token": _csrf_token(request),
        },
        status_code=status_code,
    )


@app.get("/map", name="map_page")
async def map_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="map.html",
        context={"run_layout_tests": request.query_params.get("test") == "1"},
    )


@app.get("/health/supabase", name="supabase_health")
async def supabase_health():
    try:
        response = await run_in_threadpool(
            lambda: get_supabase_client().table("courses").select("id").limit(1).execute()
        )
    except RuntimeError as error:
        return JSONResponse(
            status_code=503,
            content={"status": "not_configured", "message": str(error)},
        )
    except Exception:
        logger.exception("Supabase health check failed.")
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "message": "Supabase could not be reached."},
        )
    if not isinstance(response.data, list):
        logger.error("Supabase REST endpoint returned a non-JSON response.")
        return JSONResponse(
            status_code=503,
            content={
                "status": "invalid_response",
                "message": "Supabase returned a non-JSON response. Check that SUPABASE_URL is the project's API URL.",
            },
        )
    return {"status": "connected"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("PORT", "5000")))
