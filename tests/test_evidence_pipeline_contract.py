from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from apps.identity.models import User
from apps.organizations.models import Organization
from apps.programs.models import Program
from apps.reports.evidence_pipeline import evidence_pipeline_contract_report, register_local_evidence_acceptance
from apps.reports.models import EvidencePipelineState, Report
from apps.reports.services import add_report_evidence


@override_settings(MEDIA_ROOT="/tmp/afribounty-evidence-pipeline-contract-test-media")
class EvidencePipelineContractTests(TestCase):
    def setUp(self):
        self.researcher = User.objects.create_user(
            username="evidence-pipeline-researcher",
            email="evidence-pipeline-researcher@example.test",
            password="Complex-Password-742!",
            platform_role=User.PlatformRole.RESEARCHER,
        )
        organization = Organization.objects.create(name="Organisation pipeline preuve", verification_status=Organization.VerificationStatus.VERIFIED)
        program = Program.objects.create(
            organization=organization, name="Programme pipeline preuve", policy_version="v1", policy_hash="pipeline-contract-policy"
        )
        self.report = Report.objects.create(
            organization=organization,
            program=program,
            author=self.researcher,
            title="Rapport pipeline preuve",
            asset="https://evidence-pipeline.example.test",
            impact="Impact local",
            reproduction="Étapes locales",
            policy_version="v1",
            policy_hash="pipeline-contract-policy",
            idempotency_key="pipeline-contract-report-0001",
        )

    def test_strict_contract_detects_external_release_tampering_without_reconfiguring_pipeline(self):
        evidence = add_report_evidence(
            report=self.report,
            actor=self.researcher,
            uploaded_file=SimpleUploadedFile("preuve.txt", b"preuve pipeline locale", content_type="text/plain"),
            category="reproduction",
            idempotency_key="pipeline-contract-upload-0001",
        ).evidence
        register_local_evidence_acceptance(evidence=evidence)
        self.assertEqual(
            evidence_pipeline_contract_report(),
            {
                "checked_count": 1,
                "invalid_state_count": 0,
                "invalid_provider_count": 0,
                "release_allowed_count": 0,
                "valid": True,
            },
        )
        call_command("verify_evidence_pipeline_contract", "--strict")
        EvidencePipelineState.objects.filter(evidence=evidence).update(
            state=EvidencePipelineState.State.EXTERNAL_RELEASED,
            storage_provider="unapproved-provider",
            external_release_allowed=True,
        )
        self.assertEqual(
            evidence_pipeline_contract_report(),
            {
                "checked_count": 1,
                "invalid_state_count": 1,
                "invalid_provider_count": 1,
                "release_allowed_count": 1,
                "valid": False,
            },
        )
        with self.assertRaises(CommandError):
            call_command("verify_evidence_pipeline_contract", "--strict")
        state = EvidencePipelineState.objects.get(evidence=evidence)
        self.assertEqual(state.storage_provider, "unapproved-provider")
        self.assertTrue(state.external_release_allowed)
