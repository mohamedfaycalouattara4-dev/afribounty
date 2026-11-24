from django.core.paginator import Paginator
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from apps.integrations.services import authorize_api_key
from apps.organizations.models import Organization
from apps.programs.models import AssetScope, Program


def _error(code: str, detail: str, status: int) -> JsonResponse:
    return JsonResponse({"error": {"code": code, "detail": detail}}, status=status)


def _public_programs():
    return Program.objects.select_related("organization").filter(
        status=Program.Status.PUBLIC_ACTIVE,
        organization__verification_status=Organization.VerificationStatus.VERIFIED,
    )


def _require_api_key(request, *, scope: str, safe_reference: str):
    scheme, _, raw_key = request.headers.get("Authorization", "").partition(" ")
    if scheme != "Bearer" or not raw_key:
        return None
    try:
        return authorize_api_key(raw_key=raw_key, scope=scope, safe_reference=safe_reference)
    except PermissionDenied:
        return None


def _serialize_program(program: Program, *, include_scopes: bool = False) -> dict:
    payload = {
        "id": program.id,
        "name": program.name,
        "organization": program.organization.name,
        "policy_version": program.policy_version,
        "status": "public_active",
        "links": {"html": f"/programs/{program.id}/", "self": f"/api/v1/programs/{program.id}/"},
    }
    if include_scopes:
        payload["scopes"] = list(
            AssetScope.objects.filter(program=program, is_active=True, is_verified=True, is_excluded=False).values("id", "asset", "asset_type")
        )
    return payload


@require_GET
def api_v1_index(request):
    return JsonResponse(
        {
            "name": "AfriBounty Public API",
            "version": "v1",
            "status": "read_only",
            "endpoints": {"programs": "/api/v1/programs/", "openapi": "/api/v1/openapi.json"},
            "deprecation_policy": "Toute évolution incompatible introduira une nouvelle version majeure.",
        }
    )


@require_GET
def api_v1_openapi(request):
    return JsonResponse(
        {
            "openapi": "3.0.3",
            "info": {"title": "AfriBounty Public API", "version": "1.0.0"},
            "paths": {
                "/api/v1/programs/": {"get": {"summary": "Lister les programmes publics vérifiés"}},
                "/api/v1/programs/{program_id}/": {"get": {"summary": "Lire un programme public vérifié"}},
                "/api/v1/key/": {"get": {"summary": "Inspecter sa clé API active", "security": [{"bearerAuth": []}]}},
            },
            "components": {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}}},
            "security": [],
        }
    )


@require_GET
def api_v1_programs(request):
    query = request.GET.get("q", "").strip()
    queryset = _public_programs()
    if query:
        queryset = queryset.filter(name__icontains=query)
    try:
        page_number = max(1, int(request.GET.get("page", "1")))
    except ValueError:
        return _error("invalid_page", "Le paramètre page doit être un entier positif.", 400)
    page = Paginator(queryset.order_by("name", "id"), 20).get_page(page_number)
    return JsonResponse(
        {
            "data": [_serialize_program(program) for program in page.object_list],
            "pagination": {"page": page.number, "page_size": 20, "total": page.paginator.count, "pages": page.paginator.num_pages},
        }
    )


@require_GET
def api_v1_program_detail(request, program_id: int):
    program = _public_programs().filter(id=program_id).first()
    if program is None:
        return _error("not_found", "Programme public introuvable.", 404)
    return JsonResponse({"data": _serialize_program(program, include_scopes=True)})


@require_GET
def api_v1_key_inspection(request):
    key = _require_api_key(request, scope="programs.read", safe_reference="api:v1:key-inspection")
    if key is None:
        response = _error("authentication_failed", "Authentification par clé API refusée.", 401)
        response["WWW-Authenticate"] = "Bearer"
        return response
    return JsonResponse(
        {
            "data": {
                "key_prefix": key.key_prefix,
                "scopes": key.scopes,
                "expires_at": key.expires_at.isoformat(),
                "owner_id": key.owner_id,
            }
        }
    )
