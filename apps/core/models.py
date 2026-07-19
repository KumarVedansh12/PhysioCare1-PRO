from datetime import timedelta

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from .validators import validate_chat_attachment, validate_medical_document


class PatientProfile(models.Model):
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="patient_profile"
    )
    patient_id = models.CharField(max_length=20, unique=True, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=30, blank=True)
    blood_group = models.CharField(max_length=8, blank=True)
    address = models.TextField(blank=True)
    emergency_contact = models.CharField(max_length=100, blank=True)
    conditions = models.TextField(blank=True)
    allergies = models.TextField(blank=True)
    surgeries = models.TextField(blank=True)
    profile_picture = models.ImageField(upload_to="profile_pictures/", blank=True)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    registered_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="registered_patients",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.patient_id:
            self.patient_id = f"PC-{self.pk:05d}"
            super().save(update_fields=["patient_id"])

    def __str__(self):
        return self.user.get_full_name() or self.user.username


class DoctorProfile(models.Model):
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="doctor_profile"
    )
    specialization = models.CharField(max_length=120)
    qualifications = models.CharField(max_length=180, blank=True)
    experience_years = models.PositiveIntegerField(default=0)
    bio = models.TextField(blank=True)
    consultation_fee = models.DecimalField(max_digits=8, decimal_places=2, default=800)
    rating = models.DecimalField(max_digits=2, decimal_places=1, default=4.8)
    available = models.BooleanField(default=True)

    def __str__(self):
        return f"Dr. {self.user.get_full_name() or self.user.username}"


class EmployeeProfile(models.Model):
    DEPARTMENTS = [
        ("administration", "Administration"),
        ("front_desk", "Front desk"),
        ("billing", "Billing and accounts"),
        ("clinical_support", "Clinical support"),
        ("operations", "Clinic operations"),
        ("housekeeping", "Housekeeping"),
        ("other", "Other"),
    ]
    EMPLOYMENT_TYPES = [
        ("full_time", "Full-time"),
        ("part_time", "Part-time"),
        ("contract", "Contract"),
        ("intern", "Intern / trainee"),
    ]
    SHIFTS = [
        ("morning", "Morning"),
        ("evening", "Evening"),
        ("full_day", "Full day"),
        ("flexible", "Flexible / rotating"),
    ]

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="employee_profile"
    )
    employee_id = models.CharField(max_length=20, unique=True, blank=True)
    phone = models.CharField(max_length=20)
    job_title = models.CharField(max_length=120)
    department = models.CharField(
        max_length=30, choices=DEPARTMENTS, default="operations"
    )
    employment_type = models.CharField(
        max_length=30, choices=EMPLOYMENT_TYPES, default="full_time"
    )
    shift = models.CharField(max_length=30, choices=SHIFTS, default="full_day")
    joined_on = models.DateField(default=timezone.localdate)
    monthly_salary = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    emergency_contact = models.CharField(max_length=120, blank=True)
    address = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    portal_access = models.BooleanField(default=False)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["user__first_name", "user__last_name", "employee_id"]
        verbose_name = "Clinic employee"
        verbose_name_plural = "Clinic employees"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.employee_id:
            self.employee_id = f"EMP-{self.pk:05d}"
            super().save(update_fields=["employee_id"])

    def __str__(self):
        return self.user.get_full_name() or self.user.username


class Appointment(models.Model):
    STATUS_CHOICES = [
        ("confirmed", "Confirmed"),
        ("pending", "Pending"),
        ("checked_in", "Checked in"),
        ("in_progress", "In progress"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
        ("no_show", "No-show"),
    ]
    MODE_CHOICES = [
        ("clinic", "In-clinic"),
        ("video", "Video consultation (coming soon)"),
    ]
    patient = models.ForeignKey(
        PatientProfile, on_delete=models.CASCADE, related_name="appointments"
    )
    doctor = models.ForeignKey(
        DoctorProfile, on_delete=models.PROTECT, related_name="appointments"
    )
    scheduled_at = models.DateTimeField()
    duration_minutes = models.PositiveIntegerField(default=45)
    concern = models.CharField(max_length=240)
    notes = models.TextField(blank=True)
    mode = models.CharField(max_length=20, choices=MODE_CHOICES, default="clinic")
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="confirmed"
    )
    reminder_channel = models.CharField(max_length=30, default="Email & WhatsApp")
    checked_in_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["scheduled_at"]

    def clean(self):
        super().clean()
        if not self.scheduled_at or not self.doctor_id or not self.duration_minutes:
            return

        schedule_changed = True
        if self.pk:
            previous = (
                Appointment.objects.filter(pk=self.pk)
                .values("doctor_id", "scheduled_at", "duration_minutes")
                .first()
            )
            if previous:
                schedule_changed = any(
                    (
                        previous["doctor_id"] != self.doctor_id,
                        previous["scheduled_at"] != self.scheduled_at,
                        previous["duration_minutes"] != self.duration_minutes,
                    )
                )
        if not schedule_changed:
            return

        if self.scheduled_at <= timezone.now():
            raise ValidationError({"scheduled_at": "Choose a future appointment time."})

        new_end = self.scheduled_at + timedelta(minutes=self.duration_minutes)
        candidates = Appointment.objects.filter(
            doctor_id=self.doctor_id,
            scheduled_at__lt=new_end,
        ).exclude(status__in=("cancelled", "no_show"))
        if self.pk:
            candidates = candidates.exclude(pk=self.pk)
        conflict = any(
            item.scheduled_at + timedelta(minutes=item.duration_minutes)
            > self.scheduled_at
            for item in candidates.only("scheduled_at", "duration_minutes")
        )
        if conflict:
            raise ValidationError(
                {
                    "scheduled_at": "This therapist already has an overlapping appointment."
                }
            )

    def __str__(self):
        return f"{self.patient} with {self.doctor}"


class TreatmentPlan(models.Model):
    patient = models.ForeignKey(
        PatientProfile, on_delete=models.CASCADE, related_name="treatment_plans"
    )
    doctor = models.ForeignKey(
        DoctorProfile, on_delete=models.PROTECT, related_name="treatment_plans"
    )
    title = models.CharField(max_length=180)
    diagnosis = models.CharField(max_length=220, blank=True)
    goal = models.TextField()
    instructions = models.TextField(blank=True)
    progress = models.PositiveIntegerField(
        default=0, validators=[MaxValueValidator(100)]
    )
    started_on = models.DateField(default=timezone.localdate)
    next_review = models.DateField(null=True, blank=True)
    active = models.BooleanField(default=True)


class Exercise(models.Model):
    DIFFICULTY = [("easy", "Easy"), ("moderate", "Moderate"), ("advanced", "Advanced")]
    title = models.CharField(max_length=180)
    category = models.CharField(max_length=100)
    description = models.TextField()
    video_url = models.URLField(blank=True)
    duration_minutes = models.PositiveIntegerField(default=10)
    difficulty = models.CharField(max_length=20, choices=DIFFICULTY, default="easy")


class ExerciseAssignment(models.Model):
    patient = models.ForeignKey(
        PatientProfile, on_delete=models.CASCADE, related_name="exercise_assignments"
    )
    exercise = models.ForeignKey(Exercise, on_delete=models.CASCADE)
    assigned_by = models.ForeignKey(DoctorProfile, on_delete=models.PROTECT)
    repetitions = models.CharField(max_length=80, default="10 reps × 2 sets")
    frequency = models.CharField(max_length=80, default="Once daily")
    completed_today = models.BooleanField(default=False)
    assigned_on = models.DateField(default=timezone.localdate)


class ProgressEntry(models.Model):
    patient = models.ForeignKey(
        PatientProfile, on_delete=models.CASCADE, related_name="progress_entries"
    )
    recorded_on = models.DateField(default=timezone.localdate)
    pain_score = models.PositiveIntegerField(validators=[MaxValueValidator(10)])
    mobility_score = models.PositiveIntegerField(validators=[MaxValueValidator(100)])
    exercise_adherence = models.PositiveIntegerField(
        default=0, validators=[MaxValueValidator(100)]
    )
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["recorded_on"]


class Prescription(models.Model):
    patient = models.ForeignKey(
        PatientProfile, on_delete=models.CASCADE, related_name="prescriptions"
    )
    doctor = models.ForeignKey(DoctorProfile, on_delete=models.PROTECT)
    diagnosis = models.CharField(max_length=220)
    medicines = models.TextField(help_text="One medicine per line")
    instructions = models.TextField(blank=True)
    issued_on = models.DateField(default=timezone.localdate)

    class Meta:
        ordering = ["-issued_on"]


class MedicalRecord(models.Model):
    RECORD_TYPES = [
        ("lab", "Lab report"),
        ("scan", "X-ray / MRI"),
        ("visit", "Visit note"),
        ("certificate", "Medical certificate"),
        ("prescription", "Prescription"),
        ("other", "Other document"),
    ]
    patient = models.ForeignKey(
        PatientProfile, on_delete=models.CASCADE, related_name="medical_records"
    )
    title = models.CharField(max_length=180)
    record_type = models.CharField(max_length=30, choices=RECORD_TYPES)
    record_date = models.DateField(default=timezone.localdate)
    doctor_name = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)
    file = models.FileField(
        upload_to="reports/", blank=True, validators=[validate_medical_document]
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-record_date"]


class Notification(models.Model):
    TYPES = [
        ("appointment", "Appointment"),
        ("medicine", "Medicine"),
        ("exercise", "Exercise"),
        ("payment", "Payment"),
        ("followup", "Follow-up"),
        ("general", "General"),
    ]
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="portal_notifications"
    )
    title = models.CharField(max_length=180)
    message = models.TextField()
    notification_type = models.CharField(
        max_length=30, choices=TYPES, default="general"
    )
    action_url = models.CharField(max_length=240, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class ChatMessage(models.Model):
    MESSAGE_TYPES = [
        ("text", "Text"),
        ("image", "Image"),
        ("video", "Video"),
        ("report", "Report"),
        ("voice", "Voice message"),
    ]
    sender = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="sent_messages"
    )
    recipient = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="received_messages"
    )
    body = models.TextField(blank=True)
    attachment = models.FileField(
        upload_to="chat_uploads/", blank=True, validators=[validate_chat_attachment]
    )
    message_type = models.CharField(
        max_length=20, choices=MESSAGE_TYPES, default="text"
    )
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class Payment(models.Model):
    STATUS = [
        ("paid", "Paid"),
        ("pending", "Pending"),
        ("failed", "Failed"),
        ("refunded", "Refunded"),
    ]
    METHODS = [
        ("upi", "UPI"),
        ("card", "Card"),
        ("netbanking", "Net banking"),
        ("cash", "Cash"),
    ]
    patient = models.ForeignKey(
        PatientProfile, on_delete=models.CASCADE, related_name="payments"
    )
    appointment = models.ForeignKey(
        Appointment, on_delete=models.SET_NULL, null=True, blank=True
    )
    invoice_number = models.CharField(max_length=40, unique=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    method = models.CharField(max_length=30, choices=METHODS, default="upi")
    status = models.CharField(max_length=20, choices=STATUS, default="pending")
    transaction_id = models.CharField(max_length=80, blank=True)
    issued_on = models.DateField(default=timezone.localdate)
    due_on = models.DateField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    collected_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="collected_payments",
    )

    class Meta:
        ordering = ["-issued_on"]


class Feedback(models.Model):
    patient = models.ForeignKey(PatientProfile, on_delete=models.CASCADE)
    doctor = models.ForeignKey(
        DoctorProfile, on_delete=models.CASCADE, related_name="feedback"
    )
    rating = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    review = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class CMSContent(models.Model):
    CONTENT_TYPES = [
        ("blog", "Health blog"),
        ("faq", "FAQ"),
        ("story", "Success story"),
        ("announcement", "Announcement"),
    ]
    content_type = models.CharField(
        max_length=30, choices=CONTENT_TYPES, default="blog"
    )
    title = models.CharField(max_length=220)
    summary = models.CharField(max_length=320, blank=True)
    body = models.TextField()
    published = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title


class EmailOTP(models.Model):
    PURPOSES = [("verify_email", "Verify email")]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="email_otps")
    purpose = models.CharField(max_length=30, choices=PURPOSES, default="verify_email")
    code_hash = models.CharField(max_length=255)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "purpose", "consumed_at"])]


class ContactMessage(models.Model):
    STATUS = [("new", "New"), ("in_progress", "In progress"), ("closed", "Closed")]

    name = models.CharField(max_length=120)
    email = models.EmailField()
    phone = models.CharField(max_length=24, blank=True)
    subject = models.CharField(max_length=180)
    message = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS, default="new")
    handled_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="handled_contact_messages",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.subject} — {self.name}"


class EmailDelivery(models.Model):
    STATUS = [
        ("pending", "Pending"),
        ("sending", "Sending"),
        ("sent", "Sent"),
        ("failed", "Failed"),
    ]

    event_key = models.CharField(max_length=220, unique=True)
    recipient = models.EmailField()
    subject = models.CharField(max_length=255)
    template_name = models.CharField(max_length=120)
    status = models.CharField(max_length=20, choices=STATUS, default="pending")
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "created_at"])]

    def __str__(self):
        return f"{self.recipient}: {self.subject} ({self.status})"
