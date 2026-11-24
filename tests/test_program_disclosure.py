from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.utils import timezone

from apps.identity.models import User
from apps.organizations.models import Organization
from apps.programs.access import emergency_close, require_research_scope
from apps.programs.models import AssetOwnershipProof, AssetScope, Program, ProgramInvitation, ProgramPolicyVersion, ProgramServiceLevel


class DisclosureProgramTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner", email="owner@example.test", password="Complex-Password-731!")
        self.researcher = User.objects.create_user(username="researcher", email="researcher@example.test", password="Complex-Password-731!")
        self.outsider = User.objects.create_user(username="outsider", email="outsider@example.test", password="Complex-Password-731!")
        self.organization = Organization.objects.create(name="Organisation Programme", verification_status=Organization.VerificationStatus.VERIFIED)
        self.program = Program.objects.create(
            organization=self.organization,
            name="Programme privé",
            status=Program.Status.PRIVATE_ACTIVE,
            policy_version="v1",
            policy_hash="policy-hash",
            safe_harbor_version="v1",
        )
        self.scope = AssetScope.objects.create(program=self.program, asset="https://api.example.test", asset_type=AssetScope.AssetType.API, is_verified=True)
        AssetOwnershipProof.objects.create(scope=self.scope, evidence_reference="proof-001", reviewed_by_reference="reviewer-001", approved_at=timezone.now())
        ProgramPolicyVersion.objects.create(
            program=self.program, version="v1", content_hash="policy-hash", safe_harbor_text="Autorisation limitée", active=True
        )
        ProgramServiceLevel.objects.create(program=self.program)

    def test_private_program_requires_accepted_invitation(self):
        with self.assertRaises(PermissionDenied):
            require_research_scope(user=self.researcher, program=self.program, asset=self.scope.asset)
        ProgramInvitation.objects.create(
            program=self.program,
            researcher=self.researcher,
            accepted_at=timezone.now(),
            rules_accepted_at=timezone.now(),
        )
        self.assertEqual(require_research_scope(user=self.researcher, program=self.program, asset=self.scope.asset), self.scope)

    def test_scope_exclusion_and_unverified_asset_are_refused(self):
        self.program.status = Program.Status.PUBLIC_ACTIVE
        self.program.save(update_fields=["status"])
        self.scope.is_excluded = True
        self.scope.save(update_fields=["is_excluded"])
        with self.assertRaises(PermissionDenied):
            require_research_scope(user=self.outsider, program=self.program, asset=self.scope.asset)
        self.scope.is_excluded = False
        self.scope.is_verified = False
        self.scope.save(update_fields=["is_excluded", "is_verified"])
        with self.assertRaises(PermissionDenied):
            require_research_scope(user=self.outsider, program=self.program, asset=self.scope.asset)

    def test_public_program_allows_verified_in_scope_asset_only(self):
        self.program.status = Program.Status.PUBLIC_ACTIVE
        self.program.save(update_fields=["status"])
        self.assertEqual(require_research_scope(user=self.outsider, program=self.program, asset=self.scope.asset), self.scope)
        with self.assertRaises(PermissionDenied):
            require_research_scope(user=self.outsider, program=self.program, asset="https://outside.example.test")

    def test_emergency_close_blocks_all_research_access_and_records_decision(self):
        ProgramInvitation.objects.create(
            program=self.program,
            researcher=self.researcher,
            accepted_at=timezone.now(),
            rules_accepted_at=timezone.now(),
        )
        emergency_close(actor=self.owner, program=self.program, reason="Incident opérationnel")
        with self.assertRaises(PermissionDenied):
            require_research_scope(user=self.researcher, program=self.program, asset=self.scope.asset)
        self.assertEqual(self.program.decision_events.count(), 1)

    def test_unapproved_proof_rules_or_unverified_organization_block_access(self):
        invitation = ProgramInvitation.objects.create(
            program=self.program,
            researcher=self.researcher,
            accepted_at=timezone.now(),
        )
        with self.assertRaises(PermissionDenied):
            require_research_scope(user=self.researcher, program=self.program, asset=self.scope.asset)
        invitation.rules_accepted_at = timezone.now()
        invitation.save(update_fields=["rules_accepted_at"])
        self.scope.ownership_proof.approved_at = None
        self.scope.ownership_proof.save(update_fields=["approved_at"])
        with self.assertRaises(PermissionDenied):
            require_research_scope(user=self.researcher, program=self.program, asset=self.scope.asset)
        self.scope.ownership_proof.approved_at = timezone.now()
        self.scope.ownership_proof.save(update_fields=["approved_at"])
        self.organization.verification_status = Organization.VerificationStatus.PENDING
        self.organization.save(update_fields=["verification_status"])
        with self.assertRaises(PermissionDenied):
            require_research_scope(user=self.researcher, program=self.program, asset=self.scope.asset)
