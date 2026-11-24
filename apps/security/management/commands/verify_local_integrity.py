import json

from django.core.management.base import BaseCommand, CommandError

from apps.readiness.services import local_integrity_report


class Command(BaseCommand):
    help = "Agrège les contrôles locaux d’intégrité sans révéler de dossier, secret ou fournisseur externe."

    def add_arguments(self, parser):
        parser.add_argument("--strict", action="store_true", help="Échoue lorsqu’un des contrôles d’intégrité locaux est en échec.")

    def handle(self, *args, **options):
        report = local_integrity_report()
        self.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True))
        if options["strict"] and not report["valid"]:
            raise CommandError("Vérification consolidée d’intégrité locale en échec.")
