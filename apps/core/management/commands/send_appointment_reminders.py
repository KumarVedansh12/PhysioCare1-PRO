import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections

from apps.core.emailing import send_due_appointment_reminders


class Command(BaseCommand):
    help = "Send idempotent 24-hour and 2-hour appointment reminder emails."

    def add_arguments(self, parser):
        parser.add_argument(
            "--watch", action="store_true",
            help="Keep polling using REMINDER_POLL_SECONDS (run as a worker process).",
        )

    def handle(self, *args, **options):
        if not settings.EMAIL_ENABLED:
            self.stdout.write(self.style.WARNING(
                "Email reminders are disabled. Set valid SMTP values and EMAIL_ENABLED=1 in .env, then restart the application."
            ))
            return
        while True:
            try:
                close_old_connections()
                sent = send_due_appointment_reminders()
                if sent:
                    self.stdout.write(self.style.SUCCESS(f"Sent {sent} appointment reminder(s)."))
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"Reminder cycle failed: {exc}"))
            finally:
                close_old_connections()

            if not options["watch"]:
                break
            try:
                time.sleep(settings.REMINDER_POLL_SECONDS)
            except KeyboardInterrupt:
                self.stdout.write("Reminder worker stopped.")
                break
