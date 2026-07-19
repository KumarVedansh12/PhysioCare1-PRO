from django.contrib.auth.models import User
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class PatientProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="patient_profile")
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
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.patient_id:
            self.patient_id = f"PC-{self.pk:05d}"
            super().save(update_fields=["patient_id"])

    def __str__(self):
        return self.user.get_full_name() or self.user.username


class DoctorProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="doctor_profile")
    specialization = models.CharField(max_length=120)
    qualifications = models.CharField(max_length=180, blank=True)
    experience_years = models.PositiveIntegerField(default=0)
    bio = models.TextField(blank=True)
    consultation_fee = models.DecimalField(max_digits=8, decimal_places=2, default=800)
    rating = models.DecimalField(max_digits=2, decimal_places=1, default=4.8)
    available = models.BooleanField(default=True)

    def __str__(self):
        return f"Dr. {self.user.get_full_name() or self.user.username}"


class Appointment(models.Model):
    STATUS_CHOICES = [
        ("confirmed", "Confirmed"), ("pending", "Pending"),
        ("completed", "Completed"), ("cancelled", "Cancelled"),
    ]
    MODE_CHOICES = [("clinic", "In-clinic"), ("video", "Video consultation")]
    patient = models.ForeignKey(PatientProfile, on_delete=models.CASCADE, related_name="appointments")
    doctor = models.ForeignKey(DoctorProfile, on_delete=models.PROTECT, related_name="appointments")
    scheduled_at = models.DateTimeField()
    duration_minutes = models.PositiveIntegerField(default=45)
    concern = models.CharField(max_length=240)
    notes = models.TextField(blank=True)
    mode = models.CharField(max_length=20, choices=MODE_CHOICES, default="clinic")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="confirmed")
    reminder_channel = models.CharField(max_length=30, default="Email & WhatsApp")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["scheduled_at"]

    def __str__(self):
        return f"{self.patient} with {self.doctor}"


class TreatmentPlan(models.Model):
    patient = models.ForeignKey(PatientProfile, on_delete=models.CASCADE, related_name="treatment_plans")
    doctor = models.ForeignKey(DoctorProfile, on_delete=models.PROTECT, related_name="treatment_plans")
    title = models.CharField(max_length=180)
    diagnosis = models.CharField(max_length=220, blank=True)
    goal = models.TextField()
    instructions = models.TextField(blank=True)
    progress = models.PositiveIntegerField(default=0, validators=[MaxValueValidator(100)])
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
    patient = models.ForeignKey(PatientProfile, on_delete=models.CASCADE, related_name="exercise_assignments")
    exercise = models.ForeignKey(Exercise, on_delete=models.CASCADE)
    assigned_by = models.ForeignKey(DoctorProfile, on_delete=models.PROTECT)
    repetitions = models.CharField(max_length=80, default="10 reps × 2 sets")
    frequency = models.CharField(max_length=80, default="Once daily")
    completed_today = models.BooleanField(default=False)
    assigned_on = models.DateField(default=timezone.localdate)


class ProgressEntry(models.Model):
    patient = models.ForeignKey(PatientProfile, on_delete=models.CASCADE, related_name="progress_entries")
    recorded_on = models.DateField(default=timezone.localdate)
    pain_score = models.PositiveIntegerField(validators=[MaxValueValidator(10)])
    mobility_score = models.PositiveIntegerField(validators=[MaxValueValidator(100)])
    exercise_adherence = models.PositiveIntegerField(default=0, validators=[MaxValueValidator(100)])
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["recorded_on"]


class Prescription(models.Model):
    patient = models.ForeignKey(PatientProfile, on_delete=models.CASCADE, related_name="prescriptions")
    doctor = models.ForeignKey(DoctorProfile, on_delete=models.PROTECT)
    diagnosis = models.CharField(max_length=220)
    medicines = models.TextField(help_text="One medicine per line")
    instructions = models.TextField(blank=True)
    issued_on = models.DateField(default=timezone.localdate)

    class Meta:
        ordering = ["-issued_on"]


class MedicalRecord(models.Model):
    RECORD_TYPES = [
        ("lab", "Lab report"), ("scan", "X-ray / MRI"),
        ("visit", "Visit note"), ("certificate", "Medical certificate"),
        ("prescription", "Prescription"), ("other", "Other document"),
    ]
    patient = models.ForeignKey(PatientProfile, on_delete=models.CASCADE, related_name="medical_records")
    title = models.CharField(max_length=180)
    record_type = models.CharField(max_length=30, choices=RECORD_TYPES)
    record_date = models.DateField(default=timezone.localdate)
    doctor_name = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)
    file = models.FileField(upload_to="reports/", blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-record_date"]


class Notification(models.Model):
    TYPES = [("appointment", "Appointment"), ("medicine", "Medicine"), ("exercise", "Exercise"),
             ("payment", "Payment"), ("followup", "Follow-up"), ("general", "General")]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="portal_notifications")
    title = models.CharField(max_length=180)
    message = models.TextField()
    notification_type = models.CharField(max_length=30, choices=TYPES, default="general")
    action_url = models.CharField(max_length=240, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class ChatMessage(models.Model):
    MESSAGE_TYPES = [("text", "Text"), ("image", "Image"), ("video", "Video"),
                     ("report", "Report"), ("voice", "Voice message")]
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sent_messages")
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name="received_messages")
    body = models.TextField(blank=True)
    attachment = models.FileField(upload_to="chat_uploads/", blank=True)
    message_type = models.CharField(max_length=20, choices=MESSAGE_TYPES, default="text")
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class Payment(models.Model):
    STATUS = [("paid", "Paid"), ("pending", "Pending"), ("failed", "Failed"), ("refunded", "Refunded")]
    METHODS = [("upi", "UPI"), ("card", "Card"), ("netbanking", "Net banking"), ("cash", "Cash")]
    patient = models.ForeignKey(PatientProfile, on_delete=models.CASCADE, related_name="payments")
    appointment = models.ForeignKey(Appointment, on_delete=models.SET_NULL, null=True, blank=True)
    invoice_number = models.CharField(max_length=40, unique=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    method = models.CharField(max_length=30, choices=METHODS, default="upi")
    status = models.CharField(max_length=20, choices=STATUS, default="pending")
    transaction_id = models.CharField(max_length=80, blank=True)
    issued_on = models.DateField(default=timezone.localdate)
    due_on = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-issued_on"]


class Feedback(models.Model):
    patient = models.ForeignKey(PatientProfile, on_delete=models.CASCADE)
    doctor = models.ForeignKey(DoctorProfile, on_delete=models.CASCADE, related_name="feedback")
    rating = models.PositiveIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    review = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class CMSContent(models.Model):
    CONTENT_TYPES = [
        ("blog", "Health blog"), ("faq", "FAQ"),
        ("story", "Success story"), ("announcement", "Announcement"),
    ]
    content_type = models.CharField(max_length=30, choices=CONTENT_TYPES, default="blog")
    title = models.CharField(max_length=220)
    summary = models.CharField(max_length=320, blank=True)
    body = models.TextField()
    published = models.BooleanField(default=False)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title
