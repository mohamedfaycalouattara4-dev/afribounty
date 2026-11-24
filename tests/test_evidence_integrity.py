from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from apps.identity.models import User
from apps.organizations.models import Organization
from apps.programs.models import Program
from apps.reports.models import Report, ReportEvidence
from apps.reports.services import add_report_evidence, evidence_integrity_report


@override_settings(MEDIA_ROOT="/tmp/afribounty-evidence-integrity-test-media")
class EvidenceIntegrityTests(TestCase):
    def setUp(self):
        self.researcher = User.objects.create_user(
            username="evidence-integrity-researcher",
            email="evidence-integrity-researcher@example.test",
            password="Complex-Password-731!",
            platform_role=User.PlatformRole.RESEARCHER,
        )
        organization = Organization.objects.create(name="Organisation intégrité preuve", verification_status=Organization.VerificationStatus.VERIFIED)
        program = Program.objects.create(
            organization=organization, name="Programme intégrité preuve", policy_version="v1", policy_hash="evidence-integrity-policy"
        )
        self.report = Report.objects.create(
            organization=organization,
            program=program,
            author=self.researcher,
            title="Rapport intégrité preuve",
            asset="https://evidence-integrity.example.test",
            impact="Impact local",
            reproduction="Étapes locales",
            policy_version="v1",
            policy_hash="evidence-integrity-policy",
            idempotency_key="evidence-integrity-report-0001",
        )

    def test_strict_command_detects_recorded_hash_tampering_without_touching_private_artifact(self):
        created = add_report_evidence(
            report=self.report,
            actor=self.researcher,
            uploaded_file=SimpleUploadedFile("preuve.txt", b"preuve locale integre", content_type="text/plain"),
            category="reproduction",
            idempotency_key="evidence-integrity-upload-0001",
        ).evidence
        self.assertEqual(
            evidence_integrity_report(),
            {
                "checked_count": 1,
                "missing_artifact_count": 0,
                "unreadable_artifact_count": 0,
                "mismatched_artifact_count": 0,
                "valid": True,
            },
        )
        call_command("verify_report_evidence_integrity", "--strict")
        ReportEvidence.objects.filter(pk=created.pk).update(sha256="0" * 64)
        self.assertEqual(
            evidence_integrity_report(),
            {
                "checked_count": 1,
                "missing_artifact_count": 0,
                "unreadable_artifact_count": 0,
                "mismatched_artifact_count": 1,
                "valid": False,
            },
        )
        with self.assertRaises(CommandError):
            call_command("verify_report_evidence_integrity", "--strict")
        created.refresh_from_db()
        self.assertEqual(created.sha256, "0" * 64)
        self.assertEqual(created.artifact.open("rb").read(), b"preuve locale integre")
