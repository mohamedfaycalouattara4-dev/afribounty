import json

from django.core.management.base import BaseCommand
from django.db import connection

from apps.identity.models import User
from apps.reports.models import EvidencePipelineState, Report, ReportRelation, ReportSlaEscalationEvent, ReportSlaState
from apps.security.models import AuditEvent


class Command(BaseCommand):
    help = "Produit les compteurs non sensibles nécessaires à la comparaison d’un exercice de restauration local."

    def handle(self, *args, **options):
        payload = {
            "audit_events": AuditEvent.objects.count(),
            "database_vendor": connection.vendor,
            "evidence_pipeline_states": EvidencePipelineState.objects.count(),
            "report_relations": ReportRelation.objects.count(),
            "report_sla_escalations": ReportSlaEscalationEvent.objects.count(),
            "report_sla_states": ReportSlaState.objects.count(),
            "reports": Report.objects.count(),
            "users": User.objects.count(),
        }
        self.stdout.write(json.dumps(payload, sort_keys=True))
