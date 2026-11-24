import json

from django.core.management.base import BaseCommand, CommandError

from apps.reports.services import report_scope_integrity_report


class Command(BaseCommand):
    help = "Vérifie localement les empreintes des instantanés de scope de rapports, sans modifier les rapports."

    def add_arguments(self, parser):
        parser.add_argument("--strict", action="store_true", help="Échoue si un instantané est absent ou incohérent.")

    def handle(self, *args, **options):
        report = report_scope_integrity_report()
        self.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True))
        if options["strict"] and not report["valid"]:
            raise CommandError("Intégrité des scopes de rapports en échec : instantané absent ou empreinte incohérente.")
