from django.contrib import admin
from django.urls import path

from apps.api import views as api_views
from apps.core.views import health
from apps.experience import views as experience_views
from apps.identity import views as identity_views
from apps.security import views as security_views

handler403 = experience_views.permission_denied_view
handler404 = experience_views.resource_not_found_view

urlpatterns = [
    path("api/v1/", api_views.api_v1_index, name="api-v1-index"),
    path("api/v1/openapi.json", api_views.api_v1_openapi, name="api-v1-openapi"),
    path("api/v1/programs/", api_views.api_v1_programs, name="api-v1-programs"),
    path("api/v1/programs/<int:program_id>/", api_views.api_v1_program_detail, name="api-v1-program-detail"),
    path("api/v1/key/", api_views.api_v1_key_inspection, name="api-v1-key-inspection"),
    path("", experience_views.public_home, name="experience-home"),
    path("programs/", experience_views.public_program_catalog_view, name="experience-public-program-catalog"),
    path("programs/<int:program_id>/", experience_views.public_program_detail_view, name="experience-public-program-detail"),
    path("pages/<slug:slug>/", experience_views.public_content_page_view, name="experience-public-content-page"),
    path("community/researchers/", experience_views.public_researcher_leaderboard_view, name="experience-public-researcher-leaderboard"),
    path("access/signup/", identity_views.signup, name="identity-signup"),
    path("access/login/", identity_views.local_login, name="identity-login"),
    path("access/passkey/register/", identity_views.passkey_register, name="identity-passkey-register"),
    path("access/passkey/login/", identity_views.passkey_login, name="identity-passkey-login"),
    path("access/recover/", identity_views.recover, name="identity-recover"),
    path("access/verify/<str:raw_token>/", identity_views.passwordless_verify, name="identity-passwordless-verify"),
    path("onboarding/", identity_views.onboarding, name="identity-onboarding"),
    path("settings/profile/", identity_views.profile_settings, name="identity-profile-settings"),
    path("settings/privacy/", experience_views.researcher_privacy_settings_view, name="experience-researcher-privacy-settings"),
    path("settings/security/", experience_views.account_security_settings_view, name="experience-account-security-settings"),
    path("settings/beneficiary/", experience_views.beneficiary_settings_view, name="experience-beneficiary-settings"),
    path("settings/developer/keys/", experience_views.api_key_console_view, name="experience-api-key-console"),
    path("organization/", identity_views.organization_home, name="identity-organization-home"),
    path("access/logout/", identity_views.signout, name="identity-logout"),
    path("access-required/", experience_views.access_required, name="experience-access-required"),
    path("notifications/", experience_views.notification_inbox_view, name="experience-notification-inbox"),
    path("support/", experience_views.support_center_view, name="experience-support-center"),
    path("console/support/", experience_views.support_console_view, name="experience-support-console"),
    path("onboarding/researcher/", experience_views.researcher_onboarding, name="experience-onboarding"),
    path("dashboard/researcher/", experience_views.researcher_dashboard_view, name="experience-researcher-dashboard"),
    path("reputation/", experience_views.researcher_reputation_view, name="experience-researcher-reputation"),
    path("reputation/public-profile/", experience_views.researcher_public_profile_settings_view, name="experience-researcher-public-profile-settings"),
    path("reports/draft/<int:program_id>/", experience_views.report_draft_view, name="experience-report-draft"),
    path("reports/draft/<int:program_id>/review/", experience_views.report_submit_review_view, name="experience-report-submit-review"),
    path("reports/<int:report_id>/", experience_views.report_detail_view, name="experience-report-detail"),
    path("reports/<int:report_id>/mediation/", experience_views.report_mediation_request_view, name="experience-report-mediation-request"),
    path("reports/<int:report_id>/evidence/", experience_views.report_evidence_add_view, name="experience-report-evidence-add"),
    path(
        "reports/<int:report_id>/conversation/messages/",
        experience_views.report_conversation_message_add_view,
        name="experience-report-conversation-message-add",
    ),
    path("dashboard/organization/<int:organization_id>/", experience_views.organization_dashboard_view, name="experience-organization-dashboard"),
    path("organization/<int:organization_id>/analytics/", experience_views.organization_analytics_view, name="experience-organization-analytics"),
    path("organization/<int:organization_id>/audit/", experience_views.organization_audit_log_view, name="experience-organization-audit-log"),
    path("organization/<int:organization_id>/compliance/", experience_views.organization_compliance_view, name="experience-organization-compliance"),
    path(
        "organization/<int:organization_id>/triage/metrics/", experience_views.organization_triage_metrics_view, name="experience-organization-triage-metrics"
    ),
    path(
        "organization/<int:organization_id>/programs/<int:program_id>/",
        experience_views.organization_program_detail_view,
        name="experience-organization-program-detail",
    ),
    path(
        "organization/<int:organization_id>/programs/<int:program_id>/service-level/",
        experience_views.organization_program_service_level_update_view,
        name="experience-organization-program-service-level-update",
    ),
    path(
        "organization/<int:organization_id>/programs/<int:program_id>/emergency-control/",
        experience_views.organization_program_emergency_control_view,
        name="experience-organization-program-emergency-control",
    ),
    path(
        "organization/<int:organization_id>/programs/<int:program_id>/invitations/",
        experience_views.organization_program_invitations_view,
        name="experience-organization-program-invitations",
    ),
    path(
        "organization/<int:organization_id>/programs/<int:program_id>/scopes/draft/",
        experience_views.organization_program_draft_scope_add_view,
        name="experience-organization-program-draft-scope-add",
    ),
    path(
        "organization/<int:organization_id>/reports/<int:report_id>/",
        experience_views.organization_report_detail_view,
        name="experience-organization-report-detail",
    ),
    path(
        "organization/<int:organization_id>/reports/<int:report_id>/remediation/submit/",
        experience_views.organization_remediation_submit_view,
        name="experience-organization-remediation-submit",
    ),
    path(
        "organization/<int:organization_id>/reports/<int:report_id>/conversation/messages/",
        experience_views.organization_report_conversation_message_add_view,
        name="experience-organization-report-conversation-message-add",
    ),
    path(
        "organization/<int:organization_id>/reports/<int:report_id>/evidence/",
        experience_views.organization_report_evidence_add_view,
        name="experience-organization-report-evidence-add",
    ),
    path(
        "organization/<int:organization_id>/programs/draft/",
        experience_views.organization_program_draft_create_view,
        name="experience-organization-program-draft-create",
    ),
    path("organization/<int:organization_id>/settings/", experience_views.organization_settings_view, name="experience-organization-settings"),
    path("console/triage/", experience_views.triage_console_view, name="experience-triage-console"),
    path("console/triage/reports/<int:report_id>/", experience_views.triage_report_detail_view, name="experience-triage-report-detail"),
    path("console/finance/", experience_views.finance_console_view, name="experience-finance-console"),
    path("console/administration/", experience_views.administration_console_view, name="experience-administration-console"),
    path("console/administration/readiness/", experience_views.readiness_console_view, name="experience-readiness-console"),
    path("console/administration/integrity/", experience_views.local_integrity_console_view, name="experience-local-integrity-console"),
    path("console/administration/privileges/", experience_views.privilege_review_console_view, name="experience-privilege-review-console"),
    path("console/content/", experience_views.content_console_view, name="experience-content-console"),
    path("academy/", experience_views.academy_view, name="experience-academy"),
    path("academy/challenges/<slug:challenge_code>/", experience_views.challenge_detail_view, name="experience-challenge-detail"),
    path("academy/challenges/<slug:challenge_code>/participation/", experience_views.challenge_enroll_view, name="experience-challenge-enroll"),
    path("academy/challenges/<slug:challenge_code>/result/", experience_views.challenge_result_submit_view, name="experience-challenge-result-submit"),
    path("console/challenges/", experience_views.challenge_admin_console_view, name="experience-challenge-admin-console"),
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    path("health/live/", security_views.live, name="health-live"),
    path("health/ready/", security_views.ready, name="health-ready"),
    path("metrics/", security_views.metrics, name="metrics"),
]
