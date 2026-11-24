from django.core.exceptions import PermissionDenied, ValidationError

from apps.organizations.models import (
    ConflictDeclaration,
    Organization,
    OrganizationChangeEvent,
    OrganizationMembership,
    OrganizationVerification,
    SecurityContact,
)


ROLE_PERMISSIONS = {
    OrganizationMembership.Role.OWNER: {
        "member.manage",
        "settings.manage",
        "export.request",
        "contact.manage",
        "contact.view",
        "program.manage",
        "report.message",
    },
    OrganizationMembership.Role.PROGRAM_MANAGER: {"program.manage", "contact.view", "report.message"},
    OrganizationMembership.Role.TRIAGER: {"report.triage", "report.message"},
    OrganizationMembership.Role.VIEWER: {"organization.view"},
}


def require_organization_permission(*, user, organization: Organization, permission: str) -> OrganizationMembership:
    membership = OrganizationMembership.objects.filter(organization=organization, user=user).first()
    if membership is None or permission not in ROLE_PERMISSIONS[membership.role]:
        raise PermissionDenied("Accès organisationnel refusé.")
    if ConflictDeclaration.objects.filter(organization=organization, user=user, active=True).exists():
        raise PermissionDenied("Accès refusé en raison d’un conflit d’intérêt actif.")
    return membership


def record_organization_change(*, organization: Organization, actor, action: str, metadata: dict | None = None) -> OrganizationChangeEvent:
    return OrganizationChangeEvent.objects.create(organization=organization, actor=actor, action=action, metadata=metadata or {})


def delegate_membership(*, actor, target_user, organization: Organization, role: str) -> OrganizationMembership:
    require_organization_permission(user=actor, organization=organization, permission="member.manage")
    membership, _ = OrganizationMembership.objects.update_or_create(organization=organization, user=target_user, defaults={"role": role})
    record_organization_change(organization=organization, actor=actor, action="membership.delegated", metadata={"role": role})
    return membership


def add_security_contact(*, actor, organization: Organization, label: str, email: str, emergency: bool) -> SecurityContact:
    require_organization_permission(user=actor, organization=organization, permission="contact.manage")
    normalized_label = label.strip()
    normalized_email = email.strip().lower()
    if not normalized_label or not normalized_email:
        raise ValidationError("Le libellé et l’e-mail du contact de sécurité sont obligatoires.")
    contact, created = SecurityContact.objects.update_or_create(
        organization=organization,
        label=normalized_label,
        defaults={"email": normalized_email, "emergency": emergency},
    )
    record_organization_change(
        organization=organization,
        actor=actor,
        action="security_contact.created" if created else "security_contact.updated",
        metadata={"contact_id": contact.id, "emergency": emergency},
    )
    return contact


def declare_conflict(*, actor, organization: Organization, target_user, reason: str) -> ConflictDeclaration:
    require_organization_permission(user=actor, organization=organization, permission="member.manage")
    if not OrganizationMembership.objects.filter(organization=organization, user=target_user).exists():
        raise ValidationError("La personne concernée doit déjà être membre de l’organisation.")
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise ValidationError("Un conflit d’intérêt exige un motif explicite.")
    conflict, created = ConflictDeclaration.objects.update_or_create(
        organization=organization,
        user=target_user,
        defaults={"reason": normalized_reason, "active": True},
    )
    record_organization_change(
        organization=organization,
        actor=actor,
        action="conflict.declared" if created else "conflict.updated",
        metadata={"user_id": target_user.id},
    )
    return conflict


def set_verification_status(*, organization: Organization, status: str, reviewer_reference: str, notes: str = "") -> OrganizationVerification:
    verification, _ = OrganizationVerification.objects.get_or_create(organization=organization)
    verification.status = status
    verification.reviewer_reference = reviewer_reference
    verification.notes = notes.strip()
    verification.save(update_fields=["status", "reviewer_reference", "notes", "updated_at"])
    organization.verification_status = status
    organization.save(update_fields=["verification_status"])
    return verification


def visible_security_contacts(*, user, organization: Organization):
    require_organization_permission(user=user, organization=organization, permission="contact.view")
    return SecurityContact.objects.filter(organization=organization).order_by("id")


def export_organization_data(*, user, organization: Organization) -> dict:
    require_organization_permission(user=user, organization=organization, permission="export.request")
    if not organization.exports_enabled:
        raise PermissionDenied("Les exports sont désactivés pour cette organisation.")
    record_organization_change(organization=organization, actor=user, action="organization.exported")
    return {
        "organization": {"name": organization.name, "verification_status": organization.verification_status},
        "contacts": [{"label": item.label, "emergency": item.emergency} for item in organization.security_contacts.all()],
        "retention_days": organization.privacy_retention_days,
    }
