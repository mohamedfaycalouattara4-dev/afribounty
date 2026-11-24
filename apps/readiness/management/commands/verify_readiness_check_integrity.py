import json

from django.core.management.base import BaseCommand, CommandError

from apps.readiness.services import readiness_check_integrity_report


class Command(BaseCommand):
    help = "Vérifie les digests append-only des contrôles locaux de préparation."

    def add_arguments(self, parser):
        parser.add_argument("--strict", action="store_true", help="Échoue si une divergence locale est détectée.")

    def handle(self, *args, **options):
        report = readiness_check_integrity_report()
        self.stdout.write(json.dumps(report, sort_keys=True))
        if options["strict"] and not report["valid"]:
            raise CommandError("Divergence détectée dans les contrôles de préparation append-only.")
