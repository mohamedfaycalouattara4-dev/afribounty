import json

from django.core.management.base import BaseCommand, CommandError

from apps.security.privilege_review import privilege_review_has_strict_failure, privilege_review_snapshot


class Command(BaseCommand):
    help = "Produit une revue locale, agrégée et sans secret des privilèges, sessions et clés API."

    def add_arguments(self, parser):
        parser.add_argument("--strict", action="store_true", help="Échoue en présence de sessions ou clés API expirées mais non révoquées.")

    def handle(self, *args, **options):
        report = privilege_review_snapshot()
        self.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True))
        if options["strict"] and privilege_review_has_strict_failure(snapshot=report):
            raise CommandError("Revue des privilèges en échec : sessions ou clés API expirées encore non révoquées.")
