from datetime import timedelta


from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.academy.models import Laboratory
from apps.academy.services import accept_current_ethics
from apps.experience.services import (
    academy_and_challenges,
    finance_console,
    organization_dashboard,
    public_portal,
    researcher_dashboard,
    triage_console,
)
from apps.identity.models import AuthenticationEvent, User
from apps.identity.services import grant_step_up
from apps.integrations.models import OidcEnterpriseConnection, TicketingIntegration
from apps.integrations.services import (
    authorize_api_key,
    export_compliance_audit,
    open_support_case,
    publish_content,
    queue_safe_notification,
    revoke_oidc_connection,
    simulate_oidc_callback,
    rotate_api_key,
    set_notification_preference,
    simulate_sla_escalations,
    support_case_view,
    sync_ticket_sandbox,
    create_api_key,
)
from apps.organizations.models import Organization, OrganizationMembership
from apps.programs.models import Program, ProgramServiceLevel
from apps.reputation.models import Challenge
from apps.reports.models import Report, ReportEvent, TriageDecision
from apps.reports.services import save_report_draft
from apps.reports.sla import collect_sla_escalations, ensure_report_sla_state, sla_metrics_for_program


class IntegrationsAndExperienceTests(TestCase):
    def setUp(self):
        self.researcher = User.objects.create_user(
            username="ux-researcher",
            email="ux-researcher@example.test",
            password="Complex-Password-731!",
            email_verified=True,
            platform_role=User.PlatformRole.RESEARCHER,
        )
        self.other_researcher = User.objects.create_user(
            username="ux-other",
            email="ux-other@example.test",
            password="Complex-Password-731!",
            platform_role=User.PlatformRole.RESEARCHER,
        )
        self.owner = User.objects.create_user(
            username="ux-owner",
            email="ux-owner@example.test",
            password="Complex-Password-731!",
            platform_role=User.PlatformRole.ORGANIZATION,
        )
        self.manager = User.objects.create_user(
            username="ux-manager",
            email="ux-manager@example.test",
            password="Complex-Password-731!",
            platform_role=User.PlatformRole.ORGANIZATION,
        )
        self.triager = User.objects.create_user(
            username="ux-triager",
            email="ux-triager@example.test",
            password="Complex-Password-731!",
            platform_role=User.PlatformRole.TRIAGER,
        )
        self.finance = User.objects.create_user(
            username="ux-finance",
            email="ux-finance@example.test",
            password="Complex-Password-731!",
            platform_role=User.PlatformRole.FINANCE,
        )
        self.security = User.objects.create_user(
            username="ux-security",
            email="ux-security@example.test",
            password="Complex-Password-731!",
            platform_role=User.PlatformRole.SECURITY,
        )
        self.admin = User.objects.create_user(
            username="ux-admin",
            email="ux-admin@example.test",
            password="Complex-Password-731!",
            platform_role=User.PlatformRole.ADMIN,
        )
        self.organization = Organization.objects.create(name="Organisation Intégrations", verification_status=Organization.VerificationStatus.VERIFIED)
        OrganizationMembership.objects.create(organization=self.organization, user=self.owner, role=OrganizationMembership.Role.OWNER)
        OrganizationMembership.objects.create(organization=self.organization, user=self.manager, role=OrganizationMembership.Role.PROGRAM_MANAGER)
        self.program = Program.objects.create(
            organization=self.organization,
            name="Programme Interface",
            status=Program.Status.PUBLIC_ACTIVE,
            policy_version="v1",
            policy_hash="policy-hash",
        )
        ProgramServiceLevel.objects.create(program=self.program, triage_hours=1)
        self.report = Report.objects.create(
            organization=self.organization,
            program=self.program,
            author=self.researcher,
            title="Rapport interface",
            asset="https://scope.example.test",
            status=Report.Status.SUBMITTED,
            policy_version="v1",
            policy_hash="policy-hash",
            idempotency_key="integrations-report-001",
        )

    def test_notification_preferences_sla_ticketing_oidc_and_api_key_rotation(self):
        set_notification_preference(
            user=self.owner,
            event_type="sla.escalation",
            channel="in_app",
            enabled=True,
            max_per_day=1,
            consented=True,
        )
        Report.objects.filter(pk=self.report.pk).update(created_at=timezone.now() - timedelta(hours=2))
        deliveries = simulate_sla_escalations(at=timezone.now())
        self.assertEqual(len(deliveries), 1)
        self.assertIsNone(
            queue_safe_notification(
                user=self.owner,
                event_type="sla.escalation",
                safe_reference="safe-ref",
                idempotency_key="notification-second-in-day",
            )
        )
        integration = TicketingIntegration.objects.create(organization=self.organization, project_reference="sandbox-project")
        first_sync = sync_ticket_sandbox(integration=integration, report=self.report, actor=self.manager, idempotency_key="ticket-sync-001")
        second_sync = sync_ticket_sandbox(integration=integration, report=self.report, actor=self.manager, idempotency_key="ticket-sync-001")
        self.assertEqual(first_sync.id, second_sync.id)
        connection = OidcEnterpriseConnection.objects.create(
            organization=self.organization,
            issuer="https://issuer.example.test",
            client_identifier="client-sandbox",
            scopes=["openid", "profile"],
        )
        callback = simulate_oidc_callback(connection=connection, issuer="https://issuer.example.test", subject="enterprise-user-001")
        self.assertEqual(callback["organization_id"], self.organization.id)
        revoke_oidc_connection(connection=connection, actor=self.owner)
        connection.refresh_from_db()
        self.assertFalse(connection.active)
        with self.assertRaises(PermissionDenied):
            simulate_oidc_callback(connection=connection, issuer="https://issuer.example.test", subject="enterprise-user-001")
        with self.assertRaises(PermissionDenied):
            create_api_key(owner=self.owner, label="API test", scopes=["report.read"])
        grant_step_up(user=self.owner, action="api_key.create")
        key, raw = create_api_key(owner=self.owner, label="API test", scopes=["report.read"])
        self.assertEqual(authorize_api_key(raw_key=raw, scope="report.read").id, key.id)
        with self.assertRaises(PermissionDenied):
            authorize_api_key(raw_key=raw, scope="payment.write")
        grant_step_up(user=self.owner, action="api_key.rotate")
        replacement, replacement_raw = rotate_api_key(key=key, actor=self.owner)
        with self.assertRaises(PermissionDenied):
            authorize_api_key(raw_key=raw, scope="report.read")
        self.assertEqual(authorize_api_key(raw_key=replacement_raw, scope="report.read").id, replacement.id)
        self.assertTrue(AuthenticationEvent.objects.filter(user=self.owner, event_type="action_gate.denied").exists())
        self.assertTrue(AuthenticationEvent.objects.filter(user=self.owner, event_type="action_gate.allowed").exists())

    def test_sla_tracks_each_commitment_and_escalates_once_without_external_delivery(self):
        service_level = self.program.service_level
        service_level.acknowledgement_hours = 1
        service_level.triage_hours = 2
        service_level.resolution_target_days = 1
        service_level.save()
        reference_time = timezone.now()
        Report.objects.filter(pk=self.report.pk).update(created_at=reference_time - timedelta(days=3))
        self.report.refresh_from_db()

        state = ensure_report_sla_state(report=self.report, at=reference_time)
        self.assertEqual(state.acknowledgement_state, "overdue")
        self.assertEqual(state.triage_state, "overdue")
        self.assertEqual(state.resolution_state, "overdue")
        first_escalations = collect_sla_escalations(at=reference_time)
        self.assertEqual({event.checkpoint for event in first_escalations}, {"acknowledgement", "triage", "resolution"})
        self.assertEqual(collect_sla_escalations(at=reference_time), [])

        ReportEvent.objects.create(
            report=self.report,
            actor=self.triager,
            from_status=Report.Status.SUBMITTED,
            to_status=Report.Status.IN_TRIAGE,
            reason="Accusé de réception local.",
        )
        TriageDecision.objects.create(
            report=self.report,
            decided_by=self.triager,
            business_priority=TriageDecision.BusinessPriority.MEDIUM,
            reward_eligibility=TriageDecision.RewardEligibility.UNDETERMINED,
            reason_code=TriageDecision.ReasonCode.PENDING,
            justification="Décision locale documentée.",
        )
        ReportEvent.objects.create(
            report=self.report,
            actor=self.triager,
            from_status=Report.Status.REMEDIATION,
            to_status=Report.Status.RESOLVED,
            reason="Résolution enregistrée localement.",
        )
        completed = ensure_report_sla_state(report=self.report, at=reference_time)
        self.assertEqual(completed.acknowledgement_state, "completed")
        self.assertEqual(completed.triage_state, "completed")
        self.assertEqual(completed.resolution_state, "completed")
        metrics = sla_metrics_for_program(program=self.program, at=reference_time)
        self.assertEqual(metrics["reports_total"], 1)
        self.assertEqual(metrics["acknowledgement"]["completed"], 1)
        self.assertEqual(metrics["escalations_total"], 3)

    def test_content_support_and_compliance_are_permissioned_and_masked(self):
        page = publish_content(actor=self.admin, slug="faq", title="FAQ", body="Texte public.", published=True)
        self.assertTrue(page.published)
        with self.assertRaises(PermissionDenied):
            publish_content(actor=self.researcher, slug="interdit", title="Interdit", body="Non.", published=True)
        case = open_support_case(requester=self.researcher, subject="Question", message="J’ai une question générale.")
        support_view = support_case_view(case=case, agent=self.security)
        self.assertFalse(support_view["proof_access"])
        with self.assertRaises(ValidationError):
            open_support_case(requester=self.researcher, subject="Secret", message="Voici un token secret.")
        export = export_compliance_audit(actor=self.admin, export_type="audit_summary")
        self.assertIn("audit_event_count", export)
        with self.assertRaises(PermissionDenied):
            export_compliance_audit(actor=self.security, export_type="audit_summary")

    def test_experience_contracts_limit_data_by_user_organization_and_console_role(self):
        other_report = Report.objects.create(
            organization=self.organization,
            program=self.program,
            author=self.other_researcher,
            title="Rapport d’autrui",
            asset="https://scope2.example.test",
            policy_version="v1",
            policy_hash="policy-hash",
            idempotency_key="integrations-report-002",
        )
        draft = save_report_draft(
            organization=self.organization,
            program=self.program,
            author=self.researcher,
            title="Brouillon validé",
            asset="https://scope.example.test",
            impact="Impact pédagogique.",
        )
        self.assertEqual(draft.author_id, self.researcher.id)
        dashboard = researcher_dashboard(user=self.researcher)
        self.assertEqual({item["id"] for item in dashboard["reports"]}, {self.report.id})
        self.assertNotIn(other_report.id, {item["id"] for item in dashboard["reports"]})
        self.assertEqual(organization_dashboard(user=self.owner, organization=self.organization)["reports_total"], 2)
        with self.assertRaises(PermissionDenied):
            organization_dashboard(user=self.researcher, organization=self.organization)
        self.assertIn("programs", public_portal())
        self.report.status = Report.Status.IN_TRIAGE
        self.report.save(update_fields=["status", "updated_at"])
        self.assertEqual(triage_console(user=self.triager)["reports"][0]["id"], self.report.id)
        with self.assertRaises(PermissionDenied):
            finance_console(user=self.triager)
        self.assertEqual(finance_console(user=self.finance)["entitlements"], [])
        with self.assertRaises(PermissionDenied):
            triage_console(user=self.finance)

    def test_academy_challenge_experience_requires_ethics_for_laboratories(self):
        Laboratory.objects.create(code="ui-lab", title="Laboratoire UI", fictional_scenario="Fictif seulement.")
        now = timezone.now()
        Challenge.objects.create(
            code="ui-challenge",
            title="Challenge UI",
            fictional_scenario="Fictif seulement.",
            rules_version="v1",
            rules_hash="rules-hash",
            starts_at=now - timedelta(hours=1),
            ends_at=now + timedelta(hours=2),
            status=Challenge.Status.OPEN,
        )
        initial = academy_and_challenges(user=self.researcher)
        self.assertFalse(initial["ethics_accepted"])
        self.assertEqual(initial["laboratories"], [])
        accept_current_ethics(learner=self.researcher)
        allowed = academy_and_challenges(user=self.researcher)
        self.assertTrue(allowed["ethics_accepted"])
        self.assertEqual(allowed["laboratories"][0]["code"], "ui-lab")
        self.assertEqual(allowed["challenges"][0]["code"], "ui-challenge")
