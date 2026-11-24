from django.core.management.base import BaseCommand, CommandError

from apps.security.audit import verify_audit_event
from apps.security.models import AuditEvent


class Command(BaseCommand):
    help = "Vérifie les signatures cryptographiques des événements d’audit append-only."

    def add_arguments(self, parser):
        parser.add_argument("--strict", action="store_true", help="Échoue si un événement absent ou invalide est détecté.")

    def handle(self, *args, **options):
        invalid_ids = [event.id for event in AuditEvent.objects.iterator() if not verify_audit_event(event)]
        if invalid_ids:
            message = f"{len(invalid_ids)} événement(s) d’audit invalide(s) ou non signé(s) : {', '.join(map(str, invalid_ids[:20]))}"
            if options["strict"]:
                raise CommandError(message)
            self.stderr.write(self.style.WARNING(message))
            return
        self.stdout.write(self.style.SUCCESS("Intégrité des événements d’audit vérifiée."))
