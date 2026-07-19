from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.db.models import Q
from .models import (
    Appointment, ChatMessage, CMSContent, DoctorProfile, ExerciseAssignment,
    Feedback, MedicalRecord, PatientProfile, Payment, Prescription,
    ProgressEntry, TreatmentPlan,
)


class StyledFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "form-check-input")
            else:
                field.widget.attrs.setdefault("class", "form-control")


class RegisterForm(StyledFormMixin, UserCreationForm):
    first_name = forms.CharField(max_length=80)
    last_name = forms.CharField(max_length=80)
    email = forms.EmailField()
    phone = forms.CharField(max_length=20)

    class Meta:
        model = User
        fields = ("first_name", "last_name", "email", "phone", "username", "password1", "password2")

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        if commit:
            user.save()
            PatientProfile.objects.create(user=user, phone=self.cleaned_data["phone"])
        return user


class ProfileForm(StyledFormMixin, forms.ModelForm):
    first_name = forms.CharField(max_length=80)
    last_name = forms.CharField(max_length=80)
    email = forms.EmailField()

    class Meta:
        model = PatientProfile
        fields = ("first_name", "last_name", "email", "phone", "date_of_birth", "gender",
                  "blood_group", "address", "emergency_contact", "conditions", "allergies", "surgeries")
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date"}),
            "address": forms.Textarea(attrs={"rows": 3}),
            "conditions": forms.Textarea(attrs={"rows": 3}),
            "allergies": forms.Textarea(attrs={"rows": 3}),
            "surgeries": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["first_name"].initial = self.instance.user.first_name
            self.fields["last_name"].initial = self.instance.user.last_name
            self.fields["email"].initial = self.instance.user.email

    def save(self, commit=True):
        profile = super().save(commit=False)
        profile.user.first_name = self.cleaned_data["first_name"]
        profile.user.last_name = self.cleaned_data["last_name"]
        profile.user.email = self.cleaned_data["email"]
        if commit:
            profile.user.save()
            profile.save()
        return profile


class AppointmentForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Appointment
        fields = ("doctor", "scheduled_at", "mode", "concern", "notes", "reminder_channel")
        widgets = {
            "scheduled_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "notes": forms.Textarea(attrs={"rows": 4, "placeholder": "Tell your therapist anything that may help them prepare"}),
            "concern": forms.TextInput(attrs={"placeholder": "For example: lower-back pain review"}),
        }
        labels = {"scheduled_at": "Preferred date and time", "doctor": "Doctor / therapist"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["scheduled_at"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["reminder_channel"].widget = forms.Select(
            choices=[("Email & WhatsApp", "Email & WhatsApp"), ("SMS", "SMS"), ("Email", "Email")],
            attrs={"class": "form-control"},
        )


class MedicalRecordForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = MedicalRecord
        fields = ("title", "record_type", "record_date", "doctor_name", "notes", "file")
        widgets = {"record_date": forms.DateInput(attrs={"type": "date"}), "notes": forms.Textarea(attrs={"rows": 3})}


class ChatForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ChatMessage
        fields = ("body", "attachment", "message_type")
        widgets = {
            "body": forms.Textarea(attrs={"rows": 2, "placeholder": "Type your message or question…"}),
            "attachment": forms.FileInput(attrs={"accept": "image/*,video/*,.pdf,.doc,.docx,audio/*"}),
        }


class ProgressForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ProgressEntry
        fields = ("pain_score", "mobility_score", "exercise_adherence", "note")
        widgets = {
            "pain_score": forms.NumberInput(attrs={"min": 0, "max": 10}),
            "mobility_score": forms.NumberInput(attrs={"min": 0, "max": 100}),
            "exercise_adherence": forms.NumberInput(attrs={"min": 0, "max": 100}),
            "note": forms.Textarea(attrs={"rows": 3, "placeholder": "How are you feeling today?"}),
        }


class PaymentForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Payment
        fields = ("method",)


class FeedbackForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Feedback
        fields = ("doctor", "rating", "review")
        widgets = {"rating": forms.Select(choices=[(5, "5 — Excellent"), (4, "4 — Very good"), (3, "3 — Good"), (2, "2 — Fair"), (1, "1 — Poor")]),
                   "review": forms.Textarea(attrs={"rows": 4, "placeholder": "Share your experience…"})}


class DoctorPatientFormMixin:
    def __init__(self, *args, doctor=None, **kwargs):
        super().__init__(*args, **kwargs)
        if "patient" in self.fields and doctor:
            self.fields["patient"].queryset = PatientProfile.objects.filter(
                Q(appointments__doctor=doctor) |
                Q(treatment_plans__doctor=doctor) |
                Q(prescriptions__doctor=doctor)
            ).distinct().select_related("user")


class DoctorPrescriptionForm(DoctorPatientFormMixin, StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Prescription
        fields = ("patient", "diagnosis", "medicines", "instructions", "issued_on")
        widgets = {
            "medicines": forms.Textarea(attrs={"rows": 5, "placeholder": "One medicine or recommendation per line"}),
            "instructions": forms.Textarea(attrs={"rows": 4}),
            "issued_on": forms.DateInput(attrs={"type": "date"}),
        }


class DoctorTreatmentForm(DoctorPatientFormMixin, StyledFormMixin, forms.ModelForm):
    class Meta:
        model = TreatmentPlan
        fields = ("patient", "title", "diagnosis", "goal", "instructions", "progress", "started_on", "next_review", "active")
        widgets = {
            "goal": forms.Textarea(attrs={"rows": 3}),
            "instructions": forms.Textarea(attrs={"rows": 5}),
            "progress": forms.NumberInput(attrs={"min": 0, "max": 100}),
            "started_on": forms.DateInput(attrs={"type": "date"}),
            "next_review": forms.DateInput(attrs={"type": "date"}),
        }


class DoctorExerciseForm(DoctorPatientFormMixin, StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ExerciseAssignment
        fields = ("patient", "exercise", "repetitions", "frequency")


class DoctorFollowUpForm(DoctorPatientFormMixin, StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Appointment
        fields = ("patient", "scheduled_at", "mode", "concern", "duration_minutes", "reminder_channel")
        widgets = {"scheduled_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["scheduled_at"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["reminder_channel"].widget = forms.Select(
            choices=[("Email & WhatsApp", "Email & WhatsApp"), ("SMS", "SMS"), ("Email", "Email")],
            attrs={"class": "form-control"},
        )


class DoctorDocumentForm(DoctorPatientFormMixin, StyledFormMixin, forms.ModelForm):
    class Meta:
        model = MedicalRecord
        fields = ("patient", "title", "record_type", "record_date", "notes", "file")
        widgets = {"record_date": forms.DateInput(attrs={"type": "date"}), "notes": forms.Textarea(attrs={"rows": 4})}


class DoctorFeedbackForm(DoctorPatientFormMixin, StyledFormMixin, forms.Form):
    patient = forms.ModelChoiceField(queryset=PatientProfile.objects.none())
    body = forms.CharField(label="Progress feedback", widget=forms.Textarea(attrs={"rows": 5, "placeholder": "Share encouragement, plan adjustments, or recovery feedback…"}))


class DoctorReplyForm(DoctorPatientFormMixin, StyledFormMixin, forms.Form):
    patient = forms.ModelChoiceField(queryset=PatientProfile.objects.none())
    body = forms.CharField(label="Message", widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Write a secure reply…"}))
    attachment = forms.FileField(required=False, widget=forms.FileInput(attrs={"accept": "image/*,video/*,.pdf,.doc,.docx,audio/*"}))


class ClinicalSessionForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Appointment
        fields = ("status", "notes")
        widgets = {"notes": forms.Textarea(attrs={"rows": 8, "placeholder": "Assessment, treatment delivered, patient response, and next steps…"})}


class AdminDoctorForm(StyledFormMixin, forms.Form):
    first_name = forms.CharField(max_length=80)
    last_name = forms.CharField(max_length=80)
    email = forms.EmailField()
    username = forms.CharField(max_length=80)
    password = forms.CharField(min_length=8, widget=forms.PasswordInput())
    specialization = forms.CharField(max_length=120)
    qualifications = forms.CharField(max_length=180, required=False)
    experience_years = forms.IntegerField(min_value=0, max_value=70)
    consultation_fee = forms.DecimalField(min_value=0, max_digits=8, decimal_places=2)

    def clean_username(self):
        username = self.cleaned_data["username"]
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("This username is already in use.")
        return username


class AdminStaffForm(StyledFormMixin, forms.Form):
    ROLE_CHOICES = [("Clinic Manager", "Clinic Manager"), ("Reception", "Reception"), ("Billing", "Billing"), ("Content Editor", "Content Editor")]
    first_name = forms.CharField(max_length=80)
    last_name = forms.CharField(max_length=80)
    email = forms.EmailField()
    username = forms.CharField(max_length=80)
    password = forms.CharField(min_length=8, widget=forms.PasswordInput())
    role = forms.ChoiceField(choices=ROLE_CHOICES)

    def clean_username(self):
        username = self.cleaned_data["username"]
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("This username is already in use.")
        return username


class CMSContentForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = CMSContent
        fields = ("content_type", "title", "summary", "body", "published")
        widgets = {"summary": forms.Textarea(attrs={"rows": 2}), "body": forms.Textarea(attrs={"rows": 8})}


class RoleAssignmentForm(StyledFormMixin, forms.Form):
    staff = forms.ModelChoiceField(queryset=User.objects.none())
    role = forms.ChoiceField(choices=AdminStaffForm.ROLE_CHOICES)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["staff"].queryset = User.objects.filter(is_staff=True, is_superuser=False).order_by("first_name", "username")
