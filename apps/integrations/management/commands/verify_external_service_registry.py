import json

from django.core.management.base import BaseCommand, CommandError

from apps.integrations.external_readiness import external_service_registry_integrity_report


class Command(BaseCommand):
    help = "Vérifie que le registre local des dépendances externes reste désactivé."

    def add_arguments(self, parser):
        parser.add_argument("--strict", action="store_true", help="Échoue si un service n’est plus strictement désactivé.")

    def handle(self, *args, **options):
        report = external_service_registry_integrity_report()
        self.stdout.write(json.dumps(report, sort_keys=True))
        if options["strict"] and not report["valid"]:
            raise CommandError("Divergence détectée dans le registre des dépendances externes désactivées.")
