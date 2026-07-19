from datetime import date, datetime, time, timedelta
from io import BytesIO
import csv
import logging
import mimetypes
from pathlib import Path
import uuid

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import check_password
from django.contrib.auth.models import Group, User
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import connection
from django.db.models import Avg, Count, Q, Sum
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.encoding import force_str
from django.utils.http import url_has_allowed_host_and_scheme, urlsafe_base64_decode
from django.urls import reverse, reverse_lazy
from django.views.decorators.http import require_POST

from .access import (
    ADMIN_SECTION_CAPABILITIES,
    has_capability,
    is_receptionist,
    portal_home_url,
)
from .backups import build_encrypted_backup
from .emailing import (
    issue_email_verification_otp,
    send_appointment_emails,
    send_patient_invitation,
    send_templated_email,
    send_user_notification_email,
)
from .forms import (
    AdminDoctorForm,
    AdminEmployeeForm,
    AdminStaffForm,
    AppointmentForm,
    ChatForm,
    ClinicalSessionForm,
    CMSContentForm,
    ContactForm,
    DoctorDocumentForm,
    DoctorExerciseForm,
    DoctorFeedbackForm,
    DoctorFollowUpForm,
    DoctorPrescriptionForm,
    DoctorReplyForm,
    DoctorTreatmentForm,
    FeedbackForm,
    MedicalRecordForm,
    PaymentForm,
    ProfileForm,
    ProgressForm,
    ReceptionAppointmentForm,
    ReceptionPatientForm,
    ReceptionPaymentForm,
    RegisterForm,
    RoleAssignmentForm,
    OTPVerificationForm,
)
from .models import (
    Appointment,
    ChatMessage,
    CMSContent,
    ContactMessage,
    DoctorProfile,
    EmailOTP,
    EmployeeProfile,
    Exercise,
    ExerciseAssignment,
    Feedback,
    MedicalRecord,
    Notification,
    PatientProfile,
    Payment,
    Prescription,
    TreatmentPlan,
)
from .scheduling import add_validation_error_to_form, save_appointment_safely


logger = logging.getLogger(__name__)


def health_check(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return JsonResponse(
            {"status": "unhealthy", "database": "unavailable"}, status=503
        )
    return JsonResponse({"status": "ok", "database": "postgresql"})


def home(request):
    return render(
        request,
        "home/index.html",
        {
            "doctor_count": DoctorProfile.objects.count(),
            "review_count": Feedback.objects.count(),
        },
    )


def register_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        user.is_active = False
        user.save(update_fields=["is_active"])
        request.session["pending_verification_user_id"] = user.pk
        _, sent = issue_email_verification_otp(user)
        if sent:
            messages.success(
                request, "We sent a 6-digit verification code to your email."
            )
        else:
            messages.warning(
                request,
                "Your account was created, but the email could not be sent. Check the email settings and use Resend code.",
            )
        return redirect("verify_email")
    return render(request, "accounts/register.html", {"form": form})


def verify_email(request):
    user_id = request.session.get("pending_verification_user_id")
    user = User.objects.filter(pk=user_id).first() if user_id else None
    if not user:
        messages.error(request, "Start by creating your patient account.")
        return redirect("register")

    form = OTPVerificationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        otp = EmailOTP.objects.filter(
            user=user, purpose="verify_email", consumed_at__isnull=True
        ).first()
        now = timezone.now()
        if not otp or otp.expires_at <= now:
            if otp:
                otp.consumed_at = now
                otp.save(update_fields=["consumed_at"])
            form.add_error("code", "This code has expired. Request a new code below.")
        else:
            otp.attempts += 1
            if check_password(form.cleaned_data["code"], otp.code_hash):
                otp.consumed_at = now
                otp.save(update_fields=["attempts", "consumed_at"])
                user.is_active = True
                user.save(update_fields=["is_active"])
                profile = _patient(user)
                profile.email_verified_at = now
                profile.save(update_fields=["email_verified_at"])
                request.session.pop("pending_verification_user_id", None)
                login(
                    request, user, backend="django.contrib.auth.backends.ModelBackend"
                )
                messages.success(
                    request, "Email verified. Welcome to your PhysioCare dashboard."
                )
                return redirect("dashboard")
            if otp.attempts >= settings.OTP_MAX_ATTEMPTS:
                otp.consumed_at = now
                otp.save(update_fields=["attempts", "consumed_at"])
                form.add_error("code", "Too many attempts. Request a new code.")
            else:
                otp.save(update_fields=["attempts"])
                form.add_error("code", "That code is not correct. Please try again.")
    return render(
        request, "accounts/verify_email.html", {"form": form, "email": user.email}
    )


def resend_verification_email(request):
    if request.method != "POST":
        return redirect("verify_email")
    user_id = request.session.get("pending_verification_user_id")
    user = User.objects.filter(pk=user_id).first() if user_id else None
    if not user:
        return redirect("register")
    latest = user.email_otps.first()
    if latest and latest.created_at > timezone.now() - timedelta(
        seconds=settings.OTP_RESEND_SECONDS
    ):
        messages.warning(
            request,
            f"Please wait {settings.OTP_RESEND_SECONDS} seconds before requesting another code.",
        )
    else:
        _, sent = issue_email_verification_otp(user)
        if sent:
            messages.success(request, "A new verification code was sent.")
        else:
            messages.error(
                request,
                "We could not send the code. Please contact the clinic or check SMTP configuration.",
            )
    return redirect("verify_email")


class PortalPasswordResetView(auth_views.PasswordResetView):
    template_name = "accounts/password_reset_form.html"
    email_template_name = "emails/password_reset.txt"
    html_email_template_name = "emails/password_reset.html"
    subject_template_name = "emails/password_reset_subject.txt"
    success_url = reverse_lazy("password_reset_done")

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields["email"].widget.attrs.update(
            {
                "class": "form-control",
                "autocomplete": "email",
                "placeholder": "you@example.com",
            }
        )
        return form

    def form_valid(self, form):
        try:
            return super().form_valid(form)
        except Exception:
            logger.exception("Password reset email could not be sent")
            form.add_error(
                None,
                "We could not send the reset email. Please try again later or contact the clinic.",
            )
            return self.form_invalid(form)


def contact(request):
    form = ContactForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        item = form.save()
        clinic_sent = send_templated_email(
            event_key=f"contact:{item.pk}:clinic",
            recipient=settings.CONTACT_EMAIL,
            subject=f"New website enquiry: {item.subject}",
            template_name="contact_clinic",
            context={"contact": item},
            reply_to=item.email,
        )
        send_templated_email(
            event_key=f"contact:{item.pk}:confirmation",
            recipient=item.email,
            subject="We received your PhysioCare enquiry",
            template_name="contact_confirmation",
            context={"contact": item},
        )
        if clinic_sent:
            messages.success(
                request, "Thank you. Your message was sent to our care team."
            )
        else:
            messages.warning(
                request,
                "Your message was saved securely. Our email service is temporarily unavailable, so the clinic will review it in the portal.",
            )
        return redirect("contact")
    return render(request, "contact/contact.html", {"form": form})


def activate_patient_account(request, uidb64, token):
    try:
        user = User.objects.get(pk=force_str(urlsafe_base64_decode(uidb64)))
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None
    if not user or not default_token_generator.check_token(user, token):
        messages.error(request, "This account setup link is invalid or has expired.")
        return redirect("password_reset")
    profile = getattr(user, "patient_profile", None)
    if profile and not profile.email_verified_at:
        profile.email_verified_at = timezone.now()
        profile.save(update_fields=["email_verified_at"])
    return redirect("password_reset_confirm", uidb64=uidb64, token=token)


def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    if request.method == "POST":
        username = request.POST.get("username", "")
        password = request.POST.get("password", "")
        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            next_url = request.GET.get("next", "")
            if next_url and url_has_allowed_host_and_scheme(
                next_url,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            ):
                return redirect(next_url)
            return redirect(portal_home_url(user))
        inactive_user = User.objects.filter(username=username, is_active=False).first()
        if (
            inactive_user
            and inactive_user.check_password(password)
            and hasattr(inactive_user, "patient_profile")
        ):
            request.session["pending_verification_user_id"] = inactive_user.pk
            latest = inactive_user.email_otps.first()
            if not latest or latest.created_at <= timezone.now() - timedelta(
                seconds=settings.OTP_RESEND_SECONDS
            ):
                issue_email_verification_otp(inactive_user)
            messages.info(
                request,
                "Verify your email before signing in. We sent a new code if the resend wait has passed.",
            )
            return redirect("verify_email")
        messages.error(request, "We could not sign you in. Please check your details.")
    return render(request, "accounts/login.html")


def logout_view(request):
    logout(request)
    return redirect("home")


def _patient(user):
    profile, _ = PatientProfile.objects.get_or_create(user=user)
    return profile


@login_required
def dashboard(request):
    if _is_receptionist(request.user):
        return redirect("reception_dashboard")
    if has_capability(request.user, "admin.dashboard"):
        return redirect("admin_dashboard")
    if hasattr(request.user, "doctor_profile"):
        return redirect("doctor_dashboard")
    if has_capability(request.user, "admin.payments"):
        return redirect("admin_manage", section="payments")
    if has_capability(request.user, "admin.cms"):
        return redirect("admin_manage", section="cms")
    if request.user.is_staff:
        messages.error(
            request, "Your staff account does not have an assigned portal role."
        )
        return redirect("home")
    patient = _patient(request.user)
    now = timezone.now()
    upcoming = patient.appointments.filter(scheduled_at__gte=now).exclude(
        status="cancelled"
    )[:3]
    recent_appointments = patient.appointments.filter(scheduled_at__lt=now).order_by(
        "-scheduled_at"
    )[:3]
    active_plan = patient.treatment_plans.filter(active=True).first()
    progress_entries = list(patient.progress_entries.all())
    prescriptions = patient.prescriptions.all()[:3]
    assignments = patient.exercise_assignments.select_related("exercise")[:4]
    pain_change = 0
    if len(progress_entries) >= 2:
        pain_change = progress_entries[0].pain_score - progress_entries[-1].pain_score
    return render(
        request,
        "dashboard/dashboard.html",
        {
            "patient": patient,
            "upcoming": upcoming,
            "recent_appointments": recent_appointments,
            "active_plan": active_plan,
            "prescriptions": prescriptions,
            "assignments": assignments,
            "progress_entries": progress_entries,
            "pain_change": pain_change,
            "notifications": request.user.portal_notifications.all()[:4],
        },
    )


@login_required
def profile_view(request):
    patient = _patient(request.user)
    previous_email = patient.user.email
    form = ProfileForm(request.POST or None, instance=patient)
    if request.method == "POST" and form.is_valid():
        patient = form.save()
        if patient.user.email.lower() != previous_email.lower():
            patient.email_verified_at = None
            patient.save(update_fields=["email_verified_at"])
            patient.user.is_active = False
            patient.user.save(update_fields=["is_active"])
            request.session["pending_verification_user_id"] = patient.user_id
            _, sent = issue_email_verification_otp(patient.user)
            if sent:
                messages.success(
                    request,
                    "Your profile was updated. Verify your new email address to continue.",
                )
            else:
                messages.warning(
                    request,
                    "Your profile was updated, but the verification email failed. Use Resend code after checking SMTP.",
                )
            return redirect("verify_email")
        messages.success(request, "Your profile and medical history have been updated.")
        return redirect("profile")
    previous = patient.treatment_plans.filter(active=False)
    return render(
        request,
        "profile/profile.html",
        {"patient": patient, "form": form, "previous_treatments": previous},
    )


@login_required
def book_appointment(request):
    patient = _patient(request.user)
    initial = {"scheduled_at": timezone.localtime() + timedelta(days=1, hours=2)}
    form = AppointmentForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            appointment = save_appointment_safely(
                form, patient=patient, status="confirmed"
            )
        except ValidationError as exc:
            add_validation_error_to_form(form, exc)
            appointment = None
        if appointment:
            Notification.objects.create(
                user=request.user,
                title="Appointment confirmed",
                message=f"Your session with {appointment.doctor} is booked for {timezone.localtime(appointment.scheduled_at):%d %b at %I:%M %p}.",
                notification_type="appointment",
                action_url="/appointments/",
            )
            send_appointment_emails(appointment, "booked")
            messages.success(
                request,
                "Appointment booked. Your reminder preferences have been saved.",
            )
            return redirect("appointment_history")
    return render(
        request,
        "appointments/book.html",
        {"form": form, "doctors": DoctorProfile.objects.filter(available=True)},
    )


@login_required
def appointment_history(request):
    patient = _patient(request.user)
    appointments = patient.appointments.select_related("doctor__user").order_by(
        "-scheduled_at"
    )
    return render(
        request,
        "appointments/history.html",
        {"appointments": appointments, "now": timezone.now()},
    )


@login_required
def reschedule_appointment(request, pk):
    appointment = get_object_or_404(Appointment, pk=pk, patient=_patient(request.user))
    form = AppointmentForm(request.POST or None, instance=appointment)
    if request.method == "POST" and form.is_valid():
        try:
            appointment = save_appointment_safely(form)
        except ValidationError as exc:
            add_validation_error_to_form(form, exc)
            appointment = None
        if appointment:
            send_appointment_emails(appointment, "rescheduled")
            messages.success(request, "Your appointment has been rescheduled.")
            return redirect("appointment_history")
    return render(
        request, "appointments/book.html", {"form": form, "rescheduling": True}
    )


@login_required
def cancel_appointment(request, pk):
    appointment = get_object_or_404(Appointment, pk=pk, patient=_patient(request.user))
    if request.method == "POST":
        appointment.status = "cancelled"
        appointment.save(update_fields=["status", "updated_at"])
        send_appointment_emails(appointment, "cancelled")
        messages.success(request, "The appointment has been cancelled.")
    return redirect("appointment_history")


@login_required
def treatment_plan(request):
    patient = _patient(request.user)
    return render(
        request,
        "treatment/treatment_plan.html",
        {
            "plans": patient.treatment_plans.select_related("doctor__user"),
            "assignments": patient.exercise_assignments.select_related(
                "exercise", "assigned_by__user"
            ),
        },
    )


@login_required
def exercise_library(request):
    patient = _patient(request.user)
    return render(
        request,
        "exercises/exercise_videos.html",
        {
            "assignments": patient.exercise_assignments.select_related(
                "exercise", "assigned_by__user"
            ),
            "exercises": Exercise.objects.all(),
        },
    )


@login_required
def complete_exercise(request, pk):
    assignment = get_object_or_404(
        ExerciseAssignment, pk=pk, patient=_patient(request.user)
    )
    if request.method == "POST":
        assignment.completed_today = not assignment.completed_today
        assignment.save(update_fields=["completed_today"])
        messages.success(request, "Exercise progress updated.")
    return redirect("exercise_videos")


@login_required
def reports(request):
    patient = _patient(request.user)
    form = MedicalRecordForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        record = form.save(commit=False)
        record.patient = patient
        record.save()
        doctor = (
            patient.treatment_plans.filter(active=True)
            .select_related("doctor__user")
            .first()
        )
        if doctor:
            send_user_notification_email(
                user=doctor.doctor.user,
                title=f"New report from {patient}",
                message=f"{patient} uploaded {record.title}. Review it in the patient timeline.",
                action_path=f"doctor/patients/{patient.pk}/",
                event_key=f"medical-record:{record.pk}:doctor",
            )
        messages.success(request, "Your report was uploaded securely.")
        return redirect("reports")
    return render(
        request,
        "reports/reports.html",
        {
            "form": form,
            "records": patient.medical_records.all(),
            "prescriptions": patient.prescriptions.all(),
        },
    )


def _private_file_response(field_file):
    if not field_file or not field_file.name:
        raise Http404("File not found")
    try:
        field_file.open("rb")
    except (FileNotFoundError, OSError, ValueError) as exc:
        logger.warning("Private file is unavailable: %s", field_file.name)
        raise Http404("File not found") from exc
    filename = Path(field_file.name).name
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    response = FileResponse(
        field_file,
        as_attachment=True,
        filename=filename,
        content_type=content_type,
    )
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["Pragma"] = "no-cache"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
def medical_record_download(request, pk):
    record = get_object_or_404(
        MedicalRecord.objects.select_related("patient__user"), pk=pk
    )
    authorised = record.patient.user_id == request.user.id or request.user.is_superuser
    doctor = getattr(request.user, "doctor_profile", None)
    if doctor and not authorised:
        authorised = _doctor_patients(doctor).filter(pk=record.patient_id).exists()
    if not authorised:
        raise Http404("Medical record not found")
    return _private_file_response(record.file)


@login_required
def chat_attachment_download(request, pk):
    message = get_object_or_404(ChatMessage, pk=pk)
    if (
        request.user.id not in (message.sender_id, message.recipient_id)
        and not request.user.is_superuser
    ):
        raise Http404("Attachment not found")
    return _private_file_response(message.attachment)


def _pdf_response(filename, title, lines):
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas

        buffer = BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4
        pdf.setTitle(title)
        pdf.setFillColorRGB(0.11, 0.30, 0.25)
        pdf.setFont("Helvetica-Bold", 22)
        pdf.drawString(56, height - 65, "PhysioCare")
        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(56, height - 100, title)
        y = height - 138
        pdf.setFillColorRGB(0.16, 0.22, 0.20)
        for line in lines:
            pdf.setFont("Helvetica", 11)
            for part in str(line).splitlines() or [""]:
                pdf.drawString(56, y, part[:92])
                y -= 18
                if y < 60:
                    pdf.showPage()
                    y = height - 60
            y -= 4
        pdf.save()
        response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    except ImportError:
        response = HttpResponse(
            "\n".join([title, ""] + [str(x) for x in lines]), content_type="text/plain"
        )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
def prescription_pdf(request, pk):
    item = get_object_or_404(Prescription, pk=pk, patient=_patient(request.user))
    return _pdf_response(
        f"prescription-{item.pk}.pdf",
        "Digital Prescription",
        [
            f"Patient: {item.patient}",
            f"Issued: {item.issued_on:%d %B %Y}",
            f"Doctor: {item.doctor}",
            f"Diagnosis: {item.diagnosis}",
            "Medicines:",
            item.medicines,
            "Instructions:",
            item.instructions,
        ],
    )


@login_required
def progress(request):
    patient = _patient(request.user)
    form = ProgressForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        entry = form.save(commit=False)
        entry.patient = patient
        entry.save()
        messages.success(request, "Today's progress has been recorded.")
        return redirect("progress")
    entries = list(patient.progress_entries.all())
    return render(
        request,
        "progress/progress.html",
        {
            "form": form,
            "entries": entries,
            "plan": patient.treatment_plans.filter(active=True).first(),
        },
    )


def _care_doctor_for_patient(patient):
    plan = (
        patient.treatment_plans.filter(
            active=True, doctor__available=True, doctor__user__is_active=True
        )
        .select_related("doctor__user")
        .order_by("-started_on", "-pk")
        .first()
    )
    if plan:
        return plan.doctor
    upcoming = (
        patient.appointments.filter(
            scheduled_at__gte=timezone.now(),
            doctor__available=True,
            doctor__user__is_active=True,
        )
        .exclude(status__in=("cancelled", "no_show", "completed"))
        .select_related("doctor__user")
        .order_by("scheduled_at")
        .first()
    )
    if upcoming:
        return upcoming.doctor
    previous = (
        patient.appointments.filter(
            doctor__available=True, doctor__user__is_active=True
        )
        .exclude(status__in=("cancelled", "no_show"))
        .select_related("doctor__user")
        .order_by("-scheduled_at")
        .first()
    )
    if previous:
        return previous.doctor
    prescription = (
        patient.prescriptions.filter(
            doctor__available=True, doctor__user__is_active=True
        )
        .select_related("doctor__user")
        .order_by("-issued_on", "-pk")
        .first()
    )
    return prescription.doctor if prescription else None


@login_required
def chat(request):
    patient = _patient(request.user)
    doctor = _care_doctor_for_patient(patient)
    form = ChatForm(request.POST or None, request.FILES or None)
    if request.method == "POST":
        if not doctor:
            messages.error(
                request, "Book an appointment before starting a doctor conversation."
            )
            return redirect("chat")
        if form.is_valid():
            message = form.save(commit=False)
            message.sender = request.user
            message.recipient = doctor.user
            if message.attachment and message.message_type == "text":
                message.message_type = "report"
            message.save()
            send_user_notification_email(
                user=doctor.user,
                title=f"New message from {patient}",
                message=message.body[:300]
                or "A secure attachment was shared with you.",
                action_path=f"doctor/messages/?patient={patient.pk}",
                event_key=f"chat-message:{message.pk}:recipient",
            )
            messages.success(request, "Your message was sent securely.")
            return redirect("chat")
    conversation = ChatMessage.objects.none()
    if doctor:
        conversation = ChatMessage.objects.filter(
            Q(sender=request.user, recipient=doctor.user)
            | Q(sender=doctor.user, recipient=request.user)
        )
    conversation.filter(recipient=request.user).update(is_read=True)
    return render(
        request,
        "chat/chat.html",
        {"form": form, "doctor": doctor, "conversation": conversation},
    )


@login_required
def video_consultation(request):
    patient = _patient(request.user)
    upcoming = (
        patient.appointments.filter(mode="video", scheduled_at__gte=timezone.now())
        .exclude(status="cancelled")
        .first()
    )
    return render(
        request,
        "consultation/video_call.html",
        {"appointment": upcoming, "work_in_progress": True},
    )


@login_required
def follow_up(request):
    patient = _patient(request.user)
    doctor = _care_doctor_for_patient(patient)
    if request.method == "POST":
        if not doctor:
            messages.error(
                request, "Book an appointment before requesting a doctor follow-up."
            )
            return redirect("chat")
        recipient = doctor.user
        followup_message = ChatMessage.objects.create(
            sender=request.user,
            recipient=recipient,
            body="I would like to request a follow-up appointment.",
        )
        Notification.objects.create(
            user=recipient,
            title="Follow-up requested",
            message=f"{patient} requested a follow-up appointment.",
            notification_type="followup",
        )
        send_user_notification_email(
            user=recipient,
            title="Follow-up requested",
            message=f"{patient} requested a follow-up appointment.",
            action_path=f"doctor/messages/?patient={patient.pk}",
            event_key=f"followup-request:{followup_message.pk}:doctor",
        )
        messages.success(request, "Your follow-up request was sent to the care team.")
    return redirect("chat")


@login_required
def notifications_view(request):
    return render(
        request,
        "notifications/notifications.html",
        {"notifications": request.user.portal_notifications.all()},
    )


@login_required
def mark_notifications_read(request):
    if request.method == "POST":
        request.user.portal_notifications.update(is_read=True)
    return redirect("notifications")


@login_required
def payments(request):
    patient = _patient(request.user)
    all_payments = patient.payments.all()
    pending_total = (
        all_payments.filter(status="pending").aggregate(total=Sum("amount"))["total"]
        or 0
    )
    return render(
        request,
        "payments/payments.html",
        {"payments": all_payments, "pending_total": pending_total},
    )


@login_required
def pay_due(request, pk):
    payment = get_object_or_404(
        Payment, pk=pk, patient=_patient(request.user), status="pending"
    )
    form = PaymentForm(request.POST or None, instance=payment)
    if request.method == "POST" and form.is_valid():
        payment = form.save(commit=False)
        payment.status = "paid"
        payment.transaction_id = f"TXN-{uuid.uuid4().hex[:10].upper()}"
        payment.paid_at = timezone.now()
        payment.save()
        messages.success(
            request, "Payment successful. Your invoice is ready to download."
        )
        return redirect("payments")
    return render(request, "payments/pay.html", {"form": form, "payment": payment})


@login_required
def invoice_pdf(request, pk):
    payment = get_object_or_404(Payment, pk=pk, patient=_patient(request.user))
    return _pdf_response(
        f"invoice-{payment.invoice_number}.pdf",
        "Payment Invoice",
        [
            f"Invoice: {payment.invoice_number}",
            f"Patient: {payment.patient}",
            f"Date: {payment.issued_on:%d %B %Y}",
            f"Amount: INR {payment.amount}",
            f"Payment method: {payment.get_method_display()}",
            f"Status: {payment.get_status_display()}",
            f"Transaction: {payment.transaction_id or 'Pending'}",
        ],
    )


@login_required
def community(request):
    patient = _patient(request.user)
    form = FeedbackForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        feedback = form.save(commit=False)
        feedback.patient = patient
        feedback.save()
        messages.success(request, "Thank you. Your feedback helps us improve care.")
        return redirect("community")
    return render(
        request,
        "community/community.html",
        {
            "form": form,
            "reviews": Feedback.objects.select_related("patient__user", "doctor__user")[
                :6
            ],
            "cms_blogs": CMSContent.objects.filter(published=True, content_type="blog")[
                :3
            ],
            "cms_faqs": CMSContent.objects.filter(published=True, content_type="faq")[
                :6
            ],
            "cms_stories": CMSContent.objects.filter(
                published=True, content_type="story"
            )[:3],
            "cms_announcements": CMSContent.objects.filter(
                published=True, content_type="announcement"
            )[:2],
        },
    )


def _is_receptionist(user):
    return is_receptionist(user)


def _require_reception(request):
    if not (_is_receptionist(request.user) or request.user.is_superuser):
        messages.error(request, "The reception workspace requires front-desk access.")
        return False
    return True


def _next_available_slots(limit=8):
    now = timezone.localtime()
    end_date = now.date() + timedelta(days=7)
    doctors = list(
        DoctorProfile.objects.filter(available=True, user__is_active=True)
        .select_related("user")
        .order_by("user__first_name", "user__last_name")
    )
    appointments = Appointment.objects.filter(
        doctor__in=doctors,
        scheduled_at__gte=now,
        scheduled_at__date__lte=end_date,
    ).exclude(status__in=("cancelled", "no_show"))
    occupied = {}
    for item in appointments:
        occupied.setdefault(item.doctor_id, []).append(
            (
                item.scheduled_at,
                item.scheduled_at + timedelta(minutes=item.duration_minutes),
            )
        )

    slots = []
    for day_offset in range(8):
        slot_date = now.date() + timedelta(days=day_offset)
        if slot_date.weekday() == 6:
            continue
        for hour in range(9, 18):
            for minute in (0, 30):
                starts_at = timezone.make_aware(
                    datetime.combine(slot_date, time(hour, minute))
                )
                if starts_at <= now + timedelta(minutes=15):
                    continue
                ends_at = starts_at + timedelta(minutes=45)
                for doctor in doctors:
                    has_conflict = any(
                        existing_start < ends_at and existing_end > starts_at
                        for existing_start, existing_end in occupied.get(doctor.pk, [])
                    )
                    if not has_conflict:
                        slots.append(
                            {
                                "doctor": doctor,
                                "when": starts_at,
                                "value": timezone.localtime(starts_at).strftime(
                                    "%Y-%m-%dT%H:%M"
                                ),
                            }
                        )
                        if len(slots) >= limit:
                            return slots
    return slots


@login_required
def reception_dashboard(request):
    if not _require_reception(request):
        return redirect("dashboard")
    selected_date = timezone.localdate()
    if request.GET.get("date"):
        try:
            selected_date = date.fromisoformat(request.GET["date"])
        except ValueError:
            messages.warning(
                request, "The selected date was invalid, so today’s schedule is shown."
            )

    schedule = (
        Appointment.objects.filter(scheduled_at__date=selected_date)
        .select_related("patient__user", "doctor__user")
        .order_by("scheduled_at")
    )
    query = request.GET.get("q", "").strip()
    patients = PatientProfile.objects.select_related("user")
    if query:
        patients = patients.filter(
            Q(patient_id__icontains=query)
            | Q(user__first_name__icontains=query)
            | Q(user__last_name__icontains=query)
            | Q(user__email__icontains=query)
            | Q(phone__icontains=query)
        )
    else:
        patients = patients.order_by("-created_at")

    pending_payments = (
        Payment.objects.filter(status="pending")
        .select_related("patient__user", "appointment")
        .order_by("due_on", "-issued_on")
    )
    doctor_load = (
        DoctorProfile.objects.filter(available=True)
        .select_related("user")
        .annotate(
            day_count=Count(
                "appointments",
                filter=Q(
                    appointments__scheduled_at__date=selected_date,
                )
                & ~Q(appointments__status__in=("cancelled", "no_show")),
            )
        )
        .order_by("user__first_name")
    )
    return render(
        request,
        "reception/dashboard.html",
        {
            "selected_date": selected_date,
            "schedule": schedule,
            "query": query,
            "patients": patients[:10],
            "total_today": schedule.exclude(
                status__in=("cancelled", "no_show")
            ).count(),
            "waiting_count": schedule.filter(status="checked_in").count(),
            "completed_count": schedule.filter(status="completed").count(),
            "pending_total": pending_payments.aggregate(total=Sum("amount"))["total"]
            or 0,
            "pending_payments": pending_payments[:6],
            "new_enquiries": ContactMessage.objects.filter(status="new").count(),
            "enquiries": ContactMessage.objects.select_related("handled_by")[:6],
            "doctor_load": doctor_load,
            "next_slots": _next_available_slots(),
        },
    )


@login_required
def reception_patient_new(request):
    if not _require_reception(request):
        return redirect("dashboard")
    form = ReceptionPatientForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        patient = form.save(registered_by=request.user)
        invited = send_patient_invitation(patient.user)
        if invited:
            messages.success(
                request,
                f"{patient} was registered and received a secure account-setup email.",
            )
        else:
            messages.warning(
                request,
                f"{patient} was registered, but the setup email could not be sent. You can still book the visit now.",
            )
        return redirect(f"{reverse('reception_appointment_new')}?patient={patient.pk}")
    return render(request, "reception/patient_form.html", {"form": form})


@login_required
def reception_appointment_new(request):
    if not _require_reception(request):
        return redirect("dashboard")
    initial = {
        "patient": request.GET.get("patient"),
        "doctor": request.GET.get("doctor"),
        "scheduled_at": request.GET.get("time")
        or (timezone.localtime() + timedelta(days=1)).replace(
            minute=0, second=0, microsecond=0
        ),
        "duration_minutes": 45,
        "reminder_channel": "Email & WhatsApp",
    }
    form = ReceptionAppointmentForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            appointment = save_appointment_safely(form, status="confirmed")
        except ValidationError as exc:
            add_validation_error_to_form(form, exc)
            appointment = None
        if not appointment:
            return render(
                request,
                "reception/appointment_form.html",
                {
                    "form": form,
                    "next_slots": _next_available_slots(5),
                },
            )
        payment = None
        if form.cleaned_data.get("create_invoice"):
            payment, _ = Payment.objects.get_or_create(
                appointment=appointment,
                defaults={
                    "patient": appointment.patient,
                    "invoice_number": f"PC-{timezone.localdate():%Y%m%d}-{appointment.pk:05d}",
                    "amount": appointment.doctor.consultation_fee,
                    "status": "pending",
                    "issued_on": timezone.localdate(),
                    "due_on": timezone.localdate(),
                },
            )
        Notification.objects.create(
            user=appointment.patient.user,
            title="Appointment confirmed",
            message=f"Reception booked your session with {appointment.doctor} for {timezone.localtime(appointment.scheduled_at):%d %b at %I:%M %p}.",
            notification_type="appointment",
            action_url="/appointments/",
        )
        send_appointment_emails(appointment, "booked")
        suffix = " A pending invoice was also created." if payment else ""
        messages.success(
            request,
            f"Appointment booked and both patient and therapist were notified.{suffix}",
        )
        return redirect("reception_patient_detail", pk=appointment.patient_id)
    return render(
        request,
        "reception/appointment_form.html",
        {
            "form": form,
            "next_slots": _next_available_slots(5),
        },
    )


@login_required
def reception_appointment_edit(request, pk):
    if not _require_reception(request):
        return redirect("dashboard")
    appointment = get_object_or_404(
        Appointment.objects.select_related("patient__user", "doctor__user"), pk=pk
    )
    initial = {}
    if request.method == "GET":
        if request.GET.get("doctor"):
            initial["doctor"] = request.GET["doctor"]
        if request.GET.get("time"):
            initial["scheduled_at"] = request.GET["time"]
    form = ReceptionAppointmentForm(
        request.POST or None, instance=appointment, initial=initial, allow_invoice=False
    )
    if request.method == "POST" and form.is_valid():
        try:
            appointment = save_appointment_safely(form)
        except ValidationError as exc:
            add_validation_error_to_form(form, exc)
            appointment = None
        if appointment:
            Notification.objects.create(
                user=appointment.patient.user,
                title="Appointment rescheduled",
                message=f"Reception moved your appointment with {appointment.doctor} to {timezone.localtime(appointment.scheduled_at):%d %b at %I:%M %p}.",
                notification_type="appointment",
                action_url="/appointments/",
            )
            send_appointment_emails(appointment, "rescheduled")
            messages.success(
                request,
                "Appointment rescheduled and both patient and therapist were notified.",
            )
            return redirect("reception_patient_detail", pk=appointment.patient_id)
    return render(
        request,
        "reception/appointment_form.html",
        {
            "form": form,
            "next_slots": _next_available_slots(5),
            "editing": True,
            "appointment": appointment,
        },
    )


@login_required
def reception_patient_detail(request, pk):
    if not _require_reception(request):
        return redirect("dashboard")
    patient = get_object_or_404(
        PatientProfile.objects.select_related("user", "registered_by"), pk=pk
    )
    return render(
        request,
        "reception/patient_detail.html",
        {
            "patient": patient,
            "appointments": patient.appointments.select_related(
                "doctor__user"
            ).order_by("-scheduled_at")[:12],
            "next_appointment": patient.appointments.filter(
                scheduled_at__gte=timezone.now()
            )
            .exclude(status__in=("cancelled", "completed", "no_show"))
            .select_related("doctor__user")
            .first(),
            "payments": patient.payments.select_related("appointment").order_by(
                "-issued_on"
            )[:10],
            "pending_total": patient.payments.filter(status="pending").aggregate(
                total=Sum("amount")
            )["total"]
            or 0,
        },
    )


@login_required
def reception_patient_invite(request, pk):
    if not _require_reception(request):
        return redirect("dashboard")
    patient = get_object_or_404(PatientProfile.objects.select_related("user"), pk=pk)
    if request.method == "POST":
        if patient.user.has_usable_password() and patient.email_verified_at:
            messages.info(request, "This patient account is already set up.")
        elif send_patient_invitation(patient.user):
            messages.success(
                request,
                f"A fresh account-setup email was sent to {patient.user.email}.",
            )
        else:
            messages.warning(
                request,
                "The invitation was already sent recently or SMTP is unavailable.",
            )
    return redirect("reception_patient_detail", pk=patient.pk)


@login_required
def reception_appointment_status(request, pk):
    if not _require_reception(request):
        return redirect("dashboard")
    appointment = get_object_or_404(
        Appointment.objects.select_related("patient__user", "doctor__user"), pk=pk
    )
    allowed = {"confirmed", "checked_in", "in_progress", "cancelled", "no_show"}
    new_status = request.POST.get("status")
    if request.method == "POST" and new_status in allowed:
        appointment.status = new_status
        fields = ["status", "updated_at"]
        if new_status == "checked_in" and not appointment.checked_in_at:
            appointment.checked_in_at = timezone.now()
            fields.append("checked_in_at")
        appointment.save(update_fields=fields)
        Notification.objects.create(
            user=appointment.patient.user,
            title="Appointment status updated",
            message=f"Your appointment with {appointment.doctor} is now {appointment.get_status_display().lower()}.",
            notification_type="appointment",
            action_url="/appointments/",
        )
        send_appointment_emails(appointment, "status_updated")
        messages.success(
            request,
            f"{appointment.patient} is now marked {appointment.get_status_display().lower()}.",
        )
    return_date = request.POST.get("return_date", "")
    if return_date:
        try:
            date.fromisoformat(return_date)
            return redirect(f"{reverse('reception_dashboard')}?date={return_date}")
        except ValueError:
            pass
    return redirect("reception_dashboard")


@login_required
def reception_payment_collect(request, pk):
    if not _require_reception(request):
        return redirect("dashboard")
    payment = get_object_or_404(
        Payment.objects.select_related("patient__user"), pk=pk, status="pending"
    )
    form = ReceptionPaymentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        payment.method = form.cleaned_data["method"]
        payment.status = "paid"
        payment.transaction_id = f"FRONT-{uuid.uuid4().hex[:10].upper()}"
        payment.paid_at = timezone.now()
        payment.collected_by = request.user
        payment.save(
            update_fields=[
                "method",
                "status",
                "transaction_id",
                "paid_at",
                "collected_by",
            ]
        )
        Notification.objects.create(
            user=payment.patient.user,
            title="Payment received",
            message=f"We received ₹{payment.amount} for invoice {payment.invoice_number}.",
            notification_type="payment",
            action_url="/payments/",
        )
        send_user_notification_email(
            user=payment.patient.user,
            title="Payment received",
            message=f"We received ₹{payment.amount} for invoice {payment.invoice_number}. Your receipt is available in Payments.",
            action_path="payments/",
            event_key=f"payment:{payment.pk}:received",
        )
        messages.success(
            request, f"Payment of ₹{payment.amount} was recorded successfully."
        )
    return redirect("reception_patient_detail", pk=payment.patient_id)


@login_required
def reception_invoice(request, pk):
    if not _require_reception(request):
        return redirect("dashboard")
    payment = get_object_or_404(Payment.objects.select_related("patient__user"), pk=pk)
    return _pdf_response(
        f"invoice-{payment.invoice_number}.pdf",
        "Payment Invoice",
        [
            f"Invoice: {payment.invoice_number}",
            f"Patient: {payment.patient}",
            f"Date: {payment.issued_on:%d %B %Y}",
            f"Amount: INR {payment.amount}",
            f"Payment method: {payment.get_method_display()}",
            f"Status: {payment.get_status_display()}",
            f"Transaction: {payment.transaction_id or 'Pending'}",
        ],
    )


@login_required
def reception_enquiry_status(request, pk):
    if not _require_reception(request):
        return redirect("dashboard")
    item = get_object_or_404(ContactMessage, pk=pk)
    status = request.POST.get("status")
    if request.method == "POST" and status in dict(ContactMessage.STATUS):
        item.status = status
        item.handled_by = request.user
        item.save(update_fields=["status", "handled_by", "updated_at"])
        messages.success(
            request,
            f"Enquiry from {item.name} marked {item.get_status_display().lower()}.",
        )
    return redirect("reception_dashboard")


@login_required
def doctor_dashboard(request):
    doctor = _require_doctor(request)
    if not doctor:
        return redirect("dashboard")
    appointments = doctor.appointments.select_related("patient__user")
    patients = _doctor_patients(doctor)
    unread = ChatMessage.objects.filter(recipient=doctor.user, is_read=False)
    patient_ids = patients.values_list("pk", flat=True)
    payment_qs = Payment.objects.filter(patient_id__in=patient_ids)
    return render(
        request,
        "doctor/dashboard.html",
        {
            "doctor": doctor,
            "today_appointments": appointments.filter(
                scheduled_at__date=timezone.localdate()
            ).exclude(status="cancelled"),
            "upcoming": appointments.filter(scheduled_at__gte=timezone.now()).exclude(
                status="cancelled"
            )[:6],
            "patients": patients,
            "unread_messages": unread[:5],
            "completed": appointments.filter(status="completed").count(),
            "average_rating": doctor.feedback.aggregate(avg=Avg("rating"))["avg"]
            or doctor.rating,
            "billed_total": payment_qs.aggregate(total=Sum("amount"))["total"] or 0,
            "paid_total": payment_qs.filter(status="paid").aggregate(
                total=Sum("amount")
            )["total"]
            or 0,
            "average_progress": TreatmentPlan.objects.filter(
                doctor=doctor, active=True
            ).aggregate(avg=Avg("progress"))["avg"]
            or 0,
        },
    )


@login_required
def admin_dashboard(request):
    if not _require_admin(request, "admin.dashboard"):
        return redirect("dashboard")
    today = timezone.localdate()
    payments_qs = Payment.objects.all()
    return render(
        request,
        "admin_panel/dashboard.html",
        {
            "patient_count": PatientProfile.objects.count(),
            "doctor_count": DoctorProfile.objects.count(),
            "appointment_count": Appointment.objects.count(),
            "today_appointments": Appointment.objects.filter(
                scheduled_at__date=today
            ).select_related("patient__user", "doctor__user"),
            "revenue": payments_qs.filter(status="paid").aggregate(total=Sum("amount"))[
                "total"
            ]
            or 0,
            "pending_dues": payments_qs.filter(status="pending").aggregate(
                total=Sum("amount")
            )["total"]
            or 0,
            "recent_patients": PatientProfile.objects.select_related("user").order_by(
                "-created_at"
            )[:5],
        },
    )


def _require_doctor(request):
    doctor = getattr(request.user, "doctor_profile", None)
    if not doctor:
        messages.error(
            request, "The doctor workspace is available only to authorised doctors."
        )
        return None
    return doctor


def _require_admin(request, capability="admin.dashboard"):
    if not has_capability(request.user, capability):
        messages.error(
            request, "Your staff role does not allow this administration action."
        )
        return False
    return True


def _doctor_patients(doctor):
    return (
        PatientProfile.objects.filter(
            Q(appointments__doctor=doctor)
            | Q(treatment_plans__doctor=doctor)
            | Q(prescriptions__doctor=doctor)
            | Q(exercise_assignments__assigned_by=doctor)
            | Q(user__sent_messages__recipient=doctor.user)
            | Q(user__received_messages__sender=doctor.user)
        )
        .distinct()
        .select_related("user")
        .order_by("user__first_name", "user__last_name")
    )


@login_required
def doctor_calendar(request):
    doctor = _require_doctor(request)
    if not doctor:
        return redirect("dashboard")
    appointments = doctor.appointments.select_related("patient__user").order_by(
        "scheduled_at"
    )
    status = request.GET.get("status", "")
    if status in dict(Appointment.STATUS_CHOICES):
        appointments = appointments.filter(status=status)
    query = request.GET.get("q", "").strip()
    if query:
        appointments = appointments.filter(
            Q(patient__user__first_name__icontains=query)
            | Q(patient__user__last_name__icontains=query)
            | Q(patient__patient_id__icontains=query)
            | Q(concern__icontains=query)
        )
    return render(
        request,
        "doctor/calendar.html",
        {
            "doctor": doctor,
            "appointments": appointments,
            "status_filter": status,
            "query": query,
        },
    )


@login_required
def doctor_patient_detail(request, pk):
    doctor = _require_doctor(request)
    if not doctor:
        return redirect("dashboard")
    patient = get_object_or_404(_doctor_patients(doctor), pk=pk)
    return render(
        request,
        "doctor/patient_detail.html",
        {
            "doctor": doctor,
            "patient": patient,
            "appointments": patient.appointments.filter(doctor=doctor).order_by(
                "-scheduled_at"
            )[:10],
            "plans": patient.treatment_plans.filter(doctor=doctor),
            "assignments": patient.exercise_assignments.filter(
                assigned_by=doctor
            ).select_related("exercise"),
            "prescriptions": patient.prescriptions.filter(doctor=doctor),
            "records": patient.medical_records.all()[:8],
            "progress_entries": patient.progress_entries.all(),
            "payments": patient.payments.all()[:6],
        },
    )


@login_required
def doctor_session(request, pk):
    doctor = _require_doctor(request)
    if not doctor:
        return redirect("dashboard")
    appointment = get_object_or_404(
        Appointment.objects.select_related("patient__user", "doctor__user"),
        pk=pk,
        doctor=doctor,
    )
    form = ClinicalSessionForm(request.POST or None, instance=appointment)
    if request.method == "POST" and form.is_valid():
        appointment = form.save()
        if appointment.notes:
            MedicalRecord.objects.update_or_create(
                patient=appointment.patient,
                title=f"Visit note #{appointment.pk}",
                record_type="visit",
                defaults={
                    "record_date": timezone.localdate(),
                    "doctor_name": str(doctor),
                    "notes": appointment.notes,
                },
            )
        Notification.objects.create(
            user=appointment.patient.user,
            title="Visit notes updated",
            message=f"{doctor} updated the notes for your {appointment.concern.lower()} session.",
            notification_type="followup",
            action_url="/reports/",
        )
        messages.success(request, "Session notes and appointment status were saved.")
        return redirect("doctor_patient_detail", pk=appointment.patient.pk)
    return render(
        request,
        "doctor/session.html",
        {"doctor": doctor, "appointment": appointment, "form": form},
    )


@login_required
def doctor_messages(request):
    doctor = _require_doctor(request)
    if not doctor:
        return redirect("dashboard")
    patients = _doctor_patients(doctor)
    selected_id = request.POST.get("patient") or request.GET.get("patient")
    selected = (
        patients.filter(pk=selected_id).first() if selected_id else patients.first()
    )
    initial = {"patient": selected} if selected else {}
    form = DoctorReplyForm(
        request.POST or None, request.FILES or None, doctor=doctor, initial=initial
    )
    if request.method == "POST" and form.is_valid():
        selected = form.cleaned_data["patient"]
        attachment = form.cleaned_data.get("attachment")
        reply = ChatMessage.objects.create(
            sender=doctor.user,
            recipient=selected.user,
            body=form.cleaned_data["body"],
            attachment=attachment,
            message_type="report" if attachment else "text",
        )
        Notification.objects.create(
            user=selected.user,
            title=f"New message from {doctor}",
            message=form.cleaned_data["body"][:180],
            notification_type="general",
            action_url="/chat/",
        )
        send_user_notification_email(
            user=selected.user,
            title=f"New message from {doctor}",
            message=form.cleaned_data["body"][:300],
            action_path="chat/",
            event_key=f"chat-message:{reply.pk}:recipient",
        )
        messages.success(request, "Your secure reply was sent to the patient.")
        return redirect(f"{request.path}?patient={selected.pk}")
    conversation = ChatMessage.objects.none()
    if selected:
        conversation = ChatMessage.objects.filter(
            Q(sender=doctor.user, recipient=selected.user)
            | Q(sender=selected.user, recipient=doctor.user)
        )
        conversation.filter(sender=selected.user, recipient=doctor.user).update(
            is_read=True
        )
    return render(
        request,
        "doctor/messages.html",
        {
            "doctor": doctor,
            "patients": patients,
            "selected": selected,
            "conversation": conversation,
            "form": form,
        },
    )


@login_required
def doctor_action(request, action):
    doctor = _require_doctor(request)
    if not doctor:
        return redirect("dashboard")
    action_config = {
        "prescription": (
            DoctorPrescriptionForm,
            "Digital prescription",
            "Create a clear prescription and make its PDF available to the patient.",
            "file-plus-2",
        ),
        "exercise": (
            DoctorExerciseForm,
            "Assign an exercise",
            "Add a guided activity to the patient’s home programme.",
            "dumbbell",
        ),
        "treatment": (
            DoctorTreatmentForm,
            "Update treatment plan",
            "Create or update goals, guidance, review dates, and progress.",
            "clipboard-pen-line",
        ),
        "followup": (
            DoctorFollowUpForm,
            "Schedule a follow-up",
            "Book the patient’s next in-clinic review and send a reminder.",
            "calendar-plus",
        ),
        "document": (
            DoctorDocumentForm,
            "Share a document",
            "Upload a report, visit note, certificate, or care document securely.",
            "file-up",
        ),
        "feedback": (
            DoctorFeedbackForm,
            "Send progress feedback",
            "Share personal encouragement or adjustments with the patient.",
            "message-circle-heart",
        ),
    }
    if action not in action_config:
        raise Http404("Unknown clinical action")
    form_class, title, description, icon = action_config[action]
    initial = {}
    patient_id = request.GET.get("patient")
    if patient_id and _doctor_patients(doctor).filter(pk=patient_id).exists():
        initial["patient"] = patient_id
    if action == "followup":
        initial.setdefault("scheduled_at", timezone.localtime() + timedelta(days=7))
        initial.setdefault("concern", "Follow-up review")
    form = form_class(
        request.POST or None, request.FILES or None, doctor=doctor, initial=initial
    )
    if request.method == "POST" and form.is_valid():
        patient = form.cleaned_data["patient"]
        if action == "prescription":
            item = form.save(commit=False)
            item.doctor = doctor
            item.save()
            notice = (
                "New prescription available",
                f"{doctor} added a prescription for {item.diagnosis}.",
                "general",
                "/reports/",
            )
        elif action == "exercise":
            item = form.save(commit=False)
            item.assigned_by = doctor
            item.save()
            notice = (
                "New exercise assigned",
                f"{doctor} added {item.exercise.title} to your programme.",
                "exercise",
                "/exercises/",
            )
        elif action == "treatment":
            item = form.save(commit=False)
            item.doctor = doctor
            item.save()
            notice = (
                "Treatment plan updated",
                f"{doctor} updated your {item.title} plan.",
                "followup",
                "/treatment/",
            )
        elif action == "followup":
            try:
                item = save_appointment_safely(form, doctor=doctor, status="confirmed")
            except ValidationError as exc:
                add_validation_error_to_form(form, exc)
                item = None
            if not item:
                return render(
                    request,
                    "doctor/action_form.html",
                    {
                        "doctor": doctor,
                        "form": form,
                        "action": action,
                        "action_title": title,
                        "action_description": description,
                        "action_icon": icon,
                    },
                )
            notice = (
                "Follow-up scheduled",
                f"Your follow-up with {doctor} is booked for {timezone.localtime(item.scheduled_at):%d %b at %I:%M %p}.",
                "appointment",
                "/appointments/",
            )
        elif action == "document":
            item = form.save(commit=False)
            item.doctor_name = str(doctor)
            item.save()
            notice = (
                "New medical document",
                f"{doctor} shared {item.title} with you.",
                "general",
                "/reports/",
            )
        else:
            body = form.cleaned_data["body"]
            item = ChatMessage.objects.create(
                sender=doctor.user, recipient=patient.user, body=body
            )
            notice = (
                f"Progress feedback from {doctor}",
                body[:180],
                "followup",
                "/chat/",
            )
        Notification.objects.create(
            user=patient.user,
            title=notice[0],
            message=notice[1],
            notification_type=notice[2],
            action_url=notice[3],
        )
        if action == "followup":
            send_appointment_emails(item, "doctor_scheduled")
        else:
            send_user_notification_email(
                user=patient.user,
                title=notice[0],
                message=notice[1],
                action_path=notice[3],
                event_key=f"doctor-action:{action}:{item.pk}:patient",
            )
        messages.success(request, f"{title} saved and the patient was notified.")
        return redirect("doctor_patient_detail", pk=patient.pk)
    return render(
        request,
        "doctor/action_form.html",
        {
            "doctor": doctor,
            "form": form,
            "action": action,
            "action_title": title,
            "action_description": description,
            "action_icon": icon,
        },
    )


ADMIN_SECTIONS = {
    "doctors": (
        "Manage doctors",
        "Profiles, availability, qualifications, and clinic access",
        "stethoscope",
    ),
    "patients": (
        "Manage patients",
        "Search patient accounts and control portal access",
        "users",
    ),
    "appointments": (
        "Manage appointments",
        "Review in-clinic visits and any existing video appointments",
        "calendar-days",
    ),
    "payments": (
        "Payment reports",
        "Track paid invoices, outstanding dues, and transactions",
        "wallet-cards",
    ),
    "employees": (
        "Clinic employees",
        "Manage employee details, employment status, roles, and portal access",
        "badge-check",
    ),
    "staff": (
        "Staff management",
        "Create staff accounts and assign operational roles",
        "users-round",
    ),
    "roles": (
        "Role-based access",
        "Review and change staff permissions by responsibility",
        "key-round",
    ),
    "cms": (
        "Website CMS",
        "Publish health blogs, FAQs, stories, and announcements",
        "panels-top-left",
    ),
    "backup": (
        "Encrypted backup & restore",
        "Protect database records and private files in one verified archive",
        "database-backup",
    ),
}


@login_required
def admin_manage(request, section):
    if section not in ADMIN_SECTIONS:
        raise Http404("Unknown administration section")
    if not _require_admin(request, ADMIN_SECTION_CAPABILITIES[section]):
        return redirect(portal_home_url(request.user))
    form = None
    if section == "doctors":
        form = AdminDoctorForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            data = form.cleaned_data
            user = User.objects.create_user(
                data["username"],
                data["email"],
                data["password"],
                first_name=data["first_name"],
                last_name=data["last_name"],
            )
            DoctorProfile.objects.create(
                user=user,
                specialization=data["specialization"],
                qualifications=data["qualifications"],
                experience_years=data["experience_years"],
                consultation_fee=data["consultation_fee"],
            )
            messages.success(
                request, f"Doctor account for {user.get_full_name()} was created."
            )
            return redirect("admin_manage", section="doctors")
    elif section == "employees":
        form = AdminEmployeeForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            employee = form.save()
            access = (
                "with portal access"
                if employee.portal_access
                else "without portal access"
            )
            messages.success(request, f"Employee {employee} was created {access}.")
            return redirect("admin_manage", section="employees")
    elif section == "staff":
        form = AdminStaffForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            data = form.cleaned_data
            user = User.objects.create_user(
                data["username"],
                data["email"],
                data["password"],
                first_name=data["first_name"],
                last_name=data["last_name"],
                is_staff=True,
            )
            group, _ = Group.objects.get_or_create(name=data["role"])
            user.groups.add(group)
            messages.success(
                request,
                f"Staff account for {user.get_full_name()} was created with {data['role']} access.",
            )
            return redirect("admin_manage", section="staff")
    elif section == "roles":
        form = RoleAssignmentForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            staff = form.cleaned_data["staff"]
            group, _ = Group.objects.get_or_create(name=form.cleaned_data["role"])
            staff.groups.clear()
            staff.groups.add(group)
            staff.is_staff = True
            staff.save(update_fields=["is_staff"])
            messages.success(
                request,
                f"{staff.get_full_name() or staff.username} now has the {group.name} role.",
            )
            return redirect("admin_manage", section="roles")
    elif section == "cms":
        form = CMSContentForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            item = form.save(commit=False)
            item.created_by = request.user
            item.save()
            messages.success(request, f"“{item.title}” was saved to the website CMS.")
            return redirect("admin_manage", section="cms")

    query = request.GET.get("q", "").strip()
    context = {
        "section": section,
        "section_title": ADMIN_SECTIONS[section][0],
        "section_description": ADMIN_SECTIONS[section][1],
        "section_icon": ADMIN_SECTIONS[section][2],
        "form": form,
        "query": query,
    }
    if section == "doctors":
        items = DoctorProfile.objects.select_related("user").order_by(
            "user__first_name"
        )
        if query:
            items = items.filter(
                Q(user__first_name__icontains=query)
                | Q(user__last_name__icontains=query)
                | Q(specialization__icontains=query)
            )
        context["doctors"] = items
    elif section == "patients":
        items = PatientProfile.objects.select_related("user").order_by(
            "user__first_name"
        )
        if query:
            items = items.filter(
                Q(user__first_name__icontains=query)
                | Q(user__last_name__icontains=query)
                | Q(patient_id__icontains=query)
                | Q(phone__icontains=query)
            )
        context["patients"] = items
    elif section == "appointments":
        items = Appointment.objects.select_related(
            "patient__user", "doctor__user"
        ).order_by("-scheduled_at")
        status = request.GET.get("status", "")
        if status in dict(Appointment.STATUS_CHOICES):
            items = items.filter(status=status)
        if query:
            items = items.filter(
                Q(patient__user__first_name__icontains=query)
                | Q(patient__user__last_name__icontains=query)
                | Q(doctor__user__first_name__icontains=query)
                | Q(concern__icontains=query)
            )
        context.update(
            {
                "appointments": items[:100],
                "status_filter": status,
                "status_choices": Appointment.STATUS_CHOICES,
            }
        )
    elif section == "payments":
        items = Payment.objects.select_related("patient__user", "appointment").order_by(
            "-issued_on"
        )
        status = request.GET.get("status", "")
        if status in dict(Payment.STATUS):
            items = items.filter(status=status)
        if query:
            items = items.filter(
                Q(patient__user__first_name__icontains=query)
                | Q(patient__user__last_name__icontains=query)
                | Q(invoice_number__icontains=query)
                | Q(transaction_id__icontains=query)
            )
        context.update(
            {
                "payments": items[:100],
                "status_filter": status,
                "status_choices": Payment.STATUS,
                "paid_total": items.filter(status="paid").aggregate(
                    total=Sum("amount")
                )["total"]
                or 0,
                "due_total": items.filter(status="pending").aggregate(
                    total=Sum("amount")
                )["total"]
                or 0,
            }
        )
    elif section == "employees":
        items = EmployeeProfile.objects.select_related("user").prefetch_related(
            "user__groups"
        )
        department = request.GET.get("department", "")
        status = request.GET.get("status", "")
        if department in dict(EmployeeProfile.DEPARTMENTS):
            items = items.filter(department=department)
        if status == "active":
            items = items.filter(active=True)
        elif status == "inactive":
            items = items.filter(active=False)
        elif status == "access":
            items = items.filter(portal_access=True)
        elif status == "no_access":
            items = items.filter(portal_access=False)
        if query:
            items = items.filter(
                Q(employee_id__icontains=query)
                | Q(user__first_name__icontains=query)
                | Q(user__last_name__icontains=query)
                | Q(user__email__icontains=query)
                | Q(phone__icontains=query)
                | Q(job_title__icontains=query)
            )
        context.update(
            {
                "employees": items,
                "department_filter": department,
                "department_choices": EmployeeProfile.DEPARTMENTS,
                "status_filter": status,
                "employee_total": EmployeeProfile.objects.count(),
                "employee_active": EmployeeProfile.objects.filter(active=True).count(),
                "employee_access": EmployeeProfile.objects.filter(
                    portal_access=True, active=True
                ).count(),
            }
        )
    elif section in ("staff", "roles"):
        context["staff_members"] = (
            User.objects.filter(is_staff=True)
            .prefetch_related("groups")
            .order_by("first_name", "username")
        )
    elif section == "cms":
        context["content_items"] = CMSContent.objects.select_related("created_by")
    return render(request, "admin_panel/manage.html", context)


@login_required
def admin_employee_edit(request, pk):
    if not _require_admin(request, "admin.employees"):
        return redirect("dashboard")
    employee = get_object_or_404(EmployeeProfile.objects.select_related("user"), pk=pk)
    form = AdminEmployeeForm(request.POST or None, instance=employee)
    if request.method == "POST" and form.is_valid():
        employee = form.save()
        messages.success(request, f"Employee record for {employee} was updated.")
        return redirect("admin_manage", section="employees")
    return render(
        request,
        "admin_panel/employee_form.html",
        {
            "employee": employee,
            "form": form,
        },
    )


@login_required
def admin_employee_toggle_active(request, pk):
    if not _require_admin(request, "admin.employees"):
        return redirect("dashboard")
    if request.method == "POST":
        employee = get_object_or_404(
            EmployeeProfile.objects.select_related("user"), pk=pk
        )
        employee.active = not employee.active
        employee.save(update_fields=["active", "updated_at"])
        employee.user.is_active = employee.active and employee.portal_access
        employee.user.save(update_fields=["is_active"])
        state = "active" if employee.active else "deactivated"
        messages.success(request, f"{employee} is now {state}.")
    return redirect("admin_manage", section="employees")


@login_required
def admin_employee_toggle_access(request, pk):
    if not _require_admin(request, "admin.employees"):
        return redirect("dashboard")
    if request.method == "POST":
        employee = get_object_or_404(
            EmployeeProfile.objects.select_related("user"), pk=pk
        )
        if not employee.portal_access and not employee.user.has_usable_password():
            messages.error(
                request, "Set a temporary password before granting portal access."
            )
            return redirect("admin_employee_edit", pk=employee.pk)
        employee.portal_access = not employee.portal_access
        employee.save(update_fields=["portal_access", "updated_at"])
        employee.user.is_staff = employee.portal_access
        employee.user.is_active = employee.active and employee.portal_access
        employee.user.save(update_fields=["is_staff", "is_active"])
        state = "granted" if employee.portal_access else "revoked"
        messages.success(request, f"Portal access for {employee} was {state}.")
    return redirect("admin_manage", section="employees")


@login_required
def admin_toggle_doctor(request, pk):
    if not _require_admin(request, "admin.doctors"):
        return redirect("dashboard")
    if request.method == "POST":
        doctor = get_object_or_404(DoctorProfile, pk=pk)
        doctor.available = not doctor.available
        doctor.save(update_fields=["available"])
        doctor.user.is_active = doctor.available
        doctor.user.save(update_fields=["is_active"])
        messages.success(
            request,
            f"{doctor} is now {'available' if doctor.available else 'inactive'}.",
        )
    return redirect("admin_manage", section="doctors")


@login_required
def admin_toggle_patient(request, pk):
    if not _require_admin(request, "admin.patients"):
        return redirect("dashboard")
    if request.method == "POST":
        patient = get_object_or_404(PatientProfile, pk=pk)
        patient.user.is_active = not patient.user.is_active
        patient.user.save(update_fields=["is_active"])
        messages.success(
            request,
            f"Portal access for {patient} is now {'active' if patient.user.is_active else 'suspended'}.",
        )
    return redirect("admin_manage", section="patients")


@login_required
def admin_update_appointment(request, pk):
    if not _require_admin(request, "admin.appointments"):
        return redirect("dashboard")
    appointment = get_object_or_404(Appointment, pk=pk)
    if request.method == "POST" and request.POST.get("status") in dict(
        Appointment.STATUS_CHOICES
    ):
        appointment.status = request.POST["status"]
        appointment.save(update_fields=["status", "updated_at"])
        Notification.objects.create(
            user=appointment.patient.user,
            title="Appointment status updated",
            message=f"Your appointment with {appointment.doctor} is now {appointment.get_status_display().lower()}.",
            notification_type="appointment",
            action_url="/appointments/",
        )
        send_appointment_emails(appointment, "status_updated")
        messages.success(
            request, "Appointment status updated and the patient was notified."
        )
    return redirect("admin_manage", section="appointments")


@login_required
def admin_toggle_content(request, pk):
    if not _require_admin(request, "admin.cms"):
        return redirect("dashboard")
    if request.method == "POST":
        item = get_object_or_404(CMSContent, pk=pk)
        item.published = not item.published
        item.save(update_fields=["published"])
        messages.success(
            request,
            f"“{item.title}” is now {'published' if item.published else 'a draft'}.",
        )
    return redirect("admin_manage", section="cms")


@login_required
def admin_delete_content(request, pk):
    if not _require_admin(request, "admin.cms"):
        return redirect("dashboard")
    if request.method == "POST":
        item = get_object_or_404(CMSContent, pk=pk)
        title = item.title
        item.delete()
        messages.success(request, f"“{title}” was removed from the CMS.")
    return redirect("admin_manage", section="cms")


@login_required
def admin_export(request, report_type):
    if report_type not in {
        "appointments",
        "payments",
        "patients",
        "doctors",
        "employees",
    }:
        raise Http404("Unknown report")
    if not _require_admin(request, f"admin.export.{report_type}"):
        return redirect(portal_home_url(request.user))
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = (
        f'attachment; filename="physiocare-{report_type}-{timezone.localdate()}.csv"'
    )
    writer = csv.writer(response)
    if report_type == "appointments":
        writer.writerow(
            [
                "Date",
                "Time",
                "Patient ID",
                "Patient",
                "Doctor",
                "Mode",
                "Concern",
                "Status",
            ]
        )
        for item in Appointment.objects.select_related(
            "patient__user", "doctor__user"
        ).order_by("-scheduled_at"):
            local = timezone.localtime(item.scheduled_at)
            writer.writerow(
                [
                    local.date(),
                    local.strftime("%I:%M %p"),
                    item.patient.patient_id,
                    str(item.patient),
                    str(item.doctor),
                    item.get_mode_display(),
                    item.concern,
                    item.get_status_display(),
                ]
            )
    elif report_type == "payments":
        writer.writerow(
            [
                "Invoice",
                "Date",
                "Patient ID",
                "Patient",
                "Amount",
                "Method",
                "Status",
                "Transaction",
            ]
        )
        for item in Payment.objects.select_related("patient__user"):
            writer.writerow(
                [
                    item.invoice_number,
                    item.issued_on,
                    item.patient.patient_id,
                    str(item.patient),
                    item.amount,
                    item.get_method_display(),
                    item.get_status_display(),
                    item.transaction_id,
                ]
            )
    elif report_type == "patients":
        writer.writerow(
            ["Patient ID", "Name", "Email", "Phone", "Joined", "Account status"]
        )
        for item in PatientProfile.objects.select_related("user"):
            writer.writerow(
                [
                    item.patient_id,
                    str(item),
                    item.user.email,
                    item.phone,
                    item.created_at.date(),
                    "Active" if item.user.is_active else "Suspended",
                ]
            )
    elif report_type == "doctors":
        writer.writerow(
            [
                "Doctor",
                "Specialization",
                "Qualifications",
                "Experience",
                "Fee",
                "Availability",
            ]
        )
        for item in DoctorProfile.objects.select_related("user"):
            writer.writerow(
                [
                    str(item),
                    item.specialization,
                    item.qualifications,
                    item.experience_years,
                    item.consultation_fee,
                    "Available" if item.available else "Inactive",
                ]
            )
    elif report_type == "employees":
        writer.writerow(
            [
                "Employee ID",
                "Name",
                "Email",
                "Phone",
                "Job title",
                "Department",
                "Employment type",
                "Shift",
                "Joined",
                "Salary",
                "Employment status",
                "Portal access",
                "Role",
            ]
        )
        for item in EmployeeProfile.objects.select_related("user").prefetch_related(
            "user__groups"
        ):
            role = (
                item.user.groups.first().name
                if item.user.groups.exists()
                else "No role"
            )
            writer.writerow(
                [
                    item.employee_id,
                    str(item),
                    item.user.email,
                    item.phone,
                    item.job_title,
                    item.get_department_display(),
                    item.get_employment_type_display(),
                    item.get_shift_display(),
                    item.joined_on,
                    item.monthly_salary or "",
                    "Active" if item.active else "Inactive",
                    "Enabled" if item.portal_access else "Disabled",
                    role,
                ]
            )
    else:
        raise Http404("Unknown report")
    return response


@login_required
@require_POST
def admin_backup_download(request):
    if not _require_admin(request, "admin.backup"):
        return redirect(portal_home_url(request.user))
    try:
        payload = build_encrypted_backup()
    except ImproperlyConfigured:
        logger.exception(
            "Encrypted backup requested without valid encryption configuration"
        )
        return HttpResponse("Encrypted backups are not configured.", status=503)
    logger.info("Encrypted clinic backup downloaded by user_id=%s", request.user.pk)
    response = HttpResponse(payload, content_type="application/octet-stream")
    response["Content-Disposition"] = (
        f'attachment; filename="physiocare-backup-{timezone.localtime():%Y%m%d-%H%M}.pcbackup"'
    )
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["Pragma"] = "no-cache"
    return response
