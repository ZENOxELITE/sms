import logging

from django.http import Http404, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.middleware.csrf import get_token

import portal.services as services


logger = logging.getLogger("sms")


def _redirect(name, **path_params):
    return HttpResponseRedirect(reverse(name, kwargs=path_params or None))


def _authenticated_profile(request):
    profile = services._set_authenticated_user(
        request, request.session.get("auth_session_id")
    )
    if profile:
        return profile
    request.session.pop("auth_session_id", None)
    services.flash(request, "Please sign in with an active campus account.", "error")
    return None


def _login_page(request):
    return render(request, "login.html", {"csrf_token": get_token(request)})


@require_GET
def login(request):
    profile = services._set_authenticated_user(
        request, request.session.get("auth_session_id")
    )
    if profile:
        return _redirect(
            "portal_page", role=profile["role"], section="dashboard"
        )
    return _login_page(request)


@require_POST
def login_submit(request):
    login_method = str(request.POST.get("login_method", "")).strip().lower()
    identifier = str(request.POST.get("identifier", "")).strip()
    password = str(request.POST.get("password", ""))
    if login_method not in {"email", "username"} or not identifier or not password:
        services.flash(
            request,
            "Choose email or username, then enter your account name and password.",
            "error",
        )
        return _redirect("login")
    if login_method == "email":
        email = identifier.lower()
    else:
        try:
            email = services._resolve_login_email(identifier)
        except RuntimeError as error:
            logger.exception("Username lookup is not available.")
            services.flash(request, str(error), "error")
            return _redirect("login")
    if not email:
        services.flash(request, "Username or password is incorrect.", "error")
        return _redirect("login")
    try:
        result = services._authenticate_credentials(email, password)
        if not result:
            services.flash(
                request,
                "Sign-in did not return an active session. Check your account and email confirmation.",
                "error",
            )
            return _redirect("login")
        _user, session_id = result
        request.session.flush()
        request.session["auth_session_id"] = session_id
        profile = services._set_authenticated_user(request, session_id)
        if not profile:
            request.session.flush()
            services.flash(
                request,
                "Your account needs a campus profile. Ask an administrator to finish setting it up.",
                "error",
            )
            return _redirect("login")
        return _redirect(
            "portal_page", role=profile["role"], section="dashboard"
        )
    except Exception:
        logger.exception("Supabase sign-in failed.")
        services.flash(
            request,
            "Sign-in failed. Check your email or username and password, then try again.",
            "error",
        )
        return _redirect("login")


@require_POST
def password_reset(request):
    email = str(request.POST.get("email", "")).strip().lower()
    if not email:
        services.flash(
            request, "Enter your account email to request a reset link.", "error"
        )
        return _redirect("login")
    try:
        services.create_supabase_client().auth.reset_password_email(email)
    except Exception:
        logger.exception("Supabase password reset request failed.")
        services.flash(
            request,
            "Could not request a password reset. Please try again later.",
            "error",
        )
        return _redirect("login")
    services.flash(
        request,
        "If the account exists, Supabase will send a password reset email.",
        "success",
    )
    return _redirect("login")


@require_POST
def logout(request):
    services.delete_session(request.session.get("auth_session_id"))
    request.session.flush()
    services.flash(request, "You have signed out.", "success")
    return _redirect("login")


@require_GET
def dashboard(request):
    return _redirect("portal_page", role="student", section="dashboard")


@require_GET
def portal_home(request, role):
    profile = _authenticated_profile(request)
    if not profile:
        return _redirect("login")
    if role != profile["role"]:
        return _redirect(
            "portal_page", role=profile["role"], section="dashboard"
        )
    if role not in services.PORTALS:
        raise Http404
    return _redirect("portal_page", role=role, section="dashboard")


@require_http_methods(["GET", "POST"])
def portal_page(request, role, section):
    profile = _authenticated_profile(request)
    if not profile:
        return _redirect("login")
    current_role, portal = services._current_portal(request)
    if role != current_role:
        return _redirect(
            "portal_page", role=current_role, section="dashboard"
        )
    if role not in services.PORTALS or section not in {
        key for key, _label in services.PORTALS[role]["navigation"]
    }:
        raise Http404
    if request.method == "POST":
        try:
            message = services._handle_portal_post(
                request, role, section, request.POST
            )
            services.flash(request, message, "success")
            return _redirect("portal_page", role=role, section=section)
        except ValueError as error:
            services.flash(request, str(error), "error")
        except services.PortalRequestError as error:
            return HttpResponse(str(error), status=error.status_code)
        except RuntimeError as error:
            logger.warning(
                "Supabase management action could not complete: %s", error
            )
            services.flash(request, str(error), "error")
        except Exception:
            logger.exception("Supabase form submission failed.")
            services.flash(
                request,
                "Could not save this change. Check your access and database policies, then try again.",
                "error",
            )
    try:
        page = services.build_live_page(
            role, section, request.profile, request.supabase
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
    return render(
        request,
        "portal.html",
        {
            "role": role,
            "portal": portal,
            "page": page,
            "csrf_token": get_token(request),
        },
        status=status_code,
    )


@require_GET
def map_page(request):
    return render(
        request,
        "map.html",
        {"run_layout_tests": request.GET.get("test") == "1"},
    )


@require_GET
def supabase_health(_request):
    try:
        response = (
            services.get_supabase_client()
            .table("courses")
            .select("id")
            .limit(1)
            .execute()
        )
    except RuntimeError as error:
        return JsonResponse(
            {"status": "not_configured", "message": str(error)}, status=503
        )
    except Exception:
        logger.exception("Supabase health check failed.")
        return JsonResponse(
            {
                "status": "unavailable",
                "message": "Supabase could not be reached.",
            },
            status=503,
        )
    if not isinstance(response.data, list):
        logger.error("Supabase REST endpoint returned a non-JSON response.")
        return JsonResponse(
            {
                "status": "invalid_response",
                "message": "Supabase returned a non-JSON response. Check that SUPABASE_URL is the project's API URL.",
            },
            status=503,
        )
    return JsonResponse({"status": "connected"})
