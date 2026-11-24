import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.contrib.auth import password_validation
from django.db import transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from apps.identity.local_auth import (
    authenticate_local_password,
    authentication_options_for,
    consume_recovery_code,
    create_local_account,
    issue_recovery_codes,
    registration_options_for,
    verify_authentication,
    verify_registration,
)
from apps.identity.models import AccountProfile, User


def _dashboard_for(user) -> str:
    destinations = {
        User.PlatformRole.ORGANIZATION: "identity-organization-home",
        User.PlatformRole.TRIAGER: "experience-triage-console",
        User.PlatformRole.FINANCE: "experience-finance-console",
        User.PlatformRole.ADMIN: "experience-administration-console",
        User.PlatformRole.SECURITY: "experience-readiness-console",
    }
    return destinations.get(user.platform_role, "experience-researcher-dashboard")


def _pending_user(request) -> User | None:
    user_id = request.session.get("local_pre_auth_user_id")
    return User.objects.filter(pk=user_id, is_active=True).first() if user_id else None


def _safe_json_body(request) -> dict:
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValidationError("La réponse de sécurité est mal formée.")
    if not isinstance(payload, dict):
        raise ValidationError("La réponse de sécurité est invalide.")
    return payload


@require_http_methods(["GET", "POST"])
def signup(request):
    if request.user.is_authenticated:
        return redirect(_dashboard_for(request.user))
    if request.method == "POST":
        account_intent = request.POST.get("account_intent", "")
        identifier = request.POST.get("identifier", "")
        display_name = request.POST.get("display_name", "").strip()
        country_code = request.POST.get("country_code", "").strip().upper()
        organization_name = request.POST.get("organization_name", "").strip()
        password = request.POST.get("password", "")
        password_confirmation = request.POST.get("password_confirmation", "")
        accepted_rules = request.POST.get("accepted_rules") == "on"
        acknowledged_recovery = request.POST.get("acknowledged_recovery") == "on"
        if password != password_confirmation:
            messages.error(request, "Les deux mots de passe ne correspondent pas.")
        elif not accepted_rules or not acknowledged_recovery:
            messages.error(request, "Vous devez accepter les règles et confirmer avoir compris la récupération hors ligne.")
        else:
            try:
                user, recovery_codes = create_local_account(
                    identifier=identifier,
                    password=password,
                    consent_version="platform-v2-local-auth",
                    account_intent=account_intent,
                    display_name=display_name,
                    country_code=country_code,
                    organization_name=organization_name,
                )
            except (ValidationError, PermissionDenied) as exc:
                messages.error(request, str(exc))
            else:
                login(request, user, backend="django.contrib.auth.backends.ModelBackend")
                request.session["pending_recovery_codes"] = recovery_codes
                request.session["local_enrollment_started"] = True
                request.session["local_enrollment_required"] = True
                return redirect("identity-passkey-register")
    return render(request, "identity/signup.html", {"intent_choices": AccountProfile.AccountIntent.choices})


@require_http_methods(["GET", "POST"])
def local_login(request):
    if request.user.is_authenticated:
        return redirect(_dashboard_for(request.user))
    if request.method == "POST":
        identifier = request.POST.get("identifier", "")
        password = request.POST.get("password", "")
        try:
            user = authenticate_local_password(identifier=identifier, password=password)
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, str(exc))
        else:
            request.session.cycle_key()
            request.session["local_pre_auth_user_id"] = user.id
            request.session["local_password_authenticated"] = True
            if user.webauthn_credentials.filter(revoked_at__isnull=True).exists():
                return redirect("identity-passkey-login")
            request.session["local_enrollment_required"] = True
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            request.session["local_enrollment_started"] = False
            messages.warning(request, "Votre compte n’a pas encore de passkey. Enregistrez-en une immédiatement pour terminer la protection de votre compte.")
            return redirect("identity-passkey-register")
    return render(request, "identity/login.html")


@require_http_methods(["GET", "POST"])
def passkey_register(request):
    if not request.user.is_authenticated:
        return redirect(f"{settings.LOGIN_URL}?next=/access/passkey/register/")
    if request.method == "GET":
        try:
            options = registration_options_for(user=request.user, request=request)
        except (ValidationError, PermissionDenied) as exc:
            return render(request, "identity/access_invalid.html", {"detail": str(exc)}, status=400)
        return render(
            request,
            "identity/passkey_register.html",
            {
                "options": options,
                "enrollment": request.session.get("local_enrollment_started", False),
                "second_required": request.user.webauthn_credentials.filter(revoked_at__isnull=True).count() < 2,
            },
        )
    try:
        credential = _safe_json_body(request)
        verify_registration(user=request.user, request=request, credential=credential)
    except (ValidationError, PermissionDenied) as exc:
        return render(request, "identity/access_invalid.html", {"detail": str(exc)}, status=400)
    if request.user.webauthn_credentials.filter(revoked_at__isnull=True).count() < 2:
        request.session["local_enrollment_required"] = True
        messages.warning(
            request,
            "Une deuxième passkey est obligatoire. Utilisez un autre appareil ou une autre clé FIDO2 ; "
            "ne quittez pas cette étape sans sauvegarde indépendante.",
        )
        return redirect("identity-passkey-register")
    recovery_codes = request.session.pop("pending_recovery_codes", [])
    request.session.pop("local_enrollment_started", None)
    request.session.pop("local_enrollment_required", None)
    if recovery_codes:
        return render(request, "identity/recovery_codes.html", {"recovery_codes": recovery_codes})
    messages.success(request, "Votre passkey est enregistrée. Votre compte est maintenant protégé par une authentification locale forte.")
    return redirect(_dashboard_for(request.user))


@require_http_methods(["GET", "POST"])
def passkey_login(request):
    user = _pending_user(request)
    if user is None:
        return redirect("identity-login")
    if request.method == "GET":
        try:
            options = authentication_options_for(user=user, request=request)
        except PermissionDenied as exc:
            return render(request, "identity/access_invalid.html", {"detail": str(exc)}, status=400)
        return render(request, "identity/passkey_login.html", {"options": options, "identifier": user.username})
    try:
        credential = _safe_json_body(request)
        verify_authentication(user=user, request=request, credential=credential)
    except (ValidationError, PermissionDenied) as exc:
        return render(request, "identity/access_invalid.html", {"detail": str(exc)}, status=403)
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    request.session.pop("local_pre_auth_user_id", None)
    request.session.pop("local_password_authenticated", None)
    return redirect(_dashboard_for(user))


@require_http_methods(["GET", "POST"])
def recover(request):
    if request.user.is_authenticated:
        return redirect(_dashboard_for(request.user))
    if request.method == "POST":
        identifier = request.POST.get("identifier", "").strip().lower()
        code = request.POST.get("recovery_code", "")
        password = request.POST.get("password", "")
        confirmation = request.POST.get("password_confirmation", "")
        user = User.objects.filter(username=identifier, is_active=True).first()
        try:
            if user is None:
                raise PermissionDenied("Identifiant ou code de récupération invalide.")
            if password != confirmation:
                raise ValidationError("Les deux mots de passe ne correspondent pas.")
            with transaction.atomic():
                password_validation.validate_password(password, user)
                consume_recovery_code(user=user, code=code)
                user.set_password(password)
                user.save(update_fields=["password"])
                recovery_codes = issue_recovery_codes(user=user)
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, str(exc))
        else:
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            request.session["pending_recovery_codes"] = recovery_codes
            request.session["local_enrollment_required"] = True
            messages.warning(
                request,
                "Récupération réussie. Toutes les anciennes sessions ont été révoquées. Enregistrez une nouvelle passkey et imprimez de nouveaux codes.",
            )
            return redirect("identity-passkey-register")
    return render(request, "identity/recover.html")


@require_http_methods(["GET"])
def passwordless_verify(request, raw_token: str):
    return render(
        request,
        "identity/access_invalid.html",
        {
            "detail": (
                "Les liens de connexion et de vérification par e-mail sont désactivés. Utilisez votre identifiant local, votre mot de passe et votre passkey."
            )
        },
        status=410,
    )


@require_http_methods(["GET", "POST"])
def onboarding(request):
    if not request.user.is_authenticated:
        return redirect(f"{settings.LOGIN_URL}?next={request.path}")
    profile = request.user.account_profile
    if request.method == "POST":
        if request.POST.get("understood") != "on":
            messages.error(request, "Vous devez confirmer avoir compris les conséquences de la perte des moyens d’accès.")
        else:
            from apps.identity.services import complete_account_onboarding

            complete_account_onboarding(user=request.user)
            messages.success(request, "Onboarding terminé. Vous pouvez maintenant utiliser votre espace AfriBounty.")
            return redirect(_dashboard_for(request.user))
    return render(request, "identity/onboarding.html", {"profile": profile})


@login_required
@require_http_methods(["GET", "POST"])
def profile_settings(request):
    if request.user.platform_role != User.PlatformRole.RESEARCHER:
        raise PermissionDenied("Les paramètres de profil chercheur sont réservés aux chercheurs en sécurité.")
    profile = request.user.account_profile
    if request.method == "POST":
        display_name = request.POST.get("display_name", "").strip()
        country_code = request.POST.get("country_code", "").strip().upper()
        if not display_name or len(country_code) != 2 or not country_code.isalpha():
            messages.error(request, "Indiquez un nom affiché et un code pays ISO à deux lettres.")
        else:
            profile.display_name = display_name
            profile.country_code = country_code
            profile.save(update_fields=["display_name", "country_code"])
            messages.success(request, "Vos paramètres de profil ont été enregistrés.")
            return redirect("identity-profile-settings")
    return render(request, "identity/profile_settings.html", {"profile": profile})


def organization_home(request):
    if not request.user.is_authenticated:
        return redirect(f"{settings.LOGIN_URL}?next={request.path}")
    memberships = request.user.afribounty_memberships.select_related("organization")
    return render(request, "identity/organization_home.html", {"memberships": memberships})


@require_http_methods(["POST"])
def signout(request):
    logout(request)
    messages.success(request, "Vous êtes déconnecté de cette session.")
    return redirect("experience-home")
