from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.identity.models import User
from apps.identity.services import grant_step_up
from apps.organizations.models import Organization
from apps.programs.models import Program
from apps.reports.models import Report, TriageDecision
from apps.reputation.models import Challenge, ChallengeResult, ReputationEvent, ReputationSeason
from apps.reputation.services import (
    append_reputation_event,
    enroll_challenge,
    export_anonymized_progress,
    open_score_dispute,
    points_for,
    rebuild_profiles,
    resolve_score_dispute,
    validate_challenge_result,
)
from apps.rewards.models import LedgerEntry, RewardEntitlement
from apps.rewards.sandbox import SandboxPaymentProvider
from apps.rewards.services import (
    approve_reward,
    cancel_reward,
    create_payment_order,
    create_reward_entitlement,
    process_payment_webhook,
    reconcile_sandbox_payments,
    record_sandbox_fee,
    set_beneficiary_profile,
    verify_beneficiary,
)


class ReputationAndRewardsTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.researcher = User.objects.create_user(
            username="researcher-reputation",
            email="researcher-reputation@example.test",
            password="Complex-Password-731!",
            email_verified=True,
            platform_role=User.PlatformRole.RESEARCHER,
        )
        self.second_researcher = User.objects.create_user(
            username="second-researcher",
            email="second-researcher@example.test",
            password="Complex-Password-731!",
            email_verified=True,
            platform_role=User.PlatformRole.RESEARCHER,
        )
        self.triager = User.objects.create_user(
            username="triager-reputation",
            email="triager-reputation@example.test",
            password="Complex-Password-731!",
            platform_role=User.PlatformRole.TRIAGER,
        )
        self.admin = User.objects.create_user(
            username="admin-reputation",
            email="admin-reputation@example.test",
            password="Complex-Password-731!",
            platform_role=User.PlatformRole.ADMIN,
        )
        self.finance_one = User.objects.create_user(
            username="finance-one",
            email="finance-one@example.test",
            password="Complex-Password-731!",
            platform_role=User.PlatformRole.FINANCE,
        )
        self.finance_two = User.objects.create_user(
            username="finance-two",
            email="finance-two@example.test",
            password="Complex-Password-731!",
            platform_role=User.PlatformRole.FINANCE,
        )
        self.season = ReputationSeason.objects.create(code="saison-2026", starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=30), active=True)

    def _open_challenge(self):
        now = timezone.now()
        return Challenge.objects.create(
            code="challenge-isole",
            title="Challenge isolé",
            fictional_scenario="Scénario entièrement fictif.",
            rules_version="v1",
            rules_hash="rules-hash",
            starts_at=now - timedelta(hours=1),
            ends_at=now + timedelta(hours=4),
            status=Challenge.Status.OPEN,
        )

    def _eligible_report(self):
        organization = Organization.objects.create(name="Organisation Récompense", verification_status=Organization.VerificationStatus.VERIFIED)
        program = Program.objects.create(
            organization=organization,
            name="Programme Récompense",
            status=Program.Status.PUBLIC_ACTIVE,
            policy_version="v1",
            policy_hash="policy-hash",
        )
        report = Report.objects.create(
            organization=organization,
            program=program,
            author=self.researcher,
            title="Rapport accepté",
            asset="https://scope.example.test",
            status=Report.Status.VALID,
            policy_version="v1",
            policy_hash="policy-hash",
            idempotency_key="reward-report-idempotency-001",
        )
        TriageDecision.objects.create(
            report=report,
            decided_by=self.triager,
            business_priority=TriageDecision.BusinessPriority.HIGH,
            reward_eligibility=TriageDecision.RewardEligibility.ELIGIBLE,
            justification="Éligibilité confirmée par triage.",
        )
        return report

    def test_reputation_is_deterministic_append_only_and_recalculable(self):
        self.assertEqual(points_for(event_type=ReputationEvent.EventType.REPORT_ACCEPTED, context={"severity": "high"}), 60)
        event = append_reputation_event(
            user=self.researcher,
            season=self.season,
            event_type=ReputationEvent.EventType.REPORT_ACCEPTED,
            points=60,
            source_reference="report:1",
            idempotency_key="reputation-report-1",
            reason="Rapport accepté.",
        )
        same_event = append_reputation_event(
            user=self.researcher,
            season=self.season,
            event_type=ReputationEvent.EventType.REPORT_ACCEPTED,
            points=60,
            source_reference="report:1",
            idempotency_key="reputation-report-1",
            reason="Rapport accepté.",
        )
        self.assertEqual(event.id, same_event.id)
        event.points = 1
        with self.assertRaises(ValidationError):
            event.save()
        profiles = rebuild_profiles(season=self.season)
        self.assertEqual([(profile.user_id, profile.points, profile.rank) for profile in profiles], [(self.researcher.id, 60, 1)])
        self.assertEqual(export_anonymized_progress(season=self.season, actor=self.admin)["participants"], 1)
        with self.assertRaises(PermissionDenied):
            export_anonymized_progress(season=self.season, actor=self.researcher)

    def test_isolated_challenge_review_and_score_compensation(self):
        challenge = self._open_challenge()
        self.researcher.email_verified = False
        self.researcher.save(update_fields=["email_verified"])
        with self.assertRaises(PermissionDenied):
            enroll_challenge(challenge=challenge, learner=self.researcher)
        self.researcher.email_verified = True
        self.researcher.save(update_fields=["email_verified"])
        enrollment = enroll_challenge(challenge=challenge, learner=self.researcher)
        result = ChallengeResult.objects.create(enrollment=enrollment, submitted_score=70, submission_reference="submission-001")
        validate_challenge_result(result=result, reviewer=self.triager, anti_cheat_cleared=False, approved=True, reason="Signal à examiner.")
        result.refresh_from_db()
        self.assertEqual(result.review_status, ChallengeResult.ReviewStatus.MANUAL_REVIEW)
        enrollment_two = enroll_challenge(challenge=challenge, learner=self.second_researcher)
        approved_result = ChallengeResult.objects.create(enrollment=enrollment_two, submitted_score=70, submission_reference="submission-002")
        validate_challenge_result(
            result=approved_result,
            reviewer=self.triager,
            anti_cheat_cleared=True,
            approved=True,
            reason="Contrôle manuel validé.",
        )
        dispute = open_score_dispute(result=approved_result, requester=self.second_researcher, reason="Score à corriger.")
        resolve_score_dispute(dispute=dispute, reviewer=self.triager, corrected_score=80, reason="Nouvelle preuve recevable.")
        dispute.refresh_from_db()
        self.assertEqual(dispute.status, "resolved")
        self.assertEqual(dispute.correction_event.points, 10)
        self.assertEqual(approved_result.reputation_event.points, 75)

    def test_reward_double_control_ledger_mfa_payment_idempotence_and_replay_refusal(self):
        report = self._eligible_report()
        entitlement = create_reward_entitlement(report=report, proposer=self.triager, amount_xof=150_000, rationale="Impact élevé confirmé.")
        approve_reward(entitlement=entitlement, approver=self.finance_one, approved=True, reason="Premier contrôle.")
        entitlement.refresh_from_db()
        self.assertEqual(entitlement.status, RewardEntitlement.Status.PENDING)
        approve_reward(entitlement=entitlement, approver=self.finance_two, approved=True, reason="Second contrôle indépendant.")
        entitlement.refresh_from_db()
        self.assertEqual(entitlement.status, RewardEntitlement.Status.APPROVED)
        promise = entitlement.ledger_entries.get(entry_type=LedgerEntry.EntryType.PROMISE)
        promise.amount_xof = 1
        with self.assertRaises(ValidationError):
            promise.save()
        with self.assertRaises(PermissionDenied):
            set_beneficiary_profile(user=self.researcher, provider_code="sandbox-money", recipient_reference="sandbox-beneficiary-001")
        grant_step_up(user=self.researcher, action="beneficiary.change")
        profile = set_beneficiary_profile(user=self.researcher, provider_code="sandbox-money", recipient_reference="sandbox-beneficiary-001")
        verify_beneficiary(profile=profile, reviewer=self.finance_one)
        provider = SandboxPaymentProvider("sandbox-signing-secret-0001")
        order = create_payment_order(entitlement=entitlement, actor=self.finance_one, idempotency_key="payment-order-001", provider=provider)
        same_order = create_payment_order(entitlement=entitlement, actor=self.finance_one, idempotency_key="payment-order-001", provider=provider)
        self.assertEqual(order.id, same_order.id)
        fee = record_sandbox_fee(entitlement=entitlement, actor=self.finance_one, amount_xof=500, reference="sandbox-fee-001")
        self.assertEqual(fee.entry_type, LedgerEntry.EntryType.FEE)
        occurred_at = timezone.now()
        signature = provider.sign_webhook(
            event_id="payment-event-001",
            provider_reference=order.provider_reference,
            status="succeeded",
            occurred_at=occurred_at.isoformat(),
        )
        process_payment_webhook(
            provider=provider,
            event_id="payment-event-001",
            provider_reference=order.provider_reference,
            status="succeeded",
            occurred_at=occurred_at,
            signature=signature,
        )
        with self.assertRaises(PermissionDenied):
            process_payment_webhook(
                provider=provider,
                event_id="payment-event-001",
                provider_reference=order.provider_reference,
                status="succeeded",
                occurred_at=occurred_at,
                signature=signature,
            )
        with self.assertRaises(PermissionDenied):
            process_payment_webhook(
                provider=provider,
                event_id="payment-event-invalid-signature",
                provider_reference=order.provider_reference,
                status="succeeded",
                occurred_at=timezone.now(),
                signature="0" * 64,
            )
        stale_at = timezone.now() - timedelta(minutes=6)
        stale_signature = provider.sign_webhook(
            event_id="payment-event-stale",
            provider_reference=order.provider_reference,
            status="succeeded",
            occurred_at=stale_at.isoformat(),
        )
        with self.assertRaises(PermissionDenied):
            process_payment_webhook(
                provider=provider,
                event_id="payment-event-stale",
                provider_reference=order.provider_reference,
                status="succeeded",
                occurred_at=stale_at,
                signature=stale_signature,
            )
        report_reconciliation = reconcile_sandbox_payments(actor=self.finance_one)
        self.assertEqual(report_reconciliation.exception_count, 0)
        cancellation = cancel_reward(entitlement=entitlement, actor=self.finance_one, reason="Annulation de test après rapprochement.")
        self.assertEqual(cancellation.amount_xof, -150_000)
