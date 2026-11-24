from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.identity.models import User
from apps.organizations.models import Organization, OrganizationMembership
from apps.programs.models import AssetOwnershipProof, AssetScope, Program
from apps.reports.models import Report
from apps.reports.services import report_scope_integrity_report, submit_report


class ReportScopeIntegrityCommandTests(TestCase):
    def setUp(self):
        self.researcher = User.objects.create_user(
            username="scope-integrity-researcher",
            email="scope-integrity-researcher@example.test",
            password="Complex-Password-731!",
            platform_role=User.PlatformRole.RESEARCHER,
        )
        owner = User.objects.create_user(
            username="scope-integrity-owner",
            email="scope-integrity-owner@example.test",
            password="Complex-Password-731!",
            platform_role=User.PlatformRole.ORGANIZATION,
        )
        self.organization = Organization.objects.create(name="Organisation contrôle scope", verification_status=Organization.VerificationStatus.VERIFIED)
        OrganizationMembership.objects.create(organization=self.organization, user=owner, role=OrganizationMembership.Role.OWNER)
        self.program = Program.objects.create(
            organization=self.organization,
            name="Programme contrôle scope",
            status=Program.Status.PUBLIC_ACTIVE,
            policy_version="v1",
            policy_hash="scope-integrity-policy",
        )
        self.scope = AssetScope.objects.create(program=self.program, asset="https://scope-integrity.example.test", is_verified=True)
        AssetOwnershipProof.objects.create(
            scope=self.scope,
            evidence_reference="scope-integrity-proof",
            reviewed_by_reference="security-local",
            approved_at=self.scope.created_at,
        )

    def test_strict_command_detects_missing_or_mismatched_scope_snapshot_without_repairing_report(self):
        submitted = submit_report(
            organization=self.organization,
            program=self.program,
            author=self.researcher,
            title="Rapport sous contrôle scope",
            asset=self.scope.asset,
            impact="Impact local contrôlé",
            reproduction="Étapes locales contrôlées",
            idempotency_key="scope-integrity-command-submission-0001",
        ).report
        self.assertEqual(
            report_scope_integrity_report(),
            {"checked_count": 1, "missing_snapshot_count": 0, "mismatched_snapshot_count": 0, "valid": True},
        )
        call_command("verify_report_scope_integrity", "--strict")
        Report.objects.filter(pk=submitted.pk).update(scope_snapshot={"asset": "https://altered.example.test"})
        self.assertEqual(
            report_scope_integrity_report(),
            {"checked_count": 1, "missing_snapshot_count": 0, "mismatched_snapshot_count": 1, "valid": False},
        )
        with self.assertRaises(CommandError):
            call_command("verify_report_scope_integrity", "--strict")
        submitted.refresh_from_db()
        self.assertEqual(submitted.scope_snapshot, {"asset": "https://altered.example.test"})
