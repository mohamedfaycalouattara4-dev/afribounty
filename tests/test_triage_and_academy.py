from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.academy.models import (
    AcademyBadge,
    Laboratory,
    LearnerConductIncident,
    LearningModule,
    LearningPath,
    Lesson,
    RemediationExercise,
    RemediationExerciseSubmission,
    ReportingExercise,
    ReportingExerciseSubmission,
)
from apps.academy.providers import SandboxLabProvider
from apps.academy.services import (
    appeal_conduct,
    accept_current_ethics,
    assess_remediation_exercise,
    assess_reporting_exercise,
    complete_lesson,
    destroy_lab_instance,
    freeze_for_conduct,
    provision_lab_instance,
    request_badge,
    resolve_conduct_appeal,
    review_badge,
)
from apps.identity.models import User
from apps.organizations.models import ConflictDeclaration, Organization, OrganizationMembership
from apps.programs.models import Program
from apps.reports.models import FixValidation, Report, ReportRelation, TriageAssignment, TriageDecision, TriageExportEvent
from apps.reports.services import transition_report
from apps.reports.triage import (
    assign_triage,
    decide_mediation,
    export_triage_aggregate,
    record_severity,
    record_triage_decision,
    relate_reports,
    request_mediation,
    start_remediation,
    submit_fix_for_validation,
    triage_metrics_for_program,
    validate_fix,
)
from apps.security.models import SecuritySubject


class TriageAndAcademyTests(TestCase):
    def setUp(self):
        self.author = User.objects.create_user(username="author", email="author@example.test", password="Complex-Password-731!")
        self.triager = User.objects.create_user(username="triager", email="triager@example.test", password="Complex-Password-731!")
        self.owner = User.objects.create_user(username="owner", email="owner@example.test", password="Complex-Password-731!")
        self.mediator = User.objects.create_user(username="mediator", email="mediator@example.test", password="Complex-Password-731!")
        self.reviewer = User.objects.create_user(username="reviewer", email="reviewer@example.test", password="Complex-Password-731!")
        self.organization = Organization.objects.create(name="Organisation Triage", verification_status=Organization.VerificationStatus.VERIFIED)
        self.program = Program.objects.create(
            organization=self.organization,
            name="Programme Triage",
            status=Program.Status.PUBLIC_ACTIVE,
            policy_version="v1",
            policy_hash="policy-hash",
        )
        self.report = Report.objects.create(
            organization=self.organization,
            program=self.program,
            author=self.author,
            title="Rapport test",
            asset="https://app.example.test",
            policy_version="v1",
            policy_hash="policy-hash",
            idempotency_key="idempotency-key-report-0001",
        )

    def _enter_triage_with_assignee(self):
        return assign_triage(report=self.report, actor=self.owner, assignee=self.triager, reason="File dédiée")

    def test_triage_assignment_refuses_author_and_active_conflict(self):
        with self.assertRaises(PermissionDenied):
            assign_triage(report=self.report, actor=self.owner, assignee=self.author, reason="Auto-assignation")
        ConflictDeclaration.objects.create(organization=self.organization, user=self.triager, reason="Mission de conseil", active=True)
        with self.assertRaises(PermissionDenied):
            assign_triage(report=self.report, actor=self.owner, assignee=self.triager, reason="Conflit actif")

    def test_severity_priority_eligibility_and_remediation_are_separated(self):
        assignment = self._enter_triage_with_assignee()
        self.assertEqual(assignment.queue, TriageAssignment.Queue.PRE_TRIAGE)
        first = record_severity(
            report=self.report,
            evaluator=self.triager,
            technical_severity="high",
            justification="Impact reproductible dans le périmètre.",
            scoring_vector="CVSS:3.1/AV:N",
        )
        second = record_severity(
            report=self.report,
            evaluator=self.triager,
            technical_severity="critical",
            justification="Impact élargi confirmé.",
        )
        self.assertEqual((first.version, second.version), (1, 2))
        decision = record_triage_decision(
            report=self.report,
            decider=self.triager,
            business_priority="urgent",
            reward_eligibility="eligible",
            reason_code=TriageDecision.ReasonCode.VALID_CONFIRMED,
            justification="Priorité métier et récompense examinées séparément.",
        )
        self.assertEqual(decision.business_priority, "urgent")
        self.assertEqual(decision.reward_eligibility, "eligible")
        self.assertEqual(decision.reason_code, TriageDecision.ReasonCode.VALID_CONFIRMED)
        self.assertTrue(
            decision.report.triage_events.filter(action="triage.decision_recorded", detail__reason_code=TriageDecision.ReasonCode.VALID_CONFIRMED).exists()
        )
        with self.assertRaises(ValidationError):
            record_triage_decision(
                report=self.report,
                decider=self.triager,
                business_priority="urgent",
                reward_eligibility="eligible",
                reason_code="motif-inconnu",
                justification="Ce motif non répertorié doit être refusé.",
            )
        transition_report(report=self.report, actor=self.triager, target_status=Report.Status.VALID, reason="Rapport accepté.")
        remediation = start_remediation(
            report=self.report,
            actor=self.triager,
            owner=self.owner,
            target_due_at=timezone.now() + timedelta(days=14),
            plan="Corriger puis soumettre une validation indépendante.",
        )
        submit_fix_for_validation(remediation=remediation, actor=self.owner)
        with self.assertRaises(PermissionDenied):
            validate_fix(remediation=remediation, validator=self.owner, outcome=FixValidation.Outcome.ACCEPTED, notes="Auto-validation")
        validate_fix(remediation=remediation, validator=self.triager, outcome=FixValidation.Outcome.ACCEPTED, notes="Correction vérifiée.")
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, Report.Status.RESOLVED)

    def test_duplicate_additional_impact_and_mediation_second_look(self):
        self._enter_triage_with_assignee()
        primary = Report.objects.create(
            organization=self.organization,
            program=self.program,
            author=self.reviewer,
            title="Premier rapport",
            asset="https://app.example.test",
            policy_version="v1",
            policy_hash="policy-hash",
            idempotency_key="idempotency-key-report-0002",
            status=Report.Status.IN_TRIAGE,
        )
        relation = relate_reports(
            report=self.report,
            related_report=primary,
            actor=self.triager,
            relation_type=ReportRelation.RelationType.DUPLICATE_OF,
            rationale="Même cause racine confirmée.",
        )
        self.assertEqual(relation.relation_type, ReportRelation.RelationType.DUPLICATE_OF)
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, Report.Status.DUPLICATE)
        # Un nouveau rapport permet d'exercer la médiation après une première décision.
        contested = Report.objects.create(
            organization=self.organization,
            program=self.program,
            author=self.author,
            title="Rapport contesté",
            asset="https://other.example.test",
            policy_version="v1",
            policy_hash="policy-hash",
            idempotency_key="idempotency-key-report-0003",
            status=Report.Status.IN_TRIAGE,
        )
        record_severity(report=contested, evaluator=self.triager, technical_severity="medium", justification="Analyse initiale.")
        record_triage_decision(
            report=contested,
            decider=self.triager,
            business_priority="medium",
            reward_eligibility="ineligible",
            reason_code=TriageDecision.ReasonCode.DUPLICATE_ROOT_CAUSE,
            justification="Décision initiale.",
        )
        case = request_mediation(report=contested, requester=self.author, reason="Demande de second regard.")
        with self.assertRaises(PermissionDenied):
            decide_mediation(case=case, mediator=self.triager, independent_reviewer=self.reviewer, decision="Interdit : premier décideur.")
        case = decide_mediation(case=case, mediator=self.mediator, independent_reviewer=self.reviewer, decision="Décision motivée et revue indépendante.")
        self.assertEqual(case.status, "decided")
        self.assertEqual(triage_metrics_for_program(program=self.program)["reports_total"], 3)

    def test_academy_requires_ethics_and_destroys_isolated_instances(self):
        lab = Laboratory.objects.create(
            code="xss-fictif",
            title="XSS fictif",
            fictional_scenario="Application de démonstration uniquement.",
            default_quota_minutes=30,
        )
        with self.assertRaises(PermissionDenied):
            provision_lab_instance(laboratory=lab, learner=self.author)
        accept_current_ethics(learner=self.author)
        provider = SandboxLabProvider()
        instance = provision_lab_instance(laboratory=lab, learner=self.author, quota_minutes=20, provider=provider)
        self.assertTrue(instance.network_isolated)
        self.assertEqual(instance.status, "provisioned")
        self.assertEqual(instance.quota_minutes, 20)
        self.assertEqual(instance.isolation_proof["policy"]["egress"], "deny-all")
        self.assertTrue(instance.provider_reference.startswith("sandbox-"))
        destroy_lab_instance(
            instance=instance,
            actor=self.author,
            reason="Fin de session pédagogique.",
            provider=provider,
        )
        instance.refresh_from_db()
        self.assertEqual(instance.status, "destroyed")
        self.assertEqual(instance.destruction_proof["state"], "destroyed")
        external = Laboratory.objects.create(
            code="interdit-externe", title="Interdit", fictional_scenario="Ne doit jamais être lancé.", contains_external_target=True
        )
        with self.assertRaises(PermissionDenied):
            provision_lab_instance(laboratory=external, learner=self.author)
        with self.assertRaises(ValidationError):
            provision_lab_instance(laboratory=lab, learner=self.author, quota_minutes=31, provider=provider)
        unsafe_provider = SandboxLabProvider()
        unsafe_provider.isolation_policy = {**unsafe_provider.isolation_policy, "egress": "allow-all"}
        with self.assertRaises(ValidationError):
            provision_lab_instance(laboratory=lab, learner=self.author, provider=unsafe_provider)

    def test_triage_aggregate_export_is_authorized_audited_and_contains_no_report_content(self):
        self.organization.exports_enabled = True
        self.organization.save(update_fields=["exports_enabled"])
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.owner,
            role=OrganizationMembership.Role.OWNER,
        )
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.triager,
            role=OrganizationMembership.Role.TRIAGER,
        )
        self._enter_triage_with_assignee()
        payload = export_triage_aggregate(organization=self.organization, program=self.program, actor=self.owner)
        self.assertEqual(payload["reports_total"], 1)
        self.assertIn("triage_delay_average_hours", payload)
        self.assertIn("remediations_overdue", payload)
        self.assertNotIn("title", payload)
        self.assertNotIn("asset", payload)
        self.assertEqual(TriageExportEvent.objects.filter(program=self.program, actor=self.owner).count(), 1)
        with self.assertRaises(PermissionDenied):
            export_triage_aggregate(organization=self.organization, program=self.program, actor=self.triager)

    def test_academy_progress_exercises_badges_and_conduct_appeal(self):
        path = LearningPath.objects.create(code="fondations", title="Fondations", description="Parcours de base", published=True)
        module = LearningModule.objects.create(path=path, title="Module un", position=1)
        lesson = Lesson.objects.create(module=module, title="Leçon un", content_reference="lesson://one", position=1)
        progress = complete_lesson(learner=self.author, lesson=lesson, score=85)
        self.assertIsNotNone(progress.completed_at)
        report_exercise = ReportingExercise.objects.create(module=module, prompt="Rédiger un rapport", minimum_score=60)
        submission = ReportingExerciseSubmission.objects.create(exercise=report_exercise, learner=self.author, response="Rapport pédagogique.")
        with self.assertRaises(PermissionDenied):
            assess_reporting_exercise(submission=submission, reviewer=self.author, score=90)
        assess_reporting_exercise(submission=submission, reviewer=self.reviewer, score=90)
        remediation_exercise = RemediationExercise.objects.create(
            module=module,
            prompt="Proposer un correctif",
            expected_controls=["validation"],
        )
        remediation_submission = RemediationExerciseSubmission.objects.create(
            exercise=remediation_exercise,
            learner=self.author,
            response="Correctif pédagogique.",
        )
        assess_remediation_exercise(submission=remediation_submission, reviewer=self.reviewer, score=88)
        badge = AcademyBadge.objects.create(code="fondations-validees", title="Fondations validées", criteria="Revue humaine obligatoire.")
        award = request_badge(badge=badge, learner=self.author)
        with self.assertRaises(PermissionDenied):
            review_badge(award=award, reviewer=self.author, award_badge=True, reason="Auto-attribution")
        review_badge(award=award, reviewer=self.reviewer, award_badge=True, reason="Critères validés.")
        self.assertEqual(award.status, "awarded")
        subject = SecuritySubject.objects.create(reference="academy-author")
        incident = LearnerConductIncident.objects.create(
            learner=self.author,
            reporter=self.reviewer,
            security_subject=subject,
            description="Non-respect des règles de laboratoire.",
        )
        freeze_for_conduct(incident=incident, reviewer=self.reviewer, reason="Revue humaine requise.")
        appeal_conduct(incident=incident, learner=self.author, reason="Recours documenté.")
        resolve_conduct_appeal(incident=incident, reviewer=self.mediator, overturn_freeze=True, reason="Recours accepté.")
        subject.refresh_from_db()
        incident.refresh_from_db()
        self.assertEqual(subject.status, SecuritySubject.Status.ACTIVE)
        self.assertEqual(incident.status, LearnerConductIncident.Status.CLOSED)
