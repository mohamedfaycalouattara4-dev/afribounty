import json

from django.core.management.base import BaseCommand, CommandError

from apps.reports.evidence_pipeline import evidence_pipeline_contract_report


class Command(BaseCommand):
    help = "Vérifie que le pipeline de preuves reste local et que les fournisseurs externes sont désactivés."

    def add_arguments(self, parser):
        parser.add_argument("--strict", action="store_true", help="Échoue si une activation, un fournisseur ou une libération externe est détecté.")

    def handle(self, *args, **options):
        report = evidence_pipeline_contract_report()
        self.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True))
        if options["strict"] and not report["valid"]:
            raise CommandError("Contrat local du pipeline de preuves en échec : activation externe non autorisée détectée.")
