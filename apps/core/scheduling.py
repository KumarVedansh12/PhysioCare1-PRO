from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import transaction

from .models import DoctorProfile


@transaction.atomic
def save_appointment_safely(form, **overrides):
    """Serialize bookings per doctor and revalidate inside the lock."""
    appointment = form.save(commit=False)
    for field, value in overrides.items():
        setattr(appointment, field, value)
    DoctorProfile.objects.select_for_update().get(pk=appointment.doctor_id)
    appointment.full_clean()
    appointment.save()
    if hasattr(form, "save_m2m"):
        form.save_m2m()
    return appointment


def add_validation_error_to_form(form, error):
    if not isinstance(error, ValidationError):
        form.add_error(None, str(error))
        return
    if hasattr(error, "message_dict"):
        for field, messages in error.message_dict.items():
            target = (
                None if field == NON_FIELD_ERRORS or field not in form.fields else field
            )
            for message in messages:
                form.add_error(target, message)
    else:
        for message in error.messages:
            form.add_error(None, message)
