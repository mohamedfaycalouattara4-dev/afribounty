from django.core.management.base import BaseCommand, CommandError

from apps.identity.models import User
from apps.integrations.models import TicketingIntegration
from apps.rewards.models import PaymentOrder


class Command(BaseCommand):
    help = "Signale les comptes et intégrations de démonstration qui ne doivent pas exister dans un dataset de production."

    def add_arguments(self, parser):
        parser.add_argument("--strict", action="store_true", help="Échoue si un artefact de démonstration est trouvé.")

    def handle(self, *args, **options):
        findings = {
            "comptes_example_test": User.objects.filter(email__iendswith="@example.test").count(),
            "ordres_sandbox": PaymentOrder.objects.filter(provider_code="sandbox-money").count(),
            "integrations_ticketing_sandbox": TicketingIntegration.objects.filter(provider_code="sandbox-ticketing").count(),
        }
        unsafe = {label: count for label, count in findings.items() if count}
        if unsafe:
            rendered = ", ".join(f"{label}={count}" for label, count in unsafe.items())
            message = f"Dataset non publiable : artefacts de démonstration détectés ({rendered})."
            if options["strict"]:
                raise CommandError(message)
            self.stdout.write(self.style.WARNING(message))
            return
        self.stdout.write(self.style.SUCCESS("Dataset vérifié : aucun artefact de démonstration connu détecté."))
