from django.shortcuts import redirect


class LocalEnrollmentRequiredMiddleware:
    """Force l’enregistrement d’une passkey avant tout accès applicatif."""

    allowed_prefixes = (
        "/access/passkey/register/",
        "/access/logout/",
        "/access/login/",
        "/access/signup/",
        "/access/recover/",
        "/access/verify/",
        "/static/",
        "/health/",
        "/metrics/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and request.session.get("local_enrollment_required") and not request.path.startswith(self.allowed_prefixes):
            return redirect("identity-passkey-register")
        return self.get_response(request)
