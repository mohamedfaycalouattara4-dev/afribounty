from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings

from apps.identity.models import User
from apps.organizations.models import Organization, OrganizationMembership
from apps.programs.models import AssetOwnershipProof, AssetScope, Program
from apps.reports.evidence_pipeline import external_evidence_pipeline_readiness, require_external_evidence_activation
from apps.reports.models import EvidencePipelineState, Report, ReportEvidence
from apps.reports.services import add_report_evidence, list_report_evidence, save_report_draft, submit_report, verify_report_scope_integrity


@override_settings(MEDIA_ROOT="/tmp/afribounty-evidence-test-media")
class ReportEvidenceTests(TestCase):
    def setUp(self):
        self.researcher = User.objects.create_user(
            username="evidence-researcher",
            email="evidence-researcher@example.test",
            password="Complex-Password-731!",
            platform_role=User.PlatformRole.RESEARCHER,
        )
        self.other = User.objects.create_user(
            username="evidence-other", email="evidence-other@example.test", password="Complex-Password-731!", platform_role=User.PlatformRole.RESEARCHER
        )
        self.owner = User.objects.create_user(
            username="evidence-owner", email="evidence-owner@example.test", password="Complex-Password-731!", platform_role=User.PlatformRole.ORGANIZATION
        )
        self.organization = Organization.objects.create(name="Organisation preuves", verification_status=Organization.VerificationStatus.VERIFIED)
        OrganizationMembership.objects.create(organization=self.organization, user=self.owner, role=OrganizationMembership.Role.OWNER)
        self.program = Program.objects.create(
            organization=self.organization, name="Programme preuves", status=Program.Status.PUBLIC_ACTIVE, policy_version="v1", policy_hash="proof-policy"
        )
        self.report = Report.objects.create(
            organization=self.organization,
            program=self.program,
            author=self.researcher,
            title="Rapport preuve",
            asset="https://preuve.example.test",
            impact="Impact fictif",
            reproduction="Étapes fictives",
            policy_version="v1",
            policy_hash="proof-policy",
            idempotency_key="evidence-report-key-0001",
        )

    def test_authorized_evidence_is_hashed_idempotent_and_private(self):
        uploaded = SimpleUploadedFile("preuve.json", b'{"local": true}', content_type="application/json")
        first = add_report_evidence(
            report=self.report, actor=self.researcher, uploaded_file=uploaded, category="reproduction", idempotency_key="evidence-idempotency-key-0001"
        )
        duplicate = add_report_evidence(
            report=self.report,
            actor=self.researcher,
            uploaded_file=SimpleUploadedFile("preuve.json", b'{"local": true}', content_type="application/json"),
            category="reproduction",
            idempotency_key="evidence-idempotency-key-0001",
        )
        self.assertTrue(first.was_created)
        self.assertFalse(duplicate.was_created)
        self.assertEqual(ReportEvidence.objects.filter(report=self.report).count(), 1)
        self.assertEqual(len(first.evidence.sha256), 64)
        self.assertEqual(first.evidence.pipeline_state.state, EvidencePipelineState.State.LOCAL_ACCEPTED)
        self.assertEqual(first.evidence.pipeline_state.malware_scanner, "disabled")
        self.assertFalse(first.evidence.pipeline_state.external_release_allowed)
        self.assertEqual(list(list_report_evidence(report=self.report, actor=self.owner)).pop().id, first.evidence.id)
        with self.assertRaises(PermissionDenied):
            list_report_evidence(report=self.report, actor=self.other)
        with self.assertRaises(ValidationError):
            add_report_evidence(
                report=self.report,
                actor=self.researcher,
                uploaded_file=SimpleUploadedFile("preuve.exe", b"x", content_type="application/octet-stream"),
                category="reproduction",
                idempotency_key="bad-evidence-key-000001",
            )

    def test_external_evidence_capabilities_remain_prepared_but_disabled(self):
        readiness = external_evidence_pipeline_readiness()
        self.assertFalse(readiness["private_object_storage"]["enabled"])
        self.assertEqual(readiness["dlp_inspection"]["provider"], "disabled")
        with self.assertRaises(ImproperlyConfigured):
            require_external_evidence_activation(capability="malware_scanning")

    def test_http_hides_evidence_from_other_researcher(self):
        url = f"/reports/{self.report.id}/evidence/"
        self.client.force_login(self.other)
        response = self.client.post(
            url,
            {
                "category": "reproduction",
                "evidence_key": "other-evidence-key-000001",
                "evidence_file": SimpleUploadedFile("preuve.txt", b"preuve", content_type="text/plain"),
            },
        )
        self.assertEqual(response.status_code, 404)

    def test_evidence_rejects_spoofed_signature_and_antivirus_marker(self):
        with self.assertRaises(ValidationError):
            add_report_evidence(
                report=self.report,
                actor=self.researcher,
                uploaded_file=SimpleUploadedFile("preuve.pdf", b"not-a-pdf", content_type="application/pdf"),
                category="impact",
                idempotency_key="spoofed-pdf-evidence-key-0001",
            )
        with self.assertRaises(ValidationError):
            add_report_evidence(
                report=self.report,
                actor=self.researcher,
                uploaded_file=SimpleUploadedFile("preuve.txt", b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE", content_type="text/plain"),
                category="impact",
                idempotency_key="eicar-evidence-key-00000001",
            )
        with self.assertRaises(ValidationError):
            add_report_evidence(
                report=self.report,
                actor=self.researcher,
                uploaded_file=SimpleUploadedFile("delayed-eicar.txt", b"x" * 9000 + b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE", content_type="text/plain"),
                category="impact",
                idempotency_key="delayed-eicar-evidence-key-0001",
            )

    def test_draft_submission_and_text_evidence_refuse_secret_material_before_persistence(self):
        secret = "ghp_abcdefghijklmnopqrstuvwxyz0123456789ABCDE"
        with self.assertRaises(ValidationError):
            save_report_draft(
                organization=self.organization,
                program=self.program,
                author=self.researcher,
                title="Brouillon avec secret",
                asset="https://preuve.example.test",
                impact="Impact fictif",
                reproduction=f"Authorization: Bearer {secret}",
            )
        with self.assertRaises(ValidationError):
            submit_report(
                organization=self.organization,
                program=self.program,
                author=self.researcher,
                title="Rapport avec secret",
                asset="https://preuve.example.test",
                impact="Impact fictif",
                reproduction=f"token={secret}",
                idempotency_key="secret-report-idempotency-0001",
            )
        with self.assertRaises(ValidationError):
            add_report_evidence(
                report=self.report,
                actor=self.researcher,
                uploaded_file=SimpleUploadedFile("secret.log", f"x-api-key: {secret}".encode(), content_type="text/plain"),
                category="reproduction",
                idempotency_key="secret-evidence-idempotency-0001",
            )
        self.assertFalse(ReportEvidence.objects.filter(report=self.report, original_name="secret.log").exists())

    def test_submission_preserves_a_verifiable_scope_snapshot(self):
        scope = AssetScope.objects.create(
            program=self.program,
            asset="https://preuve.example.test",
            asset_type=AssetScope.AssetType.WEB,
            is_verified=True,
        )
        AssetOwnershipProof.objects.create(
            scope=scope,
            evidence_reference="ownership-proof-local-reference",
            reviewed_by_reference="security-reviewer",
            approved_at=scope.created_at,
        )
        created = submit_report(
            organization=self.organization,
            program=self.program,
            author=self.researcher,
            title="Intégrité de scope",
            asset=scope.asset,
            impact="Impact contrôlé",
            reproduction="Étapes contrôlées",
            idempotency_key="scope-integrity-submission-key-0001",
        )
        self.assertTrue(created.was_created)
        self.assertEqual(created.report.scope_snapshot["scope_id"], scope.id)
        self.assertEqual(created.report.scope_snapshot["policy_hash"], "proof-policy")
        self.assertTrue(verify_report_scope_integrity(report=created.report))
        self.program.policy_hash = "new-policy-hash"
        self.program.save(update_fields=["policy_hash"])
        created.report.refresh_from_db()
        self.assertTrue(verify_report_scope_integrity(report=created.report))
        created.report.scope_snapshot["asset"] = "https://altered.example.test"
        self.assertFalse(verify_report_scope_integrity(report=created.report))

    def test_submission_records_structured_quality_context(self):
        scope = AssetScope.objects.create(program=self.program, asset="https://quality.example.test", is_verified=True)
        AssetOwnershipProof.objects.create(
            scope=scope,
            evidence_reference="quality-proof-reference",
            reviewed_by_reference="security-reviewer",
            approved_at=scope.created_at,
        )
        created = submit_report(
            organization=self.organization,
            program=self.program,
            author=self.researcher,
            title="Qualité structurée",
            asset=scope.asset,
            impact="Impact confirmé",
            reproduction="Étapes reproductibles",
            vulnerability_category="access_control",
            cwe_reference="CWE-639",
            affected_version="2026.08.22",
            environment_details="Compte chercheur standard, application web.",
            idempotency_key="quality-submission-key-0001",
        )
        self.assertEqual(created.report.quality_score, 100)
        self.assertEqual(created.report.quality_flags, [])
        self.assertEqual(created.report.cwe_reference, "CWE-639")

    def test_text_evidence_detects_secret_beyond_the_first_8192_bytes(self):
        secret = b"\ntoken=ghp_abcdefghijklmnopqrstuvwxyz0123456789ABCDE"
        with self.assertRaises(ValidationError):
            add_report_evidence(
                report=self.report,
                actor=self.researcher,
                uploaded_file=SimpleUploadedFile("delayed-secret.txt", b"x" * 9000 + secret, content_type="text/plain"),
                category="reproduction",
                idempotency_key="delayed-secret-evidence-key-0001",
            )

    @override_settings(EVIDENCE_ENCRYPTION_KEY="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
    def test_private_storage_encrypts_file_without_public_url(self):
        created = add_report_evidence(
            report=self.report,
            actor=self.researcher,
            uploaded_file=SimpleUploadedFile("preuve.txt", b"preuve confidentielle", content_type="text/plain"),
            category="reproduction",
            idempotency_key="encrypted-evidence-key-000001",
        )
        with open(created.evidence.artifact.path, "rb") as stored:
            self.assertNotIn(b"preuve confidentielle", stored.read())
        self.assertEqual(created.evidence.artifact.open().read(), b"preuve confidentielle")
        with self.assertRaises(ValueError):
            created.evidence.artifact.url

    @override_settings(
        AFRIBOUNTY_ENVIRONMENT="production",
        AFRIBOUNTY_EVIDENCE_STORAGE_BACKEND="private-object",
        EVIDENCE_ENCRYPTION_KEY="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    )
    def test_production_refuses_evidence_without_object_storage_adapter(self):
        with self.assertRaises(ImproperlyConfigured):
            add_report_evidence(
                report=self.report,
                actor=self.researcher,
                uploaded_file=SimpleUploadedFile("preuve.txt", b"preuve", content_type="text/plain"),
                category="reproduction",
                idempotency_key="production-storage-refusal-key",
            )
