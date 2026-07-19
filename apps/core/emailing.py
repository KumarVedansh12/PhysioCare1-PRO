import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.urls import reverse

from .models import Appointment, EmailDelivery, EmailOTP


logger = logging.getLogger(__name__)
_logged_delivery_errors = set()


def _absolute_url(path="/"):
    return f"{settings.SITE_URL}/{path.lstrip('/')}"


def send_templated_email(
    *, event_key, recipient, subject, template_name, context=None, reply_to=None
):
    """Send one HTML + text email per event key and keep a retryable audit record."""
    if not settings.EMAIL_ENABLED or not recipient:
        return False

    delivery, _ = EmailDelivery.objects.get_or_create(
        event_key=event_key,
        defaults={
            "recipient": recipient,
            "subject": subject,
            "template_name": template_name,
        },
    )
    if delivery.status == "sent":
        return False
    if delivery.attempts >= settings.EMAIL_MAX_ATTEMPTS:
        return False

    stale_before = timezone.now() - timedelta(minutes=10)
    claimed = (
        EmailDelivery.objects.filter(pk=delivery.pk)
        .filter(
            Q(status__in=("pending", "failed"))
            | Q(status="sending", updated_at__lt=stale_before)
        )
        .update(status="sending", attempts=delivery.attempts + 1, last_error="")
    )
    if not claimed:
        return False

    email_context = {
        "site_url": settings.SITE_URL,
        "support_email": settings.CONTACT_EMAIL,
        **(context or {}),
    }
    try:
        text_body = render_to_string(f"emails/{template_name}.txt", email_context)
        html_body = render_to_string(f"emails/{template_name}.html", email_context)
        email = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[recipient],
            reply_to=[reply_to or settings.EMAIL_REPLY_TO]
            if (reply_to or settings.EMAIL_REPLY_TO)
            else None,
        )
        email.attach_alternative(html_body, "text/html")
        email.send(fail_silently=False)
    except Exception as exc:  # SMTP/provider errors must not break patient workflows.
        EmailDelivery.objects.filter(pk=delivery.pk).update(
            status="failed", last_error=str(exc)[:2000]
        )
        signature = (exc.__class__.__name__, str(exc))
        if signature not in _logged_delivery_errors:
            _logged_delivery_errors.add(signature)
            logger.error(
                "Email delivery is unavailable: %s. Check EMAIL_HOST and SMTP credentials in .env; repeated identical errors are suppressed.",
                exc,
            )
        else:
            logger.debug(
                "Suppressed repeated email error for event %s: %s", event_key, exc
            )
        return False

    EmailDelivery.objects.filter(pk=delivery.pk).update(
        status="sent", sent_at=timezone.now(), last_error=""
    )
    return True


@transaction.atomic
def issue_email_verification_otp(user):
    now = timezone.now()
    EmailOTP.objects.filter(
        user=user, purpose="verify_email", consumed_at__isnull=True
    ).update(consumed_at=now)
    code = f"{secrets.randbelow(1_000_000):06d}"
    otp = EmailOTP.objects.create(
        user=user,
        purpose="verify_email",
        code_hash=make_password(code),
        expires_at=now + timedelta(minutes=settings.OTP_EXPIRY_MINUTES),
    )
    sent = send_templated_email(
        event_key=f"email-verification:{otp.pk}",
        recipient=user.email,
        subject="Your PhysioCare verification code",
        template_name="verification_otp",
        context={
            "user": user,
            "code": code,
            "expiry_minutes": settings.OTP_EXPIRY_MINUTES,
            "verify_url": _absolute_url("verify-email/"),
        },
    )
    return otp, sent


def send_patient_invitation(user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    activation_path = reverse(
        "activate_patient_account", kwargs={"uidb64": uid, "token": token}
    )
    return send_templated_email(
        event_key=f"patient-invitation:{user.pk}:{timezone.now():%Y%m%d%H%M}",
        recipient=user.email,
        subject="Set up your PhysioCare patient account",
        template_name="patient_invitation",
        context={
            "user": user,
            "activation_url": _absolute_url(activation_path),
        },
    )


def send_appointment_emails(appointment, event):
    local_time = timezone.localtime(appointment.scheduled_at)
    labels = {
        "booked": ("Appointment booked", "Your appointment has been booked."),
        "rescheduled": (
            "Appointment rescheduled",
            "Your appointment time has been changed.",
        ),
        "cancelled": ("Appointment cancelled", "Your appointment has been cancelled."),
        "doctor_scheduled": (
            "Follow-up scheduled",
            "Your doctor scheduled a follow-up appointment.",
        ),
        "status_updated": (
            "Appointment status updated",
            f"Your appointment is now {appointment.get_status_display().lower()}.",
        ),
    }
    headline, message = labels[event]
    version = (
        local_time.strftime("%Y%m%d%H%M")
        if event in ("booked", "rescheduled", "doctor_scheduled")
        else appointment.status
    )
    patient_sent = send_templated_email(
        event_key=f"appointment:{appointment.pk}:{event}:{version}:patient",
        recipient=appointment.patient.user.email,
        subject=f"{headline} — PhysioCare",
        template_name="appointment_update",
        context={
            "recipient_name": appointment.patient.user.first_name
            or str(appointment.patient),
            "headline": headline,
            "message": message,
            "appointment": appointment,
            "appointment_time": local_time,
            "action_url": _absolute_url("appointments/"),
        },
    )
    doctor_sent = send_templated_email(
        event_key=f"appointment:{appointment.pk}:{event}:{version}:doctor",
        recipient=appointment.doctor.user.email,
        subject=f"{headline}: {appointment.patient} — PhysioCare",
        template_name="doctor_notification",
        context={
            "doctor": appointment.doctor,
            "headline": headline,
            "message": f"{appointment.patient} — {message.lower()}",
            "patient": appointment.patient,
            "appointment": appointment,
            "appointment_time": local_time,
            "action_url": _absolute_url("doctor/calendar/"),
        },
    )
    return patient_sent, doctor_sent


def send_user_notification_email(*, user, title, message, action_path, event_key):
    return send_templated_email(
        event_key=event_key,
        recipient=user.email,
        subject=f"{title} — PhysioCare",
        template_name="notification",
        context={
            "recipient_name": user.first_name or user.username,
            "headline": title,
            "message": message,
            "action_url": _absolute_url(action_path),
        },
    )


def send_due_appointment_reminders(now=None):
    now = now or timezone.now()
    appointments = Appointment.objects.filter(
        status__in=("confirmed", "pending"),
        scheduled_at__gt=now,
        scheduled_at__lte=now + timedelta(hours=24),
        reminder_channel__icontains="email",
    ).select_related("patient__user", "doctor__user")
    sent_count = 0
    for appointment in appointments.iterator():
        remaining = appointment.scheduled_at - now
        window = "2-hour" if remaining <= timedelta(hours=2) else "24-hour"
        local_time = timezone.localtime(appointment.scheduled_at)
        schedule_version = int(appointment.scheduled_at.timestamp())
        sent = send_templated_email(
            event_key=f"appointment:{appointment.pk}:reminder:{schedule_version}:{window}",
            recipient=appointment.patient.user.email,
            subject=f"Reminder: appointment with {appointment.doctor} — PhysioCare",
            template_name="appointment_reminder",
            context={
                "recipient_name": appointment.patient.user.first_name
                or str(appointment.patient),
                "appointment": appointment,
                "appointment_time": local_time,
                "window": window,
                "action_url": _absolute_url("appointments/"),
            },
        )
        sent_count += int(sent)
    return sent_count
