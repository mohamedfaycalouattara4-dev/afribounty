from pathlib import Path

from django.core.exceptions import ValidationError
from django.test import TestCase
from datetime import timedelta

from django.utils import timezone

from apps.academy.models import EthicsAcceptance, Laboratory
from apps.academy.services import CURRENT_ETHICS_RULES_HASH, accept_current_ethics
from apps.identity.models import AccountPrivacyPreference, AccountProfile, MfaStepUpGrant, User, UserSession
from apps.identity.services import grant_step_up
from apps.integrations.local_notifications import create_local_notification
from apps.integrations.models import ApiKey, LocalNotification
from apps.organizations.models import (
    ConflictDeclaration,
    Organization,
    OrganizationChangeEvent,
    OrganizationMembership,
    OrganizationVerification,
    SecurityContact,
)
from apps.readiness.models import GoNoGoAssessment, ReadinessCheck, ResilienceExercise
from apps.programs.models import AssetOwnershipProof, AssetScope, Program, ProgramDecisionEvent, ProgramPolicyVersion, ProgramServiceLevel
from apps.reports.models import FixValidation, MediationCase, Report, ReportEvent, SeverityAssessment, TriageAssignment, TriageDecision, TriageExportEvent
from apps.reputation.models import Challenge, ChallengeEnrollment, ReputationEvent, ReputationSeason
from apps.reputation.services import append_reputation_event, rebuild_profiles
from apps.reports.models import ReportDraft
from apps.rewards.models import BeneficiaryProfile, PaymentOrder, RewardEntitlement
from apps.security.models import PrivilegeReviewSnapshot


class ExperienceHttpTests(TestCase):
    def setUp(self):
        self.researcher = User.objects.create_user(
            username="http-researcher",
            email="http-researcher@example.test",
            password="Complex-Password-731!",
            email_verified=True,
            platform_role=User.PlatformRole.RESEARCHER,
        )
        self.owner = User.objects.create_user(
            username="http-owner",
            email="http-owner@example.test",
            password="Complex-Password-731!",
            platform_role=User.PlatformRole.ORGANIZATION,
        )
        self.triager = User.objects.create_user(
            username="http-triager",
            email="http-triager@example.test",
            password="Complex-Password-731!",
            platform_role=User.PlatformRole.TRIAGER,
        )
        self.finance = User.objects.create_user(
            username="http-finance",
            email="http-finance@example.test",
            password="Complex-Password-731!",
            platform_role=User.PlatformRole.FINANCE,
        )
        self.security = User.objects.create_user(
            username="http-security",
            email="http-security@example.test",
            password="Complex-Password-731!",
            email_verified=True,
            platform_role=User.PlatformRole.SECURITY,
        )
        self.admin = User.objects.create_user(
            username="http-admin",
            email="http-admin@example.test",
            password="Complex-Password-731!",
            platform_role=User.PlatformRole.ADMIN,
        )
        self.organization = Organization.objects.create(name="Organisation HTTP", verification_status=Organization.VerificationStatus.VERIFIED)
        OrganizationMembership.objects.create(organization=self.organization, user=self.owner, role=OrganizationMembership.Role.OWNER)
        self.program = Program.objects.create(
            organization=self.organization,
            name="Programme HTTP",
            status=Program.Status.PUBLIC_ACTIVE,
            policy_version="v1",
            policy_hash="policy-http",
        )
        self.scope = AssetScope.objects.create(
            program=self.program,
            asset="https://app.organisation-http.test",
            asset_type=AssetScope.AssetType.WEB,
            is_verified=True,
        )
        AssetOwnershipProof.objects.create(
            scope=self.scope,
            evidence_reference="http-ownership-proof",
            reviewed_by_reference="http-reviewer",
            approved_at=timezone.now(),
        )
        ProgramPolicyVersion.objects.create(
            program=self.program,
            version="v1",
            content_hash="policy-http",
            safe_harbor_text="Les tests autorisés doivent être non destructifs et rester strictement dans le scope publié.",
            active=True,
        )
        AccountProfile.objects.create(
            user=self.researcher,
            display_name="Chercheur HTTP",
            country_code="BF",
            account_intent=AccountProfile.AccountIntent.RESEARCHER,
        )

    def test_public_portal_includes_french_language_skip_link_viewport_and_mobile_focus_styles(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<html lang="fr">', html=False)
        self.assertContains(response, "Aller au contenu principal")
        self.assertContains(response, 'name="viewport"', html=False)
        self.assertContains(response, f"/programs/{self.program.id}/")
        stylesheet = Path("apps/experience/static/experience/afribounty.css").read_text()
        self.assertIn(":focus-visible", stylesheet)
        self.assertIn("@media (max-width:720px)", stylesheet)

    def test_public_program_detail_shows_only_verified_public_rules_and_scope(self):
        detail_url = f"/programs/{self.program.id}/"
        response = self.client.get(detail_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Règles d’engagement")
        self.assertContains(response, "tests autorisés doivent être non destructifs")
        self.assertContains(response, "https://app.organisation-http.test")
        self.assertContains(response, "/access/login/")

        private_program = Program.objects.create(
            organization=self.organization,
            name="Programme privé HTTP",
            status=Program.Status.PRIVATE_ACTIVE,
            policy_version="v1",
            policy_hash="private-policy-http",
        )
        self.assertEqual(self.client.get(f"/programs/{private_program.id}/").status_code, 404)

    def test_researcher_onboarding_dashboard_and_draft_form_are_authenticated_and_scoped(self):
        self.client.force_login(self.researcher)
        self.assertEqual(self.client.get("/onboarding/researcher/").status_code, 200)
        EthicsAcceptance.objects.create(learner=self.researcher, rules_version="ethics-v0", rules_hash="legacy-rules-hash")
        dashboard = self.client.get("/dashboard/researcher/")
        self.assertEqual(dashboard.status_code, 200)
        self.assertContains(dashboard, "Programme HTTP")
        self.assertNotContains(dashboard, f"/reports/draft/{self.program.id}/")
        self.assertContains(dashboard, "Accepter l’éthique pour préparer un brouillon")
        self.assertNotContains(dashboard, 'href="/organization/"')
        self.assertContains(dashboard, "/settings/profile/")
        draft_url = f"/reports/draft/{self.program.id}/"
        self.assertEqual(self.client.get(draft_url).status_code, 403)
        academy = self.client.post("/academy/", {"ethics_confirmation": "on"})
        self.assertRedirects(academy, "/academy/")
        self.assertTrue(EthicsAcceptance.objects.filter(learner=self.researcher, rules_hash=CURRENT_ETHICS_RULES_HASH).exists())
        self.assertContains(self.client.get("/dashboard/researcher/"), f"/reports/draft/{self.program.id}/")
        response = self.client.post(
            draft_url,
            {"title": "Brouillon HTTP", "asset": "https://scope.example.test", "impact": "Impact", "proposed_severity": "high"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(ReportDraft.objects.filter(program=self.program, author=self.researcher, title="Brouillon HTTP").exists())
        self.assertContains(self.client.get(draft_url), "Étapes de reproduction")
        self.assertContains(self.client.get("/dashboard/researcher/"), "Reprendre")

    def test_researcher_reviews_and_submits_a_scoped_draft_idempotently(self):
        self.client.force_login(self.researcher)
        self.client.post("/academy/", {"ethics_confirmation": "on"})
        draft_url = f"/reports/draft/{self.program.id}/"
        self.client.post(
            draft_url,
            {
                "title": "Rapport final HTTP",
                "asset": self.scope.asset,
                "impact": "Impact documenté dans la démonstration.",
                "reproduction": "Étapes contrôlées de démonstration.",
                "proposed_severity": "medium",
            },
        )
        review_url = f"/reports/draft/{self.program.id}/review/"
        review = self.client.get(review_url)
        self.assertContains(review, "Vérifier avant soumission")
        key = "idempotency-key-http-0001"
        response = self.client.post(review_url, {"confirmed_rules": "on", "submission_key": key})
        report = Report.objects.get(program=self.program, author=self.researcher, idempotency_key=key)
        self.assertRedirects(response, f"/reports/{report.id}/")
        self.assertEqual(report.status, Report.Status.SUBMITTED)
        self.assertEqual(report.impact, "Impact documenté dans la démonstration.")
        self.assertEqual(report.reproduction, "Étapes contrôlées de démonstration.")
        self.assertEqual(report.proposed_severity, "medium")
        self.assertTrue(ReportEvent.objects.filter(report=report, to_status=Report.Status.SUBMITTED).exists())
        self.client.post(review_url, {"confirmed_rules": "on", "submission_key": key})
        self.assertEqual(Report.objects.filter(program=self.program, author=self.researcher, idempotency_key=key).count(), 1)
        report_detail = self.client.get(f"/reports/{report.id}/")
        self.assertContains(report_detail, "Rapport privé")
        self.assertContains(report_detail, "Soumis")
        self.assertNotContains(report_detail, "submitted")
        self.assertContains(report_detail, "Impact documenté dans la démonstration.")
        self.assertContains(report_detail, "Étapes contrôlées de démonstration.")
        self.assertContains(self.client.get("/dashboard/researcher/"), f"/reports/{report.id}/")
        other_researcher = User.objects.create_user(
            username="other-report-reader",
            email="other-report-reader@example.test",
            password="Complex-Password-731!",
            email_verified=True,
            platform_role=User.PlatformRole.RESEARCHER,
        )
        self.client.force_login(other_researcher)
        self.assertEqual(self.client.get(f"/reports/{report.id}/").status_code, 404)

    def test_researcher_can_update_basic_profile_settings_and_organization_cannot_open_researcher_dashboard(self):
        self.client.force_login(self.researcher)
        response = self.client.post("/settings/profile/", {"display_name": "Awa Teste", "country_code": "CI"})
        self.assertRedirects(response, "/settings/profile/")
        self.researcher.account_profile.refresh_from_db()
        self.assertEqual(self.researcher.account_profile.display_name, "Awa Teste")
        self.assertEqual(self.researcher.account_profile.country_code, "CI")

        self.client.force_login(self.owner)
        self.assertEqual(self.client.get("/dashboard/researcher/").status_code, 403)
        self.assertEqual(self.client.get("/settings/profile/").status_code, 403)

    def test_organization_triage_finance_and_academy_routes_enforce_permissions(self):
        self.client.force_login(self.owner)
        organization_dashboard = self.client.get(f"/dashboard/organization/{self.organization.id}/")
        self.assertEqual(organization_dashboard.status_code, 200)
        self.assertContains(organization_dashboard, 'href="/organization/"', html=False)
        self.assertContains(organization_dashboard, "Mon organisation")
        self.assertNotContains(organization_dashboard, 'href="/dashboard/researcher/"', html=False)
        self.client.force_login(self.researcher)
        self.assertEqual(self.client.get(f"/dashboard/organization/{self.organization.id}/").status_code, 403)
        self.client.force_login(self.triager)
        self.assertEqual(self.client.get("/console/triage/").status_code, 200)
        self.assertEqual(self.client.get("/console/finance/").status_code, 403)
        self.client.force_login(self.finance)
        self.assertEqual(self.client.get("/console/finance/").status_code, 200)
        self.assertEqual(self.client.get("/console/triage/").status_code, 403)
        Laboratory.objects.create(code="http-lab", title="Laboratoire HTTP", fictional_scenario="Fictif.")
        Challenge.objects.create(
            code="http-challenge",
            title="Challenge HTTP",
            fictional_scenario="Fictif.",
            rules_version="v1",
            rules_hash="rules-http",
            starts_at="2026-01-01T00:00:00Z",
            ends_at="2026-12-31T00:00:00Z",
            status=Challenge.Status.OPEN,
        )
        self.client.force_login(self.researcher)
        self.assertContains(self.client.get("/academy/"), "Laboratoires indisponibles")
        accept_current_ethics(learner=self.researcher)
        self.assertContains(self.client.get("/academy/"), "Laboratoire HTTP")

    def test_reputation_and_isolated_challenge_are_consultable_with_local_participation(self):
        season = ReputationSeason.objects.create(
            code="http-saison",
            starts_at="2026-01-01T00:00:00Z",
            ends_at="2026-12-31T00:00:00Z",
            active=True,
        )
        append_reputation_event(
            user=self.researcher,
            season=season,
            event_type=ReputationEvent.EventType.REPORT_ACCEPTED,
            points=60,
            source_reference="report-http-1",
            idempotency_key="reputation-http-1",
            reason="Rapport de test accepté.",
        )
        rebuild_profiles(season=season)
        challenge = Challenge.objects.create(
            code="challenge-isole-http",
            title="Challenge isolé HTTP",
            fictional_scenario="Scénario local fictif sans cible externe.",
            rules_version="v2",
            rules_hash="rules-isolated-http",
            starts_at="2026-01-01T00:00:00Z",
            ends_at="2026-12-31T00:00:00Z",
            status=Challenge.Status.OPEN,
            is_isolated=True,
            contains_external_target=False,
        )
        external = Challenge.objects.create(
            code="challenge-externe-http",
            title="Challenge externe interdit",
            fictional_scenario="Ne doit jamais être exposé.",
            rules_version="v1",
            rules_hash="rules-external-http",
            starts_at="2026-01-01T00:00:00Z",
            ends_at="2026-12-31T00:00:00Z",
            status=Challenge.Status.OPEN,
            is_isolated=False,
            contains_external_target=True,
        )
        self.client.force_login(self.researcher)
        reputation = self.client.get("/reputation/")
        self.assertContains(reputation, "http-saison")
        self.assertContains(reputation, "60")
        self.assertContains(reputation, "1")
        academy = self.client.get("/academy/")
        self.assertContains(academy, challenge.title)
        self.assertNotContains(academy, external.title)
        detail_url = f"/academy/challenges/{challenge.code}/"
        detail = self.client.get(detail_url)
        self.assertContains(detail, "Scénario local fictif sans cible externe.")
        self.assertContains(detail, "Participer à l’exercice")
        self.assertEqual(self.client.get(f"/academy/challenges/{external.code}/").status_code, 404)
        enrolled = self.client.post(f"/academy/challenges/{challenge.code}/participation/")
        self.assertRedirects(enrolled, detail_url)
        self.assertTrue(ChallengeEnrollment.objects.filter(challenge=challenge, learner=self.researcher).exists())
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get("/reputation/").status_code, 403)
        self.assertEqual(self.client.post(f"/academy/challenges/{challenge.code}/participation/").status_code, 403)

    def test_reward_entitlement_beneficiary_and_finance_sandbox_flow_are_visible_and_controlled(self):
        report = Report.objects.create(
            organization=self.organization,
            program=self.program,
            author=self.researcher,
            title="Rapport éligible à récompense sandbox",
            asset=self.scope.asset,
            impact="Impact fictif validé.",
            reproduction="Étapes fictives validées.",
            status=Report.Status.VALID,
            policy_version="v1",
            policy_hash="policy-http",
            idempotency_key="reward-http-0001",
        )
        TriageAssignment.objects.create(
            report=report,
            assigned_to=self.triager,
            queue=TriageAssignment.Queue.TECHNICAL,
            reason="Attribution pour droit à récompense sandbox.",
        )
        TriageDecision.objects.create(
            report=report,
            decided_by=self.triager,
            business_priority=TriageDecision.BusinessPriority.HIGH,
            reward_eligibility=TriageDecision.RewardEligibility.ELIGIBLE,
            justification="Éligibilité fictive contrôlée.",
        )
        self.client.force_login(self.triager)
        triage_detail = f"/console/triage/reports/{report.id}/"
        created = self.client.post(
            triage_detail,
            {"action": "reward_entitlement", "amount_xof": "50000", "rationale": "Récompense locale de test."},
        )
        self.assertRedirects(created, triage_detail)
        entitlement = RewardEntitlement.objects.get(report=report)
        self.assertEqual(entitlement.status, RewardEntitlement.Status.PENDING)
        self.client.force_login(self.researcher)
        self.assertEqual(self.client.post("/settings/beneficiary/", {"recipient_reference": "demo-beneficiary-http"}).status_code, 200)
        grant_step_up(user=self.researcher, action="beneficiary.change")
        beneficiary = self.client.post("/settings/beneficiary/", {"recipient_reference": "demo-beneficiary-http"})
        self.assertRedirects(beneficiary, "/settings/beneficiary/")
        profile = BeneficiaryProfile.objects.get(user=self.researcher)
        self.assertEqual(profile.verification_status, BeneficiaryProfile.VerificationStatus.PENDING)
        self.client.force_login(self.finance)
        finance = self.client.get("/console/finance/")
        self.assertContains(finance, "Droit à récompense")
        self.assertContains(finance, "50")
        verified = self.client.post(
            "/console/finance/",
            {"action": "beneficiary_verify", "entitlement_id": entitlement.id, "beneficiary_profile_id": profile.id},
        )
        self.assertRedirects(verified, "/console/finance/")
        approved = self.client.post(
            "/console/finance/",
            {"action": "approval", "entitlement_id": entitlement.id, "approved": "yes", "reason": "Contrôle finance local."},
        )
        self.assertRedirects(approved, "/console/finance/")
        entitlement.refresh_from_db()
        self.assertEqual(entitlement.status, RewardEntitlement.Status.APPROVED)
        ordered = self.client.post("/console/finance/", {"action": "sandbox_order", "entitlement_id": entitlement.id})
        self.assertRedirects(ordered, "/console/finance/")
        order = PaymentOrder.objects.get(entitlement=entitlement)
        self.assertEqual(order.status, PaymentOrder.Status.SUBMITTED)
        self.assertEqual(order.provider_code, "sandbox-money")
        self.assertEqual(self.client.get("/settings/beneficiary/").status_code, 403)

    def test_local_notification_inbox_is_private_and_marks_only_own_notifications_as_read(self):
        notification, _ = create_local_notification(
            user=self.researcher,
            event_type=LocalNotification.EventType.REPORT,
            title="Rapport transmis à la file locale",
            body="Le suivi est disponible dans l’espace privé.",
            safe_reference="report:local-1",
            idempotency_key="notification-http-researcher-1",
        )
        create_local_notification(
            user=self.owner,
            event_type=LocalNotification.EventType.REWARD,
            title="Notification d’un autre compte",
            body="Ne doit pas être divulguée.",
            safe_reference="reward:other",
            idempotency_key="notification-http-owner-1",
        )
        self.client.force_login(self.researcher)
        inbox = self.client.get("/notifications/")
        self.assertContains(inbox, "Rapport transmis à la file locale")
        self.assertContains(inbox, "report:local-1")
        self.assertNotContains(inbox, "Notification d’un autre compte")
        marked = self.client.post("/notifications/", {"notification_id": notification.id})
        self.assertRedirects(marked, "/notifications/")
        notification.refresh_from_db()
        self.assertIsNotNone(notification.read_at)

    def test_researcher_and_organization_can_store_only_their_own_privacy_and_export_preferences(self):
        self.client.force_login(self.researcher)
        researcher_privacy = self.client.post("/settings/privacy/", {"retention_days": "730", "exports_enabled": "on"})
        self.assertRedirects(researcher_privacy, "/settings/privacy/")
        preference = AccountPrivacyPreference.objects.get(user=self.researcher)
        self.assertEqual(preference.retention_days, 730)
        self.assertTrue(preference.exports_enabled)
        self.client.force_login(self.owner)
        organization_privacy = self.client.post(
            f"/organization/{self.organization.id}/settings/",
            {"action": "privacy", "privacy_retention_days": "540", "exports_enabled": "on"},
        )
        self.assertRedirects(organization_privacy, f"/organization/{self.organization.id}/settings/")
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.privacy_retention_days, 540)
        self.assertTrue(self.organization.exports_enabled)
        self.client.force_login(self.triager)
        self.assertEqual(self.client.get("/settings/privacy/").status_code, 403)

    def test_administrator_reviews_scope_before_separate_program_publication(self):
        program = Program.objects.create(
            organization=self.organization,
            name="Programme brouillon revue admin",
            status=Program.Status.DRAFT,
            policy_version="draft-v1",
            policy_hash="draft-policy-admin-http",
            safe_harbor_version="draft-v1",
        )
        scope = AssetScope.objects.create(
            program=program,
            asset="https://scope-revue-admin.example.test",
            asset_type=AssetScope.AssetType.WEB,
            is_verified=False,
        )
        policy = ProgramPolicyVersion.objects.create(
            program=program,
            version="draft-v1",
            content_hash="draft-policy-admin-http",
            safe_harbor_text="Politique de démonstration suffisamment détaillée pour la revue administrative locale.",
            active=False,
        )
        self.client.force_login(self.admin)
        admin_console = self.client.get("/console/administration/")
        self.assertContains(admin_console, program.name)
        reviewed = self.client.post(
            "/console/administration/",
            {
                "action": "scope_review",
                "scope_id": scope.id,
                "evidence_reference": "evidence-local-admin-001",
                "reviewer_reference": "review-admin-001",
            },
        )
        self.assertRedirects(reviewed, "/console/administration/")
        scope.refresh_from_db()
        self.assertTrue(scope.is_verified)
        self.assertIsNotNone(scope.ownership_proof.approved_at)
        published = self.client.post(
            "/console/administration/",
            {"action": "program_publish", "program_id": program.id, "reviewer_reference": "publish-admin-001"},
        )
        self.assertRedirects(published, "/console/administration/")
        program.refresh_from_db()
        policy.refresh_from_db()
        self.assertEqual(program.status, Program.Status.PUBLIC_ACTIVE)
        self.assertTrue(policy.active)
        self.assertTrue(ProgramDecisionEvent.objects.filter(program=program, action="program.published_after_review").exists())
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post("/console/administration/", {"action": "program_publish", "program_id": program.id}).status_code, 403)

    def test_security_or_admin_can_use_readiness_console_while_operational_roles_are_refused(self):
        url = "/console/administration/readiness/"
        for user in (self.researcher, self.owner, self.triager, self.finance):
            self.client.force_login(user)
            self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.security)
        self.assertContains(self.client.get(url), "Cockpit de préparation et résilience")
        self.assertContains(self.client.get(url), "Intégrité des scopes de rapports")
        self.assertContains(self.client.get(url), "Intégrité HMAC du journal d’audit")
        self.assertContains(self.client.get(url), "État consolidé d’intégrité")
        self.assertContains(self.client.get(url), "Contrôles regroupés")
        self.assertNotContains(self.client.get(url), self.security.email)
        response = self.client.post(url, {"action": "integrity_snapshot"})
        self.assertRedirects(response, url)
        integrity_snapshot = ReadinessCheck.objects.get(check_code="integrity_consolidated")
        self.assertEqual(integrity_snapshot.recorded_by, self.security)
        self.assertTrue(integrity_snapshot.evidence["calculated_locally"])
        self.assertFalse(integrity_snapshot.evidence["external_service_called"])
        self.assertFalse(integrity_snapshot.evidence["automatic_remediation_performed"])
        history_page = self.client.get(url)
        self.assertContains(history_page, "Historique local des instantanés consolidés")
        self.assertContains(history_page, integrity_snapshot.evidence["evidence_digest"][:12])
        self.assertNotContains(history_page, self.security.email)
        response = self.client.post(
            url,
            {"action": "readiness_check", "check_code": "unit_tests", "status": "pass", "reference": "security-http-001"},
        )
        self.assertRedirects(response, url)
        check = ReadinessCheck.objects.get(check_code="unit_tests")
        self.assertEqual(check.recorded_by, self.security)
        self.assertTrue(check.evidence["external_service_called"] is False)
        response = self.client.post(
            url,
            {"action": "resilience_simulation", "dependency": "external_provider", "operation": "file attente locale"},
        )
        self.assertRedirects(response, url)
        exercise = ResilienceExercise.objects.get(dependency="external_provider")
        self.assertTrue(exercise.evidence["simulated"])
        self.assertTrue(exercise.evidence["no_real_dependency_was_disabled"])
        response = self.client.post(url, {"action": "go_no_go_local"})
        self.assertRedirects(response, url)
        assessment = GoNoGoAssessment.objects.latest("id")
        self.assertEqual(assessment.status, "pending_human_decision")
        page = self.client.get(url)
        self.assertContains(page, "audit_externe_preproduction")
        self.assertContains(page, "Fournisseur externe")

    def test_security_or_admin_can_view_aggregate_privilege_review_without_identifiers_or_auto_remediation(self):
        url = "/console/administration/privileges/"
        now = timezone.now()
        UserSession.objects.create(
            user=self.security,
            session_key_hash="s" * 64,
            device_label="poste-local-a-ne-pas-afficher",
            expires_at=now - timedelta(minutes=1),
        )
        ApiKey.objects.create(
            owner=self.security,
            label="cle-locale-a-ne-pas-afficher",
            key_prefix="abpriv001",
            secret_hash="k" * 64,
            scopes=["reports:read"],
            expires_at=now - timedelta(minutes=1),
        )
        MfaStepUpGrant.objects.create(
            user=self.security,
            action="security.local_review",
            verified_at=now - timedelta(minutes=1),
            expires_at=now + timedelta(minutes=5),
        )
        for user in (self.researcher, self.owner, self.triager, self.finance):
            self.client.force_login(user)
            self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.security)
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Revue locale des privilèges")
        self.assertContains(page, "Sessions expirées non révoquées")
        self.assertContains(page, "Clés API expirées non révoquées")
        self.assertContains(page, "Grants MFA actifs")
        self.assertNotContains(page, self.security.email)
        self.assertNotContains(page, "poste-local-a-ne-pas-afficher")
        self.assertNotContains(page, "abpriv001")
        self.assertNotContains(page, "k" * 64)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_security_or_admin_can_view_local_integrity_console_without_individual_data(self):
        url = "/console/administration/integrity/"
        for user in (self.researcher, self.owner, self.triager, self.finance):
            self.client.force_login(user)
            self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.security)
        page = self.client.get(url)
        self.assertContains(page, "Vérification consolidée d’intégrité locale")
        self.assertContains(page, "audit_hmac")
        self.assertNotContains(page, self.security.email)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_security_can_archive_an_append_only_aggregate_privilege_review_snapshot(self):
        url = "/console/administration/privileges/"
        self.client.force_login(self.security)
        response = self.client.post(url, {"review_reference": "privilege-review-http-001"})
        self.assertRedirects(response, url)
        archived = PrivilegeReviewSnapshot.objects.get(review_reference="privilege-review-http-001")
        self.assertEqual(archived.recorded_by, self.security)
        self.assertEqual(len(archived.snapshot_digest), 64)
        self.assertIn("active_user_sessions", archived.snapshot)
        self.assertNotIn("email", str(archived.snapshot))
        archived.review_reference = "modification-interdite"
        with self.assertRaises(ValidationError):
            archived.save()
        page = self.client.get(url)
        self.assertContains(page, "Historique append-only")
        self.assertContains(page, "privilege-review-http-001")

    def test_triager_can_claim_assess_decide_and_transition_an_unassigned_submitted_report(self):
        report = Report.objects.create(
            organization=self.organization,
            program=self.program,
            author=self.researcher,
            title="Rapport à trier HTTP",
            asset=self.scope.asset,
            impact="Impact fictif pour la file de triage.",
            reproduction="Étapes fictives et non destructives.",
            policy_version="v1",
            policy_hash="policy-http",
            idempotency_key="triage-http-report-0001",
        )
        detail_url = f"/console/triage/reports/{report.id}/"
        self.client.force_login(self.triager)
        console = self.client.get("/console/triage/")
        self.assertContains(console, "Rapport à trier HTTP")
        self.assertContains(console, detail_url)
        self.assertContains(console, 'href="/console/triage/"', html=False)
        self.assertNotContains(console, 'href="/dashboard/researcher/"', html=False)
        self.assertContains(self.client.get(detail_url), "Prendre en charge")

        claim = self.client.post(
            detail_url,
            {"action": "claim", "queue": TriageAssignment.Queue.TECHNICAL, "reason": "Prise en charge fictive pour contrôle local."},
        )
        self.assertRedirects(claim, detail_url)
        report.refresh_from_db()
        self.assertEqual(report.status, Report.Status.IN_TRIAGE)
        self.assertEqual(report.triage_assignment.assigned_to, self.triager)
        related = Report.objects.create(
            organization=self.organization,
            program=self.program,
            author=self.researcher,
            title="Rapport lié HTTP",
            asset="https://related-http.example.test",
            impact="Impact lié de test.",
            reproduction="Reproduction liée de test.",
            policy_version=report.policy_version,
            policy_hash=report.policy_hash,
            idempotency_key="related-triage-http-0001",
            status=Report.Status.IN_TRIAGE,
        )
        related_detail = self.client.get(detail_url)
        self.assertContains(related_detail, "Relations de cause racine")
        relation = self.client.post(
            detail_url,
            {
                "action": "relation",
                "related_report_id": related.id,
                "relation_type": "additional_impact",
                "rationale": "Même cause racine confirmée par le triage de test.",
            },
        )
        self.assertRedirects(relation, detail_url)
        self.assertContains(self.client.get(detail_url), "Même cause racine confirmée par le triage de test.")

        self.client.post(
            detail_url,
            {
                "action": "severity",
                "technical_severity": SeverityAssessment.TechnicalSeverity.HIGH,
                "scoring_vector": "CVSS:3.1/AV:N",
                "justification": "Évaluation fictive, sans cible réelle.",
            },
        )
        self.assertTrue(SeverityAssessment.objects.filter(report=report, evaluator=self.triager).exists())
        self.client.post(
            detail_url,
            {
                "action": "decision",
                "business_priority": TriageDecision.BusinessPriority.HIGH,
                "reward_eligibility": TriageDecision.RewardEligibility.UNDETERMINED,
                "reason_code": TriageDecision.ReasonCode.VALID_CONFIRMED,
                "justification": "Décision métier fictive séparée de tout paiement.",
            },
        )
        decision = TriageDecision.objects.get(report=report, decided_by=self.triager)
        self.assertEqual(decision.reason_code, TriageDecision.ReasonCode.VALID_CONFIRMED)
        self.assertContains(self.client.get(detail_url), "Vulnérabilité confirmée")
        transition = self.client.post(
            detail_url,
            {"action": "transition", "target_status": Report.Status.VALID, "reason": "Rapport fictif validé après contrôle local."},
        )
        self.assertRedirects(transition, detail_url)
        report.refresh_from_db()
        self.assertEqual(report.status, Report.Status.VALID)
        self.assertTrue(ReportEvent.objects.filter(report=report, to_status=Report.Status.VALID).exists())

        self.client.force_login(self.owner)
        organization_dashboard = self.client.get(f"/dashboard/organization/{self.organization.id}/")
        self.assertContains(organization_dashboard, "Rapport à trier HTTP")
        self.assertContains(organization_dashboard, "Validé")

        self.client.force_login(self.triager)
        remediation_start = self.client.post(
            detail_url,
            {
                "action": "remediation_start",
                "remediation_owner_id": self.owner.id,
                "target_due_at": (timezone.now() + timedelta(days=7)).isoformat(),
                "remediation_plan": "Plan fictif de correction contrôlée.",
            },
        )
        self.assertRedirects(remediation_start, detail_url)
        report.refresh_from_db()
        remediation = report.remediation
        self.assertEqual(report.status, Report.Status.REMEDIATION)
        self.assertEqual(remediation.owner, self.owner)

        self.client.force_login(self.owner)
        submit_fix_url = f"/organization/{self.organization.id}/reports/{report.id}/remediation/submit/"
        submitted_fix = self.client.post(submit_fix_url)
        self.assertRedirects(submitted_fix, f"/organization/{self.organization.id}/reports/{report.id}/")
        remediation.refresh_from_db()
        self.assertEqual(remediation.status, "ready_for_validation")

        self.client.force_login(self.triager)
        validated_fix = self.client.post(
            detail_url,
            {
                "action": "remediation_validate",
                "validation_outcome": FixValidation.Outcome.ACCEPTED,
                "validation_notes": "Validation fictive par un rôle distinct du propriétaire.",
            },
        )
        self.assertRedirects(validated_fix, detail_url)
        report.refresh_from_db()
        self.assertEqual(report.status, Report.Status.RESOLVED)

        self.client.force_login(self.researcher)
        self.assertEqual(self.client.get("/console/triage/").status_code, 403)
        self.assertEqual(self.client.get(detail_url).status_code, 403)

    def test_researcher_mediation_request_requires_two_distinct_triage_reviewers(self):
        report = Report.objects.create(
            organization=self.organization,
            program=self.program,
            author=self.researcher,
            title="Rapport de médiation HTTP",
            asset=self.scope.asset,
            impact="Impact fictif pour médiation.",
            reproduction="Étapes fictives pour médiation.",
            policy_version="v1",
            policy_hash="policy-http",
            idempotency_key="mediation-http-report-0001",
        )
        TriageDecision.objects.create(
            report=report,
            decided_by=self.triager,
            business_priority=TriageDecision.BusinessPriority.MEDIUM,
            reward_eligibility=TriageDecision.RewardEligibility.UNDETERMINED,
            justification="Décision initiale fictive.",
        )
        self.client.force_login(self.researcher)
        request_url = f"/reports/{report.id}/mediation/"
        requested = self.client.post(request_url, {"reason": "Demande de médiation fictive et motivée."})
        self.assertRedirects(requested, f"/reports/{report.id}/")
        mediation = MediationCase.objects.get(report=report)
        self.assertEqual(mediation.initial_decider, self.triager)
        self.assertContains(self.client.get(f"/reports/{report.id}/"), "Médiation")

        mediator = User.objects.create_user(
            username="http-mediator",
            email="http-mediator@example.test",
            password="Complex-Password-731!",
            email_verified=True,
            platform_role=User.PlatformRole.TRIAGER,
        )
        reviewer = User.objects.create_user(
            username="http-reviewer",
            email="http-reviewer@example.test",
            password="Complex-Password-731!",
            email_verified=True,
            platform_role=User.PlatformRole.TRIAGER,
        )
        self.client.force_login(mediator)
        detail_url = f"/console/triage/reports/{report.id}/"
        decided = self.client.post(
            detail_url,
            {"action": "mediation_decision", "independent_reviewer_id": reviewer.id, "mediation_decision": "Décision fictive après second regard indépendant."},
        )
        self.assertRedirects(decided, detail_url)
        mediation.refresh_from_db()
        self.assertEqual(mediation.status, MediationCase.Status.DECIDED)
        self.assertEqual(mediation.mediator, mediator)
        self.assertEqual(mediation.independent_reviewer, reviewer)

    def test_triage_console_lists_only_the_triagers_valid_report_for_remediation(self):
        report = Report.objects.create(
            organization=self.organization,
            program=self.program,
            author=self.researcher,
            title="Rapport validé visible pour remédiation",
            asset=self.scope.asset,
            impact="Impact fictif de remédiation.",
            reproduction="Étapes fictives de remédiation.",
            status=Report.Status.VALID,
            policy_version="v1",
            policy_hash="policy-http",
            idempotency_key="valid-remediation-http-0001",
        )
        TriageAssignment.objects.create(
            report=report,
            assigned_to=self.triager,
            queue=TriageAssignment.Queue.TECHNICAL,
            reason="Attribution fictive pour remédiation.",
        )
        other_triager = User.objects.create_user(
            username="other-triager",
            email="other-triager@example.test",
            password="Complex-Password-731!",
            email_verified=True,
            platform_role=User.PlatformRole.TRIAGER,
        )
        self.client.force_login(self.triager)
        own_console = self.client.get("/console/triage/")
        self.assertContains(own_console, "Rapport validé visible pour remédiation")
        self.assertContains(own_console, "Validé")
        self.client.force_login(other_triager)
        self.assertNotContains(self.client.get("/console/triage/"), "Rapport validé visible pour remédiation")

    def test_owner_can_view_and_export_only_aggregate_triage_metrics_for_own_organization(self):
        self.organization.exports_enabled = True
        self.organization.save(update_fields=["exports_enabled"])
        report = Report.objects.create(
            organization=self.organization,
            program=self.program,
            author=self.researcher,
            title="Contenu confidentiel non exportable",
            asset="https://never-export-this.example.test",
            impact="Impact confidentiel.",
            reproduction="Étapes confidentielles.",
            status=Report.Status.IN_TRIAGE,
            policy_version="v1",
            policy_hash="policy-http",
            idempotency_key="aggregate-http-0001",
        )
        metrics_url = f"/organization/{self.organization.id}/triage/metrics/?program_id={self.program.id}"
        self.client.force_login(self.owner)
        metrics = self.client.get(metrics_url)
        self.assertEqual(metrics.status_code, 200)
        self.assertContains(metrics, "Indicateurs de triage")
        self.assertContains(metrics, "Cockpit SLA local")
        self.assertContains(metrics, "Accusé de réception")
        self.assertNotContains(metrics, report.title)
        self.assertNotContains(metrics, report.asset)
        exported = self.client.post(metrics_url, {"program_id": self.program.id})
        self.assertEqual(exported.status_code, 200)
        self.assertContains(exported, "Résumé d’export local")
        self.assertEqual(TriageExportEvent.objects.filter(organization=self.organization, program=self.program, actor=self.owner).count(), 1)
        self.client.force_login(self.triager)
        self.assertEqual(self.client.get(metrics_url).status_code, 403)

    def test_admin_can_review_organization_verification_with_a_reference_and_owner_cannot_open_console(self):
        self.organization.verification_status = Organization.VerificationStatus.PENDING
        self.organization.save(update_fields=["verification_status"])
        admin_console = "/console/administration/"
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(admin_console).status_code, 403)

        self.client.force_login(self.admin)
        page = self.client.get(admin_console)
        self.assertContains(page, "Console administrative")
        self.assertContains(page, self.organization.name)
        self.assertContains(page, 'href="/console/administration/"', html=False)
        response = self.client.post(
            admin_console,
            {
                "organization_id": self.organization.id,
                "verification_status": Organization.VerificationStatus.VERIFIED,
                "reviewer_reference": "review-http-001",
                "notes": "Revue fictive enregistrée dans les tests locaux.",
            },
        )
        self.assertRedirects(response, admin_console)
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.verification_status, Organization.VerificationStatus.VERIFIED)
        verification = OrganizationVerification.objects.get(organization=self.organization)
        self.assertEqual(verification.reviewer_reference, "review-http-001")
        self.assertEqual(verification.notes, "Revue fictive enregistrée dans les tests locaux.")
        self.assertTrue(
            OrganizationChangeEvent.objects.filter(
                organization=self.organization,
                actor=self.admin,
                action="organization.verification_reviewed",
            ).exists()
        )
        self.assertContains(self.client.get(admin_console), "Préparation locale et résilience")
        response = self.client.post(
            admin_console,
            {
                "action": "readiness_check",
                "check_code": "django_migrations",
                "status": "pass",
                "reference": "validation-http-001",
            },
        )
        self.assertRedirects(response, admin_console)
        self.assertTrue(ReadinessCheck.objects.filter(check_code="django_migrations", status=ReadinessCheck.Status.PASS).exists())

    def test_verified_owner_can_create_a_guarded_program_draft_and_update_organization_settings(self):
        self.client.force_login(self.owner)
        dashboard_url = f"/dashboard/organization/{self.organization.id}/"
        create_url = f"/organization/{self.organization.id}/programs/draft/"
        settings_url = f"/organization/{self.organization.id}/settings/"
        self.assertContains(self.client.get(dashboard_url), "Créer un programme brouillon")
        self.assertEqual(self.client.get(create_url).status_code, 200)

        response = self.client.post(
            create_url,
            {
                "name": "Brouillon de programme HTTP",
                "asset": "https://app.organisation-http.test/",
                "asset_type": AssetScope.AssetType.WEB,
                "safe_harbor_text": "Autorisation limitée aux tests non destructifs dans le scope défini.",
                "acknowledgement_hours": "48",
                "triage_hours": "120",
                "resolution_target_days": "21",
            },
        )
        self.assertRedirects(response, dashboard_url)
        draft = Program.objects.get(organization=self.organization, name="Brouillon de programme HTTP")
        self.assertEqual(draft.status, Program.Status.DRAFT)
        self.assertFalse(AssetScope.objects.get(program=draft).is_verified)
        self.assertFalse(ProgramPolicyVersion.objects.get(program=draft).active)
        self.assertEqual(ProgramServiceLevel.objects.get(program=draft).acknowledgement_hours, 48)
        self.assertContains(self.client.get(dashboard_url), "Brouillon de programme HTTP")
        detail_url = f"/organization/{self.organization.id}/programs/{draft.id}/"
        detail = self.client.get(detail_url)
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Programme interne")
        self.assertContains(detail, "https://app.organisation-http.test")
        self.assertContains(detail, "48 h")

        sla_update_url = f"/organization/{self.organization.id}/programs/{draft.id}/service-level/"
        response = self.client.post(
            sla_update_url,
            {"acknowledgement_hours": "24", "triage_hours": "96", "resolution_target_days": "14"},
        )
        self.assertRedirects(response, detail_url)
        service_level = ProgramServiceLevel.objects.get(program=draft)
        self.assertEqual(service_level.acknowledgement_hours, 24)
        self.assertEqual(service_level.triage_hours, 96)
        self.assertEqual(service_level.resolution_target_days, 14)
        self.assertTrue(ProgramDecisionEvent.objects.filter(program=draft, actor=self.owner, action="program.service_level_updated").exists())
        detail = self.client.get(detail_url)
        self.assertContains(detail, "24 h")
        self.assertContains(detail, "Journal des changements du programme")
        self.assertContains(detail, "Objectifs SLA mis à jour")

        response = self.client.post(
            sla_update_url,
            {"acknowledgement_hours": "0", "triage_hours": "96", "resolution_target_days": "14"},
        )
        self.assertRedirects(response, detail_url)
        service_level.refresh_from_db()
        self.assertEqual(service_level.acknowledgement_hours, 24)

        emergency_url = f"/organization/{self.organization.id}/programs/{draft.id}/emergency-control/"
        self.assertEqual(
            self.client.post(emergency_url, {"action": "suspend", "reason": "Incident local à analyser immédiatement."}).status_code,
            403,
        )
        grant_step_up(user=self.owner, action="program.emergency_suspend")
        response = self.client.post(emergency_url, {"action": "suspend", "reason": "Incident local à analyser immédiatement."})
        self.assertRedirects(response, detail_url)
        draft.refresh_from_db()
        self.assertEqual(draft.status, Program.Status.SUSPENDED)
        self.assertTrue(ProgramDecisionEvent.objects.filter(program=draft, action="program.emergency_closed").exists())
        grant_step_up(user=self.owner, action="program.emergency_resume")
        response = self.client.post(emergency_url, {"action": "resume", "reason": "Incident analysé et correctif local validé."})
        self.assertRedirects(response, detail_url)
        draft.refresh_from_db()
        self.assertEqual(draft.status, Program.Status.DRAFT)
        self.assertTrue(ProgramDecisionEvent.objects.filter(program=draft, action="program.emergency_resumed").exists())

        add_scope_url = f"/organization/{self.organization.id}/programs/{draft.id}/scopes/draft/"
        response = self.client.post(add_scope_url, {"asset": "https://api.organisation-http.test/", "asset_type": AssetScope.AssetType.API})
        self.assertRedirects(response, detail_url)
        added_scope = AssetScope.objects.get(program=draft, asset="https://api.organisation-http.test")
        self.assertFalse(added_scope.is_verified)
        self.assertTrue(added_scope.is_active)
        self.assertContains(self.client.get(detail_url), "Ajouter un scope non vérifié")

        draft.status = Program.Status.PRIVATE_ACTIVE
        draft.save(update_fields=["status"])
        self.assertEqual(
            self.client.post(add_scope_url, {"asset": "https://secondaire.organisation-http.test", "asset_type": AssetScope.AssetType.WEB}).status_code, 403
        )

        response = self.client.post(settings_url, {"name": "Organisation HTTP mise à jour"})
        self.assertRedirects(response, settings_url)
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.name, "Organisation HTTP mise à jour")

    def test_owner_can_delegate_members_manage_security_contacts_and_declare_conflicts(self):
        colleague = User.objects.create_user(
            username="http-colleague",
            email="http-colleague@example.test",
            password="Complex-Password-731!",
            email_verified=True,
            platform_role=User.PlatformRole.RESEARCHER,
        )
        settings_url = f"/organization/{self.organization.id}/settings/"
        self.client.force_login(self.owner)
        delegated = self.client.post(
            settings_url,
            {"action": "member", "member_email": colleague.email, "member_role": OrganizationMembership.Role.PROGRAM_MANAGER},
        )
        self.assertRedirects(delegated, settings_url)
        membership = OrganizationMembership.objects.get(organization=self.organization, user=colleague)
        self.assertEqual(membership.role, OrganizationMembership.Role.PROGRAM_MANAGER)

        contact_response = self.client.post(
            settings_url,
            {"action": "contact", "contact_label": "SOC fictif", "contact_email": "soc@example.test", "contact_emergency": "on"},
        )
        self.assertRedirects(contact_response, settings_url)
        self.assertTrue(SecurityContact.objects.filter(organization=self.organization, label="SOC fictif", emergency=True).exists())

        conflict_response = self.client.post(
            settings_url,
            {"action": "conflict", "conflict_user_id": colleague.id, "conflict_reason": "Conflit fictif de contrôle local."},
        )
        self.assertRedirects(conflict_response, settings_url)
        self.assertTrue(ConflictDeclaration.objects.filter(organization=self.organization, user=colleague, active=True).exists())
        self.assertContains(self.client.get(settings_url), "Conflit fictif de contrôle local.")
        self.client.force_login(colleague)
        self.assertEqual(self.client.get(f"/dashboard/organization/{self.organization.id}/").status_code, 403)

    def test_pending_organization_cannot_create_a_program_draft(self):
        self.organization.verification_status = Organization.VerificationStatus.PENDING
        self.organization.save(update_fields=["verification_status"])
        self.client.force_login(self.owner)
        create_url = f"/organization/{self.organization.id}/programs/draft/"
        denied = self.client.get(create_url)
        self.assertEqual(denied.status_code, 403)
        self.assertContains(denied, "Accès refusé", status_code=403)
        response = self.client.post(
            create_url,
            {
                "name": "Brouillon refusé",
                "asset": "https://refus.example.test",
                "asset_type": AssetScope.AssetType.WEB,
                "safe_harbor_text": "Autorisation limitée aux tests non destructifs dans le scope défini.",
                "acknowledgement_hours": "72",
                "triage_hours": "168",
                "resolution_target_days": "30",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Program.objects.filter(name="Brouillon refusé").exists())
