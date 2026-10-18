import json
import os
import secrets
import time
from datetime import datetime, timezone
from functools import wraps
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import Flask, abort, current_app, flash, g, jsonify, redirect, render_template, request, session, url_for
from dotenv import load_dotenv

from auth_sessions import delete_session, get_session, save_session, update_session
from portal_data import build_live_page
from supabase_client import create_supabase_client, get_supabase_client

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "development-only-change-me")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true",
)

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

@app.context_processor
def inject_csrf_token():
    session.setdefault("csrf_token", secrets.token_urlsafe(32))
    return {"csrf_token": session["csrf_token"]}


@app.before_request
def verify_csrf_token():
    if request.method == "POST":
        expected = session.get("csrf_token")
        supplied = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
        if not expected or not supplied or not secrets.compare_digest(expected, supplied):
            abort(400, description="The form expired. Reload the page and try again.")


def _set_authenticated_user(session_id):
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
            expires_at = int(refreshed_session.expires_at or time.time() + refreshed_session.expires_in)
            update_session(session_id, access_token, refresh_token, expires_at)
        else:
            access_token = str(auth_session["access_token"])
        profile_client = create_supabase_client(access_token)
        user_response = auth_client.auth.get_user(access_token)
        user = user_response.user if user_response else None
        if not user:
            delete_session(session_id)
            return None
        profile_response = (
            profile_client.table("profiles")
            .select("*")
            .eq("id", str(user.id))
            .limit(1)
            .execute()
        )
        profile = profile_response.data[0] if profile_response.data else None
        if not profile or profile.get("role") not in PORTALS:
            delete_session(session_id)
            return None
        g.user = user
        g.profile = profile
        g.supabase = profile_client
        g.access_token = access_token
        return profile
    except Exception:
        current_app.logger.exception("Could not validate the current Supabase session.")
        delete_session(session_id)
        return None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not _set_authenticated_user(session.get("auth_session_id")):
            session.pop("auth_session_id", None)
            flash("Please sign in with an active campus account.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def current_portal():
    profile = g.profile
    role = profile["role"]
    portal = PORTALS[role].copy()
    portal["name"] = profile.get("full_name") or g.user.email or portal["name"]
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
    lookup_request = Request(
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


def _create_campus_account(payload, access_token):
    supabase_url = os.getenv("SUPABASE_URL")
    anon_key = os.getenv("SUPABASE_ANON_KEY")
    if not supabase_url or not anon_key:
        raise RuntimeError("Supabase account creation is not configured.")
    function_request = Request(
        f"{supabase_url.rstrip('/')}/functions/v1/admin-create-account",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "apikey": anon_key,
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(function_request, timeout=20) as response:
            result = json.loads(response.read())
    except HTTPError as error:
        try:
            result = json.loads(error.read())
        except json.JSONDecodeError:
            result = {}
        message = result.get("error") if isinstance(result, dict) else None
        raise RuntimeError(message or f"Account creation failed with HTTP {error.code}.") from error
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError("Could not reach the account-creation function.") from error
    if not isinstance(result, dict) or not result.get("user_id"):
        raise RuntimeError("The account-creation function returned an invalid response.")
    return result


@app.get("/")
def login():
    if _set_authenticated_user(session.get("auth_session_id")):
        role, _portal = current_portal()
        return redirect(url_for("portal_page", role=role, section="dashboard"))
    return render_template("login.html")


@app.post("/login")
def login_submit():
    login_method = request.form.get("login_method", "").strip().lower()
    identifier = request.form.get("identifier", "").strip()
    password = request.form.get("password", "")
    if login_method not in {"email", "username"} or not identifier or not password:
        flash("Choose email or username, then enter your account name and password.", "error")
        return redirect(url_for("login"))
    if login_method == "email":
        email = identifier.lower()
    else:
        try:
            email = _resolve_login_email(identifier)
        except RuntimeError as error:
            current_app.logger.exception("Username lookup is not available.")
            flash(str(error), "error")
            return redirect(url_for("login"))
    if not email:
        flash("Username or password is incorrect.", "error")
        return redirect(url_for("login"))
    try:
        auth_client = create_supabase_client()
        response = auth_client.auth.sign_in_with_password({"email": email, "password": password})
        if not response.user or not response.session:
            flash("Sign-in did not return an active session. Check your account and email confirmation.", "error")
            return redirect(url_for("login"))
        expires_at = int(response.session.expires_at or time.time() + response.session.expires_in)
        session_id = save_session(response.session.access_token, response.session.refresh_token, expires_at)
        session.clear()
        session["auth_session_id"] = session_id
        session["csrf_token"] = secrets.token_urlsafe(32)
        if not _set_authenticated_user(session_id):
            session.clear()
            flash("Your account needs a campus profile. Ask an administrator to finish setting it up.", "error")
            return redirect(url_for("login"))
        role, _portal = current_portal()
        return redirect(url_for("portal_page", role=role, section="dashboard"))
    except Exception:
        current_app.logger.exception("Supabase sign-in failed.")
        flash("Sign-in failed. Check your email or username and password, then try again.", "error")
        return redirect(url_for("login"))


@app.post("/password-reset")
def password_reset():
    email = request.form.get("email", "").strip().lower()
    if not email:
        flash("Enter your account email to request a reset link.", "error")
        return redirect(url_for("login"))
    try:
        create_supabase_client().auth.reset_password_email(email)
    except Exception:
        current_app.logger.exception("Supabase password reset request failed.")
        flash("Could not request a password reset. Please try again later.", "error")
        return redirect(url_for("login"))
    flash("If the account exists, Supabase will send a password reset email.", "success")
    return redirect(url_for("login"))


@app.post("/logout")
def logout():
    delete_session(session.get("auth_session_id"))
    session.clear()
    flash("You have signed out.", "success")
    return redirect(url_for("login"))


@app.get("/dashboard")
def dashboard():
    return redirect(url_for("portal_page", role="student", section="dashboard"))


@app.get("/portal/<role>")
@login_required
def portal_home(role):
    current_role, _portal = current_portal()
    if role != current_role:
        return redirect(url_for("portal_page", role=current_role, section="dashboard"))
    if role not in PORTALS:
        abort(404)
    return redirect(url_for("portal_page", role=role, section="dashboard"))


@app.route("/portal/<role>/<section>", methods=["GET", "POST"])
@login_required
def portal_page(role, section):
    current_role, portal = current_portal()
    if role != current_role:
        return redirect(url_for("portal_page", role=current_role, section="dashboard"))
    if role not in PORTALS or section not in {key for key, _label in PORTALS[role]["navigation"]}:
        abort(404)
    if request.method == "POST":
        try:
            if section in ("feedback", "complaints") and role == "student":
                subject = request.form.get("subject", "").strip()
                message = request.form.get("message", "").strip()
                if not subject or not message:
                    raise ValueError("Enter a subject and message.")
                g.supabase.table("student_requests").insert({
                    "student_id": str(g.user.id),
                    "request_type": "feedback" if section == "feedback" else "complaint",
                    "subject": subject,
                    "message": message,
                }).execute()
                flash("Your request was saved.", "success")
            elif role == "teacher" and section == "attendance-entry":
                g.supabase.table("attendance_records").upsert({
                    "session_id": int(request.form.get("session_id", "")),
                    "student_id": request.form.get("student_id", ""),
                    "marked_by": str(g.user.id),
                    "status": request.form.get("status", ""),
                }, on_conflict="session_id,student_id").execute()
                flash("Attendance was saved.", "success")
            elif role == "teacher" and section == "results-entry":
                grade = request.form.get("grade", "").strip()
                term = request.form.get("term", "").strip()
                if not grade or not term:
                    raise ValueError("Enter a grade and term.")
                g.supabase.table("grades").upsert({
                    "course_id": int(request.form.get("course_id", "")),
                    "student_id": request.form.get("student_id", ""),
                    "grade": grade,
                    "term": term,
                    "published": False,
                }, on_conflict="course_id,student_id,term").execute()
                flash("The grade was saved as unpublished.", "success")
            elif role == "admin" and section == "courses":
                action = request.form.get("action")
                if action == "add-course":
                    credits = int(request.form.get("credits", ""))
                    name = request.form.get("name", "").strip()
                    code = request.form.get("code", "").strip().upper()
                    department = request.form.get("department", "").strip()
                    if credits < 1 or not name or not code or not department:
                        raise ValueError("Enter a course name, code, department, and positive credit count.")
                    allowed_departments = g.supabase.table("departments").select("name").eq(
                        "name", department
                    ).limit(1).execute().data
                    if not allowed_departments:
                        raise ValueError("Choose a department from the department list.")
                    g.supabase.table("courses").insert({
                        "name": name,
                        "code": code,
                        "department": department,
                        "credits": credits,
                    }).execute()
                    flash("The course was added.", "success")
                elif action == "add-session":
                    session_values = {
                        "course_id": int(request.form.get("course_id", "")),
                        "starts_at": request.form.get("starts_at", "").strip(),
                        "ends_at": request.form.get("ends_at", "").strip(),
                        "location": request.form.get("location", "").strip(),
                    }
                    if not all(session_values.values()):
                        raise ValueError("Complete all class session fields.")
                    try:
                        starts_at = datetime.fromisoformat(session_values["starts_at"])
                        ends_at = datetime.fromisoformat(session_values["ends_at"])
                    except ValueError as error:
                        raise ValueError("Enter valid class start and end times.") from error
                    if ends_at <= starts_at:
                        raise ValueError("The class end time must be after its start time.")
                    g.supabase.table("class_sessions").insert(session_values).execute()
                    flash("The class session was scheduled.", "success")
                elif action == "add-exam":
                    exam = {
                        "course_id": int(request.form.get("course_id", "")),
                        "title": request.form.get("title", "").strip(),
                        "exam_type": request.form.get("exam_type", "").strip(),
                        "starts_at": request.form.get("starts_at", "").strip(),
                        "location": request.form.get("location", "").strip(),
                    }
                    if not all(exam.values()):
                        raise ValueError("Complete all exam details.")
                    try:
                        datetime.fromisoformat(exam["starts_at"])
                    except ValueError as error:
                        raise ValueError("Enter a valid exam date and time.") from error
                    g.supabase.table("exams").insert(exam).execute()
                    flash("The exam was scheduled.", "success")
                elif action == "assign-teacher":
                    g.supabase.table("course_staff").upsert({
                        "course_id": int(request.form.get("course_id", "")),
                        "profile_id": request.form.get("profile_id", ""),
                    }, on_conflict="course_id,profile_id").execute()
                    flash("The teacher was assigned to the course.", "success")
                elif action == "enroll-student":
                    student_id = request.form.get("student_id", "")
                    term = request.form.get("term", "").strip()
                    if not student_id or not term:
                        raise ValueError("Choose a student and enter a term.")
                    g.supabase.table("enrollments").upsert({
                        "course_id": int(request.form.get("course_id", "")),
                        "student_id": student_id,
                        "term": term,
                    }, on_conflict="course_id,student_id,term").execute()
                    flash("The student was enrolled.", "success")
                else:
                    abort(400, description="Unknown course management action.")
            elif role == "admin" and section == "users":
                action = request.form.get("action")
                if action != "create-account":
                    abort(400, description="Unknown account management action.")
                account = {
                    "email": request.form.get("email", "").strip().lower(),
                    "password": request.form.get("password", ""),
                    "full_name": request.form.get("full_name", "").strip(),
                    "username": request.form.get("username", "").strip().lower(),
                    "role": request.form.get("role", "").strip().lower(),
                    "department": request.form.get("department", "").strip(),
                    "student_number": request.form.get("student_number", "").strip(),
                }
                if not all(account[key] for key in ("email", "password", "full_name", "username", "role", "department")):
                    raise ValueError("Complete all required campus account fields.")
                if account["role"] not in {"student", "teacher", "hod"}:
                    raise ValueError("Choose student, teacher, or HOD for the new account.")
                if len(account["password"]) < 8:
                    raise ValueError("The initial password must contain at least 8 characters.")
                if account["role"] == "student" and not account["student_number"]:
                    raise ValueError("Enter the student's student number.")
                _create_campus_account(account, g.access_token)
                flash("The campus account was created and assigned to its department.", "success")
            elif role == "admin" and section == "departments":
                department_name = request.form.get("name", "").strip()
                if not department_name:
                    raise ValueError("Enter a department name.")
                existing = g.supabase.table("departments").select("name").eq(
                    "name", department_name
                ).limit(1).execute().data
                if existing:
                    raise ValueError("That department is already in the list.")
                g.supabase.table("departments").insert({"name": department_name}).execute()
                flash("The department was added.", "success")
            elif role == "admin" and section == "announcements":
                title = request.form.get("title", "").strip()
                body = request.form.get("body", "").strip()
                audience = request.form.get("audience", "all")
                if not title or not body:
                    raise ValueError("Enter a title and announcement.")
                g.supabase.table("announcements").insert({
                    "title": title,
                    "body": body,
                    "audience": audience,
                    "published": True,
                    "published_at": datetime.now(timezone.utc).isoformat(),
                    "created_by": str(g.user.id),
                }).execute()
                flash("The announcement was published.", "success")
            else:
                abort(404)
            return redirect(url_for("portal_page", role=role, section=section))
        except ValueError as error:
            flash(str(error), "error")
        except RuntimeError as error:
            current_app.logger.warning("Supabase management action could not complete: %s", error)
            flash(str(error), "error")
        except Exception:
            current_app.logger.exception("Supabase form submission failed.")
            flash("Could not save this change. Check your access and database policies, then try again.", "error")
    try:
        page = build_live_page(role, section, g.profile, g.supabase)
    except Exception:
        current_app.logger.exception("Could not load Supabase data for portal page.")
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
        response = render_template("portal.html", role=role, portal=portal, page=page)
        return response, 503
    return render_template("portal.html", role=role, portal=portal, page=page)


@app.get("/map")
def map_page():
    return render_template("map.html", run_layout_tests=request.args.get("test") == "1")


@app.get("/health/supabase")
def supabase_health():
    try:
        response = get_supabase_client().table("courses").select("id").limit(1).execute()
    except RuntimeError as error:
        return jsonify(status="not_configured", message=str(error)), 503
    except Exception:
        current_app.logger.exception("Supabase health check failed.")
        return jsonify(status="unavailable", message="Supabase could not be reached."), 503
    if not isinstance(response.data, list):
        current_app.logger.error("Supabase REST endpoint returned a non-JSON response.")
        return jsonify(
            status="invalid_response",
            message="Supabase returned a non-JSON response. Check that SUPABASE_URL is the project's API URL.",
        ), 503
    return jsonify(status="connected")


if __name__ == "__main__":
    app.run(debug=True)
