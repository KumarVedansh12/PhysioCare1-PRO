from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.core.emailing import send_templated_email


class Command(BaseCommand):
    help = "Send a real SMTP test email using the current .env configuration."

    def add_arguments(self, parser):
        parser.add_argument("--to", default=settings.CONTACT_EMAIL, help="Recipient email address")

    def handle(self, *args, **options):
        if not settings.EMAIL_ENABLED:
            raise CommandError(
                "Email is disabled. Add valid SMTP values, set EMAIL_ENABLED=1 in .env, "
                "restart the application, and run this command again."
            )
        recipient = options["to"].strip()
        if not recipient:
            raise CommandError("Pass --to or configure CONTACT_EMAIL in .env")
        sent = send_templated_email(
            event_key=f"smtp-test:{timezone.now().timestamp()}",
            recipient=recipient,
            subject="PhysioCare email configuration test",
            template_name="notification",
            context={
                "recipient_name": "Care team",
                "headline": "Email is working",
                "message": "PhysioCare successfully connected to your SMTP provider.",
                "action_url": settings.SITE_URL,
            },
        )
        if not sent:
            raise CommandError("Email failed. Check the Email delivery record and SMTP values in .env.")
        self.stdout.write(self.style.SUCCESS(f"Test email sent to {recipient}."))
