from datetime import timedelta
from io import BytesIO
import csv
import json
import uuid

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group, User
from django.core import serializers
from django.db import connection
from django.db.models import Avg, Q, Sum
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import (
    AdminDoctorForm, AdminStaffForm, AppointmentForm, ChatForm, ClinicalSessionForm,
    CMSContentForm, DoctorDocumentForm, DoctorExerciseForm, DoctorFeedbackForm,
    DoctorFollowUpForm, DoctorPrescriptionForm, DoctorReplyForm, DoctorTreatmentForm,
    FeedbackForm, MedicalRecordForm, PaymentForm, ProfileForm, ProgressForm,
    RegisterForm, RoleAssignmentForm,
)
from .models import (
    Appointment, ChatMessage, CMSContent, DoctorProfile, Exercise,
    ExerciseAssignment, Feedback, MedicalRecord, Notification, PatientProfile,
    Payment, Prescription, ProgressEntry, TreatmentPlan,
)


def health_check(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return JsonResponse({"status": "unhealthy", "database": "unavailable"}, status=503)
    return JsonResponse({"status": "ok", "database": "postgresql"})


def home(request):
    return render(request, "home/index.html", {
        "doctor_count": DoctorProfile.objects.count(),
        "review_count": Feedback.objects.count(),
    })


def register_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Welcome to PhysioCare. Your patient profile is ready.")
        return redirect("dashboard")
    return render(request, "accounts/register.html", {"form": form})


def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    if request.method == "POST":
        username = request.POST.get("username", "")
        password = request.POST.get("password", "")
        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            if request.GET.get("next"):
                return redirect(request.GET["next"])
            if user.is_staff:
                return redirect("admin_dashboard")
            if hasattr(user, "doctor_profile"):
                return redirect("doctor_dashboard")
            return redirect("dashboard")
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
    if request.user.is_staff:
        return redirect("admin_dashboard")
    if hasattr(request.user, "doctor_profile"):
        return redirect("doctor_dashboard")
    patient = _patient(request.user)
    now = timezone.now()
    upcoming = patient.appointments.filter(scheduled_at__gte=now).exclude(status="cancelled")[:3]
    recent_appointments = patient.appointments.filter(scheduled_at__lt=now).order_by("-scheduled_at")[:3]
    active_plan = patient.treatment_plans.filter(active=True).first()
    progress_entries = list(patient.progress_entries.all())
    prescriptions = patient.prescriptions.all()[:3]
    assignments = patient.exercise_assignments.select_related("exercise")[:4]
    pain_change = 0
    if len(progress_entries) >= 2:
        pain_change = progress_entries[0].pain_score - progress_entries[-1].pain_score
    return render(request, "dashboard/dashboard.html", {
        "patient": patient, "upcoming": upcoming, "recent_appointments": recent_appointments,
        "active_plan": active_plan, "prescriptions": prescriptions, "assignments": assignments,
        "progress_entries": progress_entries, "pain_change": pain_change,
        "notifications": request.user.portal_notifications.all()[:4],
    })


@login_required
def profile_view(request):
    patient = _patient(request.user)
    form = ProfileForm(request.POST or None, instance=patient)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Your profile and medical history have been updated.")
        return redirect("profile")
    previous = patient.treatment_plans.filter(active=False)
    return render(request, "profile/profile.html", {"patient": patient, "form": form, "previous_treatments": previous})


@login_required
def book_appointment(request):
    patient = _patient(request.user)
    initial = {"scheduled_at": timezone.localtime() + timedelta(days=1, hours=2)}
    form = AppointmentForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        appointment = form.save(commit=False)
        appointment.patient = patient
        appointment.save()
        Notification.objects.create(
            user=request.user, title="Appointment confirmed",
            message=f"Your session with {appointment.doctor} is booked for {timezone.localtime(appointment.scheduled_at):%d %b at %I:%M %p}.",
            notification_type="appointment", action_url="/appointments/",
        )
        messages.success(request, "Appointment booked. Your reminder preferences have been saved.")
        return redirect("appointment_history")
    return render(request, "appointments/book.html", {"form": form, "doctors": DoctorProfile.objects.filter(available=True)})


@login_required
def appointment_history(request):
    patient = _patient(request.user)
    appointments = patient.appointments.select_related("doctor__user").order_by("-scheduled_at")
    return render(request, "appointments/history.html", {"appointments": appointments, "now": timezone.now()})


@login_required
def reschedule_appointment(request, pk):
    appointment = get_object_or_404(Appointment, pk=pk, patient=_patient(request.user))
    form = AppointmentForm(request.POST or None, instance=appointment)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Your appointment has been rescheduled.")
        return redirect("appointment_history")
    return render(request, "appointments/book.html", {"form": form, "rescheduling": True})


@login_required
def cancel_appointment(request, pk):
    appointment = get_object_or_404(Appointment, pk=pk, patient=_patient(request.user))
    if request.method == "POST":
        appointment.status = "cancelled"
        appointment.save(update_fields=["status"])
        messages.success(request, "The appointment has been cancelled.")
    return redirect("appointment_history")


@login_required
def treatment_plan(request):
    patient = _patient(request.user)
    return render(request, "treatment/treatment_plan.html", {
        "plans": patient.treatment_plans.select_related("doctor__user"),
        "assignments": patient.exercise_assignments.select_related("exercise", "assigned_by__user"),
    })


@login_required
def exercise_library(request):
    patient = _patient(request.user)
    return render(request, "exercises/exercise_videos.html", {
        "assignments": patient.exercise_assignments.select_related("exercise", "assigned_by__user"),
        "exercises": Exercise.objects.all(),
    })


@login_required
def complete_exercise(request, pk):
    assignment = get_object_or_404(ExerciseAssignment, pk=pk, patient=_patient(request.user))
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
        messages.success(request, "Your report was uploaded securely.")
        return redirect("reports")
    return render(request, "reports/reports.html", {
        "form": form, "records": patient.medical_records.all(), "prescriptions": patient.prescriptions.all(),
    })


def _pdf_response(filename, title, lines):
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        buffer = BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4
        pdf.setTitle(title)
        pdf.setFillColorRGB(.11, .30, .25)
        pdf.setFont("Helvetica-Bold", 22)
        pdf.drawString(56, height - 65, "PhysioCare")
        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(56, height - 100, title)
        y = height - 138
        pdf.setFillColorRGB(.16, .22, .20)
        for line in lines:
            pdf.setFont("Helvetica", 11)
            for part in str(line).splitlines() or [""]:
                pdf.drawString(56, y, part[:92])
                y -= 18
                if y < 60:
                    pdf.showPage(); y = height - 60
            y -= 4
        pdf.save()
        response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    except ImportError:
        response = HttpResponse("\n".join([title, ""] + [str(x) for x in lines]), content_type="text/plain")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
def prescription_pdf(request, pk):
    item = get_object_or_404(Prescription, pk=pk, patient=_patient(request.user))
    return _pdf_response(f"prescription-{item.pk}.pdf", "Digital Prescription", [
        f"Patient: {item.patient}", f"Issued: {item.issued_on:%d %B %Y}", f"Doctor: {item.doctor}",
        f"Diagnosis: {item.diagnosis}", "Medicines:", item.medicines, "Instructions:", item.instructions,
    ])


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
    return render(request, "progress/progress.html", {"form": form, "entries": entries, "plan": patient.treatment_plans.filter(active=True).first()})


@login_required
def chat(request):
    patient = _patient(request.user)
    doctor = patient.treatment_plans.filter(active=True).select_related("doctor__user").first()
    doctor = doctor.doctor if doctor else DoctorProfile.objects.first()
    form = ChatForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid() and doctor:
        message = form.save(commit=False)
        message.sender = request.user
        message.recipient = doctor.user
        if message.attachment and message.message_type == "text":
            message.message_type = "report"
        message.save()
        messages.success(request, "Your message was sent securely.")
        return redirect("chat")
    conversation = ChatMessage.objects.filter(
        Q(sender=request.user, recipient=doctor.user if doctor else request.user) |
        Q(sender=doctor.user if doctor else request.user, recipient=request.user)
    )
    conversation.filter(recipient=request.user).update(is_read=True)
    return render(request, "chat/chat.html", {"form": form, "doctor": doctor, "conversation": conversation})


@login_required
def video_consultation(request):
    patient = _patient(request.user)
    upcoming = patient.appointments.filter(mode="video", scheduled_at__gte=timezone.now()).exclude(status="cancelled").first()
    return render(request, "consultation/video_call.html", {"appointment": upcoming})


@login_required
def follow_up(request):
    patient = _patient(request.user)
    plan = patient.treatment_plans.filter(active=True).first()
    if request.method == "POST":
        recipient = plan.doctor.user if plan else (DoctorProfile.objects.first().user if DoctorProfile.objects.exists() else request.user)
        ChatMessage.objects.create(sender=request.user, recipient=recipient, body="I would like to request a follow-up appointment.")
        Notification.objects.create(user=recipient, title="Follow-up requested", message=f"{patient} requested a follow-up appointment.", notification_type="followup")
        messages.success(request, "Your follow-up request was sent to the care team.")
    return redirect("chat")


@login_required
def notifications_view(request):
    return render(request, "notifications/notifications.html", {"notifications": request.user.portal_notifications.all()})


@login_required
def mark_notifications_read(request):
    if request.method == "POST":
        request.user.portal_notifications.update(is_read=True)
    return redirect("notifications")


@login_required
def payments(request):
    patient = _patient(request.user)
    all_payments = patient.payments.all()
    pending_total = all_payments.filter(status="pending").aggregate(total=Sum("amount"))["total"] or 0
    return render(request, "payments/payments.html", {"payments": all_payments, "pending_total": pending_total})


@login_required
def pay_due(request, pk):
    payment = get_object_or_404(Payment, pk=pk, patient=_patient(request.user), status="pending")
    form = PaymentForm(request.POST or None, instance=payment)
    if request.method == "POST" and form.is_valid():
        payment = form.save(commit=False)
        payment.status = "paid"
        payment.transaction_id = f"TXN-{uuid.uuid4().hex[:10].upper()}"
        payment.save()
        messages.success(request, "Payment successful. Your invoice is ready to download.")
        return redirect("payments")
    return render(request, "payments/pay.html", {"form": form, "payment": payment})


@login_required
def invoice_pdf(request, pk):
    payment = get_object_or_404(Payment, pk=pk, patient=_patient(request.user))
    return _pdf_response(f"invoice-{payment.invoice_number}.pdf", "Payment Invoice", [
        f"Invoice: {payment.invoice_number}", f"Patient: {payment.patient}", f"Date: {payment.issued_on:%d %B %Y}",
        f"Amount: INR {payment.amount}", f"Payment method: {payment.get_method_display()}",
        f"Status: {payment.get_status_display()}", f"Transaction: {payment.transaction_id or 'Pending'}",
    ])


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
    return render(request, "community/community.html", {
        "form": form, "reviews": Feedback.objects.select_related("patient__user", "doctor__user")[:6],
        "cms_blogs": CMSContent.objects.filter(published=True, content_type="blog")[:3],
        "cms_faqs": CMSContent.objects.filter(published=True, content_type="faq")[:6],
        "cms_stories": CMSContent.objects.filter(published=True, content_type="story")[:3],
        "cms_announcements": CMSContent.objects.filter(published=True, content_type="announcement")[:2],
    })


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
    return render(request, "doctor/dashboard.html", {
        "doctor": doctor, "today_appointments": appointments.filter(scheduled_at__date=timezone.localdate()).exclude(status="cancelled"),
        "upcoming": appointments.filter(scheduled_at__gte=timezone.now()).exclude(status="cancelled")[:6],
        "patients": patients, "unread_messages": unread[:5],
        "completed": appointments.filter(status="completed").count(),
        "average_rating": doctor.feedback.aggregate(avg=Avg("rating"))["avg"] or doctor.rating,
        "billed_total": payment_qs.aggregate(total=Sum("amount"))["total"] or 0,
        "paid_total": payment_qs.filter(status="paid").aggregate(total=Sum("amount"))["total"] or 0,
        "average_progress": TreatmentPlan.objects.filter(doctor=doctor, active=True).aggregate(avg=Avg("progress"))["avg"] or 0,
    })


@login_required
def admin_dashboard(request):
    if not _require_admin(request):
        return redirect("dashboard")
    today = timezone.localdate()
    payments_qs = Payment.objects.all()
    return render(request, "admin_panel/dashboard.html", {
        "patient_count": PatientProfile.objects.count(), "doctor_count": DoctorProfile.objects.count(),
        "appointment_count": Appointment.objects.count(),
        "today_appointments": Appointment.objects.filter(scheduled_at__date=today).select_related("patient__user", "doctor__user"),
        "revenue": payments_qs.filter(status="paid").aggregate(total=Sum("amount"))["total"] or 0,
        "pending_dues": payments_qs.filter(status="pending").aggregate(total=Sum("amount"))["total"] or 0,
        "recent_patients": PatientProfile.objects.select_related("user").order_by("-created_at")[:5],
    })


def _require_doctor(request):
    doctor = getattr(request.user, "doctor_profile", None)
    if not doctor:
        messages.error(request, "The doctor workspace is available only to authorised doctors.")
        return None
    return doctor


def _require_admin(request):
    if not request.user.is_staff:
        messages.error(request, "The administration panel requires clinic administrator access.")
        return False
    return True


def _doctor_patients(doctor):
    return PatientProfile.objects.filter(
        Q(appointments__doctor=doctor) |
        Q(treatment_plans__doctor=doctor) |
        Q(prescriptions__doctor=doctor) |
        Q(exercise_assignments__assigned_by=doctor)
    ).distinct().select_related("user").order_by("user__first_name", "user__last_name")


@login_required
def doctor_calendar(request):
    doctor = _require_doctor(request)
    if not doctor:
        return redirect("dashboard")
    appointments = doctor.appointments.select_related("patient__user").order_by("scheduled_at")
    status = request.GET.get("status", "")
    if status in dict(Appointment.STATUS_CHOICES):
        appointments = appointments.filter(status=status)
    query = request.GET.get("q", "").strip()
    if query:
        appointments = appointments.filter(
            Q(patient__user__first_name__icontains=query) |
            Q(patient__user__last_name__icontains=query) |
            Q(patient__patient_id__icontains=query) |
            Q(concern__icontains=query)
        )
    return render(request, "doctor/calendar.html", {
        "doctor": doctor, "appointments": appointments, "status_filter": status, "query": query,
    })


@login_required
def doctor_patient_detail(request, pk):
    doctor = _require_doctor(request)
    if not doctor:
        return redirect("dashboard")
    patient = get_object_or_404(_doctor_patients(doctor), pk=pk)
    return render(request, "doctor/patient_detail.html", {
        "doctor": doctor, "patient": patient,
        "appointments": patient.appointments.filter(doctor=doctor).order_by("-scheduled_at")[:10],
        "plans": patient.treatment_plans.filter(doctor=doctor),
        "assignments": patient.exercise_assignments.filter(assigned_by=doctor).select_related("exercise"),
        "prescriptions": patient.prescriptions.filter(doctor=doctor),
        "records": patient.medical_records.all()[:8],
        "progress_entries": patient.progress_entries.all(),
        "payments": patient.payments.all()[:6],
    })


@login_required
def doctor_session(request, pk):
    doctor = _require_doctor(request)
    if not doctor:
        return redirect("dashboard")
    appointment = get_object_or_404(Appointment.objects.select_related("patient__user", "doctor__user"), pk=pk, doctor=doctor)
    form = ClinicalSessionForm(request.POST or None, instance=appointment)
    if request.method == "POST" and form.is_valid():
        appointment = form.save()
        if appointment.notes:
            MedicalRecord.objects.update_or_create(
                patient=appointment.patient, title=f"Visit note #{appointment.pk}", record_type="visit",
                defaults={"record_date": timezone.localdate(), "doctor_name": str(doctor), "notes": appointment.notes},
            )
        Notification.objects.create(
            user=appointment.patient.user, title="Visit notes updated",
            message=f"{doctor} updated the notes for your {appointment.concern.lower()} session.",
            notification_type="followup", action_url="/reports/",
        )
        messages.success(request, "Session notes and appointment status were saved.")
        return redirect("doctor_patient_detail", pk=appointment.patient.pk)
    return render(request, "doctor/session.html", {"doctor": doctor, "appointment": appointment, "form": form})


@login_required
def doctor_messages(request):
    doctor = _require_doctor(request)
    if not doctor:
        return redirect("dashboard")
    patients = _doctor_patients(doctor)
    selected_id = request.POST.get("patient") or request.GET.get("patient")
    selected = patients.filter(pk=selected_id).first() if selected_id else patients.first()
    initial = {"patient": selected} if selected else {}
    form = DoctorReplyForm(request.POST or None, request.FILES or None, doctor=doctor, initial=initial)
    if request.method == "POST" and form.is_valid():
        selected = form.cleaned_data["patient"]
        attachment = form.cleaned_data.get("attachment")
        ChatMessage.objects.create(
            sender=doctor.user, recipient=selected.user, body=form.cleaned_data["body"],
            attachment=attachment, message_type="report" if attachment else "text",
        )
        Notification.objects.create(
            user=selected.user, title=f"New message from {doctor}",
            message=form.cleaned_data["body"][:180], notification_type="general", action_url="/chat/",
        )
        messages.success(request, "Your secure reply was sent to the patient.")
        return redirect(f"{request.path}?patient={selected.pk}")
    conversation = ChatMessage.objects.none()
    if selected:
        conversation = ChatMessage.objects.filter(
            Q(sender=doctor.user, recipient=selected.user) | Q(sender=selected.user, recipient=doctor.user)
        )
        conversation.filter(sender=selected.user, recipient=doctor.user).update(is_read=True)
    return render(request, "doctor/messages.html", {
        "doctor": doctor, "patients": patients, "selected": selected,
        "conversation": conversation, "form": form,
    })


@login_required
def doctor_action(request, action):
    doctor = _require_doctor(request)
    if not doctor:
        return redirect("dashboard")
    action_config = {
        "prescription": (DoctorPrescriptionForm, "Digital prescription", "Create a clear prescription and make its PDF available to the patient.", "file-plus-2"),
        "exercise": (DoctorExerciseForm, "Assign an exercise", "Add a guided activity to the patient’s home programme.", "dumbbell"),
        "treatment": (DoctorTreatmentForm, "Update treatment plan", "Create or update goals, guidance, review dates, and progress.", "clipboard-pen-line"),
        "followup": (DoctorFollowUpForm, "Schedule a follow-up", "Book the patient’s next clinic or video review and send a reminder.", "calendar-plus"),
        "document": (DoctorDocumentForm, "Share a document", "Upload a report, visit note, certificate, or care document securely.", "file-up"),
        "feedback": (DoctorFeedbackForm, "Send progress feedback", "Share personal encouragement or adjustments with the patient.", "message-circle-heart"),
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
    form = form_class(request.POST or None, request.FILES or None, doctor=doctor, initial=initial)
    if request.method == "POST" and form.is_valid():
        patient = form.cleaned_data["patient"]
        if action == "prescription":
            item = form.save(commit=False); item.doctor = doctor; item.save()
            notice = ("New prescription available", f"{doctor} added a prescription for {item.diagnosis}.", "general", "/reports/")
        elif action == "exercise":
            item = form.save(commit=False); item.assigned_by = doctor; item.save()
            notice = ("New exercise assigned", f"{doctor} added {item.exercise.title} to your programme.", "exercise", "/exercises/")
        elif action == "treatment":
            item = form.save(commit=False); item.doctor = doctor; item.save()
            notice = ("Treatment plan updated", f"{doctor} updated your {item.title} plan.", "followup", "/treatment/")
        elif action == "followup":
            item = form.save(commit=False); item.doctor = doctor; item.status = "confirmed"; item.save()
            notice = ("Follow-up scheduled", f"Your follow-up with {doctor} is booked for {timezone.localtime(item.scheduled_at):%d %b at %I:%M %p}.", "appointment", "/appointments/")
        elif action == "document":
            item = form.save(commit=False); item.doctor_name = str(doctor); item.save()
            notice = ("New medical document", f"{doctor} shared {item.title} with you.", "general", "/reports/")
        else:
            body = form.cleaned_data["body"]
            ChatMessage.objects.create(sender=doctor.user, recipient=patient.user, body=body)
            notice = (f"Progress feedback from {doctor}", body[:180], "followup", "/chat/")
        Notification.objects.create(user=patient.user, title=notice[0], message=notice[1], notification_type=notice[2], action_url=notice[3])
        messages.success(request, f"{title} saved and the patient was notified.")
        return redirect("doctor_patient_detail", pk=patient.pk)
    return render(request, "doctor/action_form.html", {
        "doctor": doctor, "form": form, "action": action, "action_title": title,
        "action_description": description, "action_icon": icon,
    })


ADMIN_SECTIONS = {
    "doctors": ("Manage doctors", "Profiles, availability, qualifications, and clinic access", "stethoscope"),
    "patients": ("Manage patients", "Search patient accounts and control portal access", "users"),
    "appointments": ("Manage appointments", "Review and update every clinic and video appointment", "calendar-days"),
    "payments": ("Payment reports", "Track paid invoices, outstanding dues, and transactions", "wallet-cards"),
    "staff": ("Staff management", "Create staff accounts and assign operational roles", "users-round"),
    "roles": ("Role-based access", "Review and change staff permissions by responsibility", "key-round"),
    "cms": ("Website CMS", "Publish health blogs, FAQs, stories, and announcements", "panels-top-left"),
    "backup": ("Backup & restore", "Download a complete, timestamped clinic data backup", "database-backup"),
}


@login_required
def admin_manage(request, section):
    if not _require_admin(request):
        return redirect("dashboard")
    if section not in ADMIN_SECTIONS:
        raise Http404("Unknown administration section")
    form = None
    if section == "doctors":
        form = AdminDoctorForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            data = form.cleaned_data
            user = User.objects.create_user(data["username"], data["email"], data["password"], first_name=data["first_name"], last_name=data["last_name"])
            DoctorProfile.objects.create(
                user=user, specialization=data["specialization"], qualifications=data["qualifications"],
                experience_years=data["experience_years"], consultation_fee=data["consultation_fee"],
            )
            messages.success(request, f"Doctor account for {user.get_full_name()} was created.")
            return redirect("admin_manage", section="doctors")
    elif section == "staff":
        form = AdminStaffForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            data = form.cleaned_data
            user = User.objects.create_user(data["username"], data["email"], data["password"], first_name=data["first_name"], last_name=data["last_name"], is_staff=True)
            group, _ = Group.objects.get_or_create(name=data["role"]); user.groups.add(group)
            messages.success(request, f"Staff account for {user.get_full_name()} was created with {data['role']} access.")
            return redirect("admin_manage", section="staff")
    elif section == "roles":
        form = RoleAssignmentForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            staff = form.cleaned_data["staff"]
            group, _ = Group.objects.get_or_create(name=form.cleaned_data["role"])
            staff.groups.clear(); staff.groups.add(group); staff.is_staff = True; staff.save(update_fields=["is_staff"])
            messages.success(request, f"{staff.get_full_name() or staff.username} now has the {group.name} role.")
            return redirect("admin_manage", section="roles")
    elif section == "cms":
        form = CMSContentForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            item = form.save(commit=False); item.created_by = request.user; item.save()
            messages.success(request, f"“{item.title}” was saved to the website CMS.")
            return redirect("admin_manage", section="cms")

    query = request.GET.get("q", "").strip()
    context = {"section": section, "section_title": ADMIN_SECTIONS[section][0], "section_description": ADMIN_SECTIONS[section][1], "section_icon": ADMIN_SECTIONS[section][2], "form": form, "query": query}
    if section == "doctors":
        items = DoctorProfile.objects.select_related("user").order_by("user__first_name")
        if query: items = items.filter(Q(user__first_name__icontains=query) | Q(user__last_name__icontains=query) | Q(specialization__icontains=query))
        context["doctors"] = items
    elif section == "patients":
        items = PatientProfile.objects.select_related("user").order_by("user__first_name")
        if query: items = items.filter(Q(user__first_name__icontains=query) | Q(user__last_name__icontains=query) | Q(patient_id__icontains=query) | Q(phone__icontains=query))
        context["patients"] = items
    elif section == "appointments":
        items = Appointment.objects.select_related("patient__user", "doctor__user").order_by("-scheduled_at")
        status = request.GET.get("status", "")
        if status in dict(Appointment.STATUS_CHOICES): items = items.filter(status=status)
        if query: items = items.filter(Q(patient__user__first_name__icontains=query) | Q(patient__user__last_name__icontains=query) | Q(doctor__user__first_name__icontains=query) | Q(concern__icontains=query))
        context.update({"appointments": items[:100], "status_filter": status, "status_choices": Appointment.STATUS_CHOICES})
    elif section == "payments":
        items = Payment.objects.select_related("patient__user", "appointment").order_by("-issued_on")
        status = request.GET.get("status", "")
        if status in dict(Payment.STATUS): items = items.filter(status=status)
        if query: items = items.filter(Q(patient__user__first_name__icontains=query) | Q(patient__user__last_name__icontains=query) | Q(invoice_number__icontains=query) | Q(transaction_id__icontains=query))
        context.update({"payments": items[:100], "status_filter": status, "status_choices": Payment.STATUS, "paid_total": items.filter(status="paid").aggregate(total=Sum("amount"))["total"] or 0, "due_total": items.filter(status="pending").aggregate(total=Sum("amount"))["total"] or 0})
    elif section in ("staff", "roles"):
        context["staff_members"] = User.objects.filter(is_staff=True).prefetch_related("groups").order_by("first_name", "username")
    elif section == "cms":
        context["content_items"] = CMSContent.objects.select_related("created_by")
    return render(request, "admin_panel/manage.html", context)


@login_required
def admin_toggle_doctor(request, pk):
    if not _require_admin(request): return redirect("dashboard")
    if request.method == "POST":
        doctor = get_object_or_404(DoctorProfile, pk=pk)
        doctor.available = not doctor.available; doctor.save(update_fields=["available"])
        doctor.user.is_active = doctor.available; doctor.user.save(update_fields=["is_active"])
        messages.success(request, f"{doctor} is now {'available' if doctor.available else 'inactive'}.")
    return redirect("admin_manage", section="doctors")


@login_required
def admin_toggle_patient(request, pk):
    if not _require_admin(request): return redirect("dashboard")
    if request.method == "POST":
        patient = get_object_or_404(PatientProfile, pk=pk)
        patient.user.is_active = not patient.user.is_active; patient.user.save(update_fields=["is_active"])
        messages.success(request, f"Portal access for {patient} is now {'active' if patient.user.is_active else 'suspended'}.")
    return redirect("admin_manage", section="patients")


@login_required
def admin_update_appointment(request, pk):
    if not _require_admin(request): return redirect("dashboard")
    appointment = get_object_or_404(Appointment, pk=pk)
    if request.method == "POST" and request.POST.get("status") in dict(Appointment.STATUS_CHOICES):
        appointment.status = request.POST["status"]; appointment.save(update_fields=["status"])
        Notification.objects.create(user=appointment.patient.user, title="Appointment status updated", message=f"Your appointment with {appointment.doctor} is now {appointment.get_status_display().lower()}.", notification_type="appointment", action_url="/appointments/")
        messages.success(request, "Appointment status updated and the patient was notified.")
    return redirect("admin_manage", section="appointments")


@login_required
def admin_toggle_content(request, pk):
    if not _require_admin(request): return redirect("dashboard")
    if request.method == "POST":
        item = get_object_or_404(CMSContent, pk=pk); item.published = not item.published; item.save(update_fields=["published"])
        messages.success(request, f"“{item.title}” is now {'published' if item.published else 'a draft'}.")
    return redirect("admin_manage", section="cms")


@login_required
def admin_delete_content(request, pk):
    if not _require_admin(request): return redirect("dashboard")
    if request.method == "POST":
        item = get_object_or_404(CMSContent, pk=pk); title = item.title; item.delete()
        messages.success(request, f"“{title}” was removed from the CMS.")
    return redirect("admin_manage", section="cms")


@login_required
def admin_export(request, report_type):
    if not _require_admin(request): return redirect("dashboard")
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="physiocare-{report_type}-{timezone.localdate()}.csv"'
    writer = csv.writer(response)
    if report_type == "appointments":
        writer.writerow(["Date", "Time", "Patient ID", "Patient", "Doctor", "Mode", "Concern", "Status"])
        for item in Appointment.objects.select_related("patient__user", "doctor__user").order_by("-scheduled_at"):
            local = timezone.localtime(item.scheduled_at); writer.writerow([local.date(), local.strftime("%I:%M %p"), item.patient.patient_id, str(item.patient), str(item.doctor), item.get_mode_display(), item.concern, item.get_status_display()])
    elif report_type == "payments":
        writer.writerow(["Invoice", "Date", "Patient ID", "Patient", "Amount", "Method", "Status", "Transaction"])
        for item in Payment.objects.select_related("patient__user"):
            writer.writerow([item.invoice_number, item.issued_on, item.patient.patient_id, str(item.patient), item.amount, item.get_method_display(), item.get_status_display(), item.transaction_id])
    elif report_type == "patients":
        writer.writerow(["Patient ID", "Name", "Email", "Phone", "Joined", "Account status"])
        for item in PatientProfile.objects.select_related("user"):
            writer.writerow([item.patient_id, str(item), item.user.email, item.phone, item.created_at.date(), "Active" if item.user.is_active else "Suspended"])
    elif report_type == "doctors":
        writer.writerow(["Doctor", "Specialization", "Qualifications", "Experience", "Fee", "Availability"])
        for item in DoctorProfile.objects.select_related("user"):
            writer.writerow([str(item), item.specialization, item.qualifications, item.experience_years, item.consultation_fee, "Available" if item.available else "Inactive"])
    else:
        raise Http404("Unknown report")
    return response


@login_required
def admin_backup_download(request):
    if not _require_admin(request): return redirect("dashboard")
    model_sets = {
        "users": User.objects.all(), "groups": Group.objects.all(), "patients": PatientProfile.objects.all(),
        "doctors": DoctorProfile.objects.all(), "appointments": Appointment.objects.all(),
        "treatment_plans": TreatmentPlan.objects.all(), "exercises": Exercise.objects.all(),
        "exercise_assignments": ExerciseAssignment.objects.all(), "progress": ProgressEntry.objects.all(),
        "prescriptions": Prescription.objects.all(), "medical_records": MedicalRecord.objects.all(),
        "notifications": Notification.objects.all(), "messages": ChatMessage.objects.all(),
        "payments": Payment.objects.all(), "feedback": Feedback.objects.all(), "cms": CMSContent.objects.all(),
    }
    payload = {"generated_at": timezone.now().isoformat(), "format": "PhysioCare backup v1"}
    for name, queryset in model_sets.items():
        payload[name] = json.loads(serializers.serialize("json", queryset))
    response = HttpResponse(json.dumps(payload, indent=2), content_type="application/json")
    response["Content-Disposition"] = f'attachment; filename="physiocare-backup-{timezone.localtime():%Y%m%d-%H%M}.json"'
    return response
