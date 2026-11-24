from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from apps.identity.models import User
from apps.readiness.models import ReadinessCheck, ResilienceExercise
from apps.readiness.services import (
    create_go_no_go_assessment,
    record_local_readiness_check,
    simulate_dependency_degradation,
    verify_backup_restore_payload,
)


class ReadinessTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="readiness-admin",
            email="readiness-admin@example.test",
            password="Complex-Password-731!",
            platform_role=User.PlatformRole.ADMIN,
        )
        self.security = User.objects.create_user(
            username="readiness-security",
            email="readiness-security@example.test",
            password="Complex-Password-731!",
            platform_role=User.PlatformRole.SECURITY,
        )
        self.researcher = User.objects.create_user(
            username="readiness-researcher",
            email="readiness-researcher@example.test",
            password="Complex-Password-731!",
            platform_role=User.PlatformRole.RESEARCHER,
        )

    def test_readiness_check_is_permissioned_append_only_and_evidence_is_hashed(self):
        check = record_local_readiness_check(
            actor=self.security,
            check_code="unit_tests",
            status=ReadinessCheck.Status.PASS,
            evidence={"tests": 53, "command": "manage.py test"},
        )
        self.assertIn("evidence_digest", check.evidence)
        check.status = ReadinessCheck.Status.BLOCKED
        with self.assertRaises(ValidationError):
            check.save()
        with self.assertRaises(PermissionDenied):
            record_local_readiness_check(
                actor=self.researcher,
                check_code="unit_tests",
                status=ReadinessCheck.Status.PASS,
                evidence={},
            )

    def test_backup_restore_proof_and_degraded_modes_are_deterministic(self):
        proof = verify_backup_restore_payload(backup_payload={"report_ids": [1, 2], "count": 2}, restored_payload={"count": 2, "report_ids": [1, 2]})
        self.assertTrue(proof["matched"])
        mismatch = verify_backup_restore_payload(backup_payload={"report_ids": [1]}, restored_payload={"report_ids": [2]})
        self.assertFalse(mismatch["matched"])
        exercise = simulate_dependency_degradation(
            actor=self.admin,
            dependency=ResilienceExercise.Dependency.REDIS,
            operation="Saturation du limiteur",
        )
        self.assertTrue(exercise.passed)
        self.assertEqual(exercise.observed_mode, "rate_limit_fail_closed")
        failed = simulate_dependency_degradation(
            actor=self.admin,
            dependency=ResilienceExercise.Dependency.WORKER,
            operation="Worker indisponible",
            observed_mode="unsafe_continue",
        )
        self.assertFalse(failed.passed)

    def test_go_no_go_remains_pending_human_decision_with_external_blockers(self):
        assessment = create_go_no_go_assessment(actor=self.security, local_evidence={"tests": 53, "sca": "pass"})
        self.assertEqual(assessment.status, "pending_human_decision")
        self.assertIn("audit_externe_preproduction", assessment.blockers)
        self.assertIn("decision_humaine_proprietaire", assessment.blockers)
