import json

from django.core.management.base import BaseCommand, CommandError

from apps.security.privilege_review import privilege_review_snapshot_integrity_report


class Command(BaseCommand):
    help = "Vérifie localement les empreintes des instantanés append-only de revue des privilèges."

    def add_arguments(self, parser):
        parser.add_argument("--strict", action="store_true", help="Échoue si une divergence d’empreinte est détectée.")

    def handle(self, *args, **options):
        report = privilege_review_snapshot_integrity_report()
        self.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True))
        if options["strict"] and not report["valid"]:
            raise CommandError("Intégrité des instantanés de privilèges en échec : divergence locale détectée.")
