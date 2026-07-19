from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import Group, User
from django.db import transaction
from django.db.models import Q
from django.utils.text import slugify
from .models import (
    Appointment,
    ChatMessage,
    CMSContent,
    DoctorProfile,
    EmployeeProfile,
    ExerciseAssignment,
    ContactMessage,
    Feedback,
    MedicalRecord,
    PatientProfile,
    Payment,
    Prescription,
    ProgressEntry,
    TreatmentPlan,
)
from .validators import validate_chat_attachment


class StyledFormMixin:
    MODEL_CHOICE_PROMPTS = {
        "doctor": "Type or choose a doctor / therapist",
        "exercise": "Type or choose an exercise",
        "patient": "Type or choose a patient",
        "staff": "Type or choose a staff member",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "form-check-input")
            else:
                field.widget.attrs.setdefault("class", "form-control")
            if isinstance(field, forms.ModelChoiceField):
                field_label = field.label or name.replace("_", " ")
                prompt = self.MODEL_CHOICE_PROMPTS.get(
                    name, f"Type or choose {field_label.lower()}"
                )
                field.empty_label = prompt
                field.widget.attrs.update(
                    {
                        "data-searchable-select": "true",
                        "data-placeholder": prompt,
                    }
                )
            elif isinstance(field, forms.ChoiceField) and isinstance(
                field.widget, forms.Select
            ):
                choices = list(field.choices)
                if (
                    choices
                    and choices[0][0] == ""
                    and str(choices[0][1]).strip("- ") == ""
                ):
                    label = (field.label or name.replace("_", " ")).lower()
                    field.choices = [("", f"Choose {label}"), *choices[1:]]


class RegisterForm(StyledFormMixin, UserCreationForm):
    first_name = forms.CharField(max_length=80)
    last_name = forms.CharField(max_length=80)
    email = forms.EmailField()
    phone = forms.CharField(max_length=20)

    class Meta:
        model = User
        fields = (
            "first_name",
            "last_name",
            "email",
            "phone",
            "username",
            "password1",
            "password2",
        )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account already uses this email address.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        if commit:
            user.save()
            PatientProfile.objects.create(user=user, phone=self.cleaned_data["phone"])
        return user


class OTPVerificationForm(StyledFormMixin, forms.Form):
    code = forms.CharField(
        label="6-digit verification code",
        min_length=6,
        max_length=6,
        widget=forms.TextInput(
            attrs={
                "inputmode": "numeric",
                "autocomplete": "one-time-code",
                "pattern": "[0-9]{6}",
                "placeholder": "000000",
                "autofocus": True,
            }
        ),
    )

    def clean_code(self):
        code = self.cleaned_data["code"].strip()
        if not code.isdigit():
            raise forms.ValidationError("Enter the 6-digit code from your email.")
        return code


class ContactForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ContactMessage
        fields = ("name", "email", "phone", "subject", "message")
        widgets = {
            "message": forms.Textarea(
                attrs={"rows": 6, "placeholder": "How can our care team help?"}
            ),
            "phone": forms.TextInput(attrs={"autocomplete": "tel"}),
            "email": forms.EmailInput(attrs={"autocomplete": "email"}),
        }


class ReceptionPatientForm(StyledFormMixin, forms.Form):
    first_name = forms.CharField(max_length=80)
    last_name = forms.CharField(max_length=80)
    email = forms.EmailField(help_text="We will email a secure account-setup link.")
    phone = forms.CharField(max_length=20)
    date_of_birth = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    gender = forms.CharField(max_length=30, required=False)
    address = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    emergency_contact = forms.CharField(max_length=100, required=False)

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                "A patient account already uses this email address."
            )
        return email

    def clean_phone(self):
        phone = self.cleaned_data["phone"].strip()
        if PatientProfile.objects.filter(phone=phone).exists():
            raise forms.ValidationError(
                "A patient with this phone number already exists."
            )
        return phone

    @transaction.atomic
    def save(self, *, registered_by):
        data = self.cleaned_data
        base = (
            slugify(data["email"].split("@", 1)[0])
            or slugify(f"{data['first_name']}-{data['last_name']}")
            or "patient"
        )
        username = base[:130]
        suffix = 1
        while User.objects.filter(username=username).exists():
            suffix += 1
            username = f"{base[: 140 - len(str(suffix))]}-{suffix}"
        user = User(
            username=username,
            email=data["email"],
            first_name=data["first_name"],
            last_name=data["last_name"],
            is_active=True,
        )
        user.set_unusable_password()
        user.save()
        return PatientProfile.objects.create(
            user=user,
            phone=data["phone"],
            date_of_birth=data.get("date_of_birth"),
            gender=data.get("gender", ""),
            address=data.get("address", ""),
            emergency_contact=data.get("emergency_contact", ""),
            registered_by=registered_by,
        )


class ReceptionAppointmentForm(StyledFormMixin, forms.ModelForm):
    create_invoice = forms.BooleanField(
        required=False,
        initial=True,
        help_text="Create a pending invoice using the therapist’s consultation fee.",
    )

    class Meta:
        model = Appointment
        fields = (
            "patient",
            "doctor",
            "scheduled_at",
            "mode",
            "concern",
            "duration_minutes",
            "reminder_channel",
        )
        widgets = {
            "scheduled_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
            "concern": forms.TextInput(attrs={"placeholder": "Reason for visit"}),
        }

    def __init__(self, *args, allow_invoice=True, **kwargs):
        super().__init__(*args, **kwargs)
        if not allow_invoice:
            self.fields.pop("create_invoice", None)
        self.fields["patient"].queryset = (
            PatientProfile.objects.filter(user__is_active=True)
            .select_related("user")
            .order_by("user__first_name", "user__last_name")
        )
        self.fields["doctor"].queryset = (
            DoctorProfile.objects.filter(available=True, user__is_active=True)
            .select_related("user")
            .order_by("user__first_name", "user__last_name")
        )
        self.fields["scheduled_at"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["mode"].choices = [("clinic", "In-clinic")]
        self.fields["reminder_channel"].widget = forms.Select(
            choices=[
                ("Email & WhatsApp", "Email & WhatsApp"),
                ("Email", "Email"),
                ("SMS", "SMS"),
            ],
            attrs={"class": "form-control"},
        )


class ReceptionPaymentForm(StyledFormMixin, forms.Form):
    method = forms.ChoiceField(choices=Payment.METHODS)


class ProfileForm(StyledFormMixin, forms.ModelForm):
    first_name = forms.CharField(max_length=80)
    last_name = forms.CharField(max_length=80)
    email = forms.EmailField()

    class Meta:
        model = PatientProfile
        fields = (
            "first_name",
            "last_name",
            "email",
            "phone",
            "date_of_birth",
            "gender",
            "blood_group",
            "address",
            "emergency_contact",
            "conditions",
            "allergies",
            "surgeries",
        )
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

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        users = User.objects.filter(email__iexact=email)
        if self.instance and self.instance.pk:
            users = users.exclude(pk=self.instance.user_id)
        if users.exists():
            raise forms.ValidationError("An account already uses this email address.")
        return email

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
        fields = (
            "doctor",
            "scheduled_at",
            "mode",
            "concern",
            "notes",
            "reminder_channel",
        )
        widgets = {
            "scheduled_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
            "notes": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "Tell your therapist anything that may help them prepare",
                }
            ),
            "concern": forms.TextInput(
                attrs={"placeholder": "For example: lower-back pain review"}
            ),
        }
        labels = {
            "scheduled_at": "Preferred date and time",
            "doctor": "Doctor / therapist",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["scheduled_at"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["mode"].choices = [("clinic", "In-clinic")]
        self.fields["reminder_channel"].widget = forms.Select(
            choices=[
                ("Email & WhatsApp", "Email & WhatsApp"),
                ("SMS", "SMS"),
                ("Email", "Email"),
            ],
            attrs={"class": "form-control"},
        )


class MedicalRecordForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = MedicalRecord
        fields = ("title", "record_type", "record_date", "doctor_name", "notes", "file")
        widgets = {
            "record_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }


class ChatForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ChatMessage
        fields = ("body", "attachment", "message_type")
        widgets = {
            "body": forms.Textarea(
                attrs={"rows": 2, "placeholder": "Type your message or question…"}
            ),
            "attachment": forms.FileInput(
                attrs={"accept": "image/*,video/*,.pdf,.doc,.docx,audio/*"}
            ),
        }


class ProgressForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ProgressEntry
        fields = ("pain_score", "mobility_score", "exercise_adherence", "note")
        widgets = {
            "pain_score": forms.NumberInput(attrs={"min": 0, "max": 10}),
            "mobility_score": forms.NumberInput(attrs={"min": 0, "max": 100}),
            "exercise_adherence": forms.NumberInput(attrs={"min": 0, "max": 100}),
            "note": forms.Textarea(
                attrs={"rows": 3, "placeholder": "How are you feeling today?"}
            ),
        }


class PaymentForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Payment
        fields = ("method",)


class FeedbackForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Feedback
        fields = ("doctor", "rating", "review")
        widgets = {
            "rating": forms.Select(
                choices=[
                    (5, "5 — Excellent"),
                    (4, "4 — Very good"),
                    (3, "3 — Good"),
                    (2, "2 — Fair"),
                    (1, "1 — Poor"),
                ]
            ),
            "review": forms.Textarea(
                attrs={"rows": 4, "placeholder": "Share your experience…"}
            ),
        }


class DoctorPatientFormMixin:
    def __init__(self, *args, doctor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.doctor = doctor
        if (
            doctor
            and isinstance(self.instance, Appointment)
            and not self.instance.doctor_id
        ):
            self.instance.doctor = doctor
        if "patient" in self.fields and doctor:
            self.fields["patient"].queryset = (
                PatientProfile.objects.filter(
                    Q(appointments__doctor=doctor)
                    | Q(treatment_plans__doctor=doctor)
                    | Q(prescriptions__doctor=doctor)
                )
                .distinct()
                .select_related("user")
            )


class DoctorPrescriptionForm(DoctorPatientFormMixin, StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Prescription
        fields = ("patient", "diagnosis", "medicines", "instructions", "issued_on")
        widgets = {
            "medicines": forms.Textarea(
                attrs={
                    "rows": 5,
                    "placeholder": "One medicine or recommendation per line",
                }
            ),
            "instructions": forms.Textarea(attrs={"rows": 4}),
            "issued_on": forms.DateInput(attrs={"type": "date"}),
        }


class DoctorTreatmentForm(DoctorPatientFormMixin, StyledFormMixin, forms.ModelForm):
    class Meta:
        model = TreatmentPlan
        fields = (
            "patient",
            "title",
            "diagnosis",
            "goal",
            "instructions",
            "progress",
            "started_on",
            "next_review",
            "active",
        )
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
        fields = (
            "patient",
            "scheduled_at",
            "mode",
            "concern",
            "duration_minutes",
            "reminder_channel",
        )
        widgets = {
            "scheduled_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            )
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["scheduled_at"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["mode"].choices = [("clinic", "In-clinic")]
        self.fields["reminder_channel"].widget = forms.Select(
            choices=[
                ("Email & WhatsApp", "Email & WhatsApp"),
                ("SMS", "SMS"),
                ("Email", "Email"),
            ],
            attrs={"class": "form-control"},
        )


class DoctorDocumentForm(DoctorPatientFormMixin, StyledFormMixin, forms.ModelForm):
    class Meta:
        model = MedicalRecord
        fields = ("patient", "title", "record_type", "record_date", "notes", "file")
        widgets = {
            "record_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 4}),
        }


class DoctorFeedbackForm(DoctorPatientFormMixin, StyledFormMixin, forms.Form):
    patient = forms.ModelChoiceField(queryset=PatientProfile.objects.none())
    body = forms.CharField(
        label="Progress feedback",
        widget=forms.Textarea(
            attrs={
                "rows": 5,
                "placeholder": "Share encouragement, plan adjustments, or recovery feedback…",
            }
        ),
    )


class DoctorReplyForm(DoctorPatientFormMixin, StyledFormMixin, forms.Form):
    patient = forms.ModelChoiceField(queryset=PatientProfile.objects.none())
    body = forms.CharField(
        label="Message",
        widget=forms.Textarea(
            attrs={"rows": 3, "placeholder": "Write a secure reply…"}
        ),
    )
    attachment = forms.FileField(
        required=False,
        validators=[validate_chat_attachment],
        widget=forms.FileInput(
            attrs={"accept": "image/*,video/*,.pdf,.doc,.docx,audio/*"}
        ),
    )


class ClinicalSessionForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Appointment
        fields = ("status", "notes")
        widgets = {
            "notes": forms.Textarea(
                attrs={
                    "rows": 8,
                    "placeholder": "Assessment, treatment delivered, patient response, and next steps…",
                }
            )
        }


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


EMPLOYEE_ROLE_CHOICES = [
    ("Clinic Manager", "Clinic Manager"),
    ("Reception", "Reception"),
    ("Billing", "Billing"),
    ("Content Editor", "Content Editor"),
]


class AdminEmployeeForm(StyledFormMixin, forms.ModelForm):
    first_name = forms.CharField(max_length=80)
    last_name = forms.CharField(max_length=80)
    email = forms.EmailField()
    username = forms.CharField(
        max_length=80,
        help_text="Used for portal login when access is enabled.",
    )
    password = forms.CharField(
        min_length=8,
        required=False,
        widget=forms.PasswordInput(),
        help_text="Required for a new employee. Leave blank while editing to keep the current password.",
    )
    role = forms.ChoiceField(choices=EMPLOYEE_ROLE_CHOICES)

    class Meta:
        model = EmployeeProfile
        fields = (
            "first_name",
            "last_name",
            "email",
            "phone",
            "job_title",
            "department",
            "employment_type",
            "shift",
            "joined_on",
            "monthly_salary",
            "emergency_contact",
            "address",
            "notes",
            "username",
            "password",
            "role",
            "portal_access",
            "active",
        )
        widgets = {
            "joined_on": forms.DateInput(attrs={"type": "date"}),
            "monthly_salary": forms.NumberInput(attrs={"min": 0, "step": "0.01"}),
            "address": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {
            "portal_access": "Allow portal login",
            "active": "Currently employed",
            "monthly_salary": "Monthly salary (optional)",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            user = self.instance.user
            self.fields["first_name"].initial = user.first_name
            self.fields["last_name"].initial = user.last_name
            self.fields["email"].initial = user.email
            self.fields["username"].initial = user.username
            self.fields["role"].initial = user.groups.values_list(
                "name", flat=True
            ).first()
        else:
            self.fields["active"].initial = True
            self.fields["password"].required = True

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        users = User.objects.filter(username__iexact=username)
        if self.instance and self.instance.pk:
            users = users.exclude(pk=self.instance.user_id)
        if users.exists():
            raise forms.ValidationError("This username is already in use.")
        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        users = User.objects.filter(email__iexact=email)
        if self.instance and self.instance.pk:
            users = users.exclude(pk=self.instance.user_id)
        if users.exists():
            raise forms.ValidationError("This email address is already in use.")
        return email

    def clean(self):
        cleaned = super().clean()
        if not self.instance.pk and not cleaned.get("password"):
            self.add_error("password", "Set a temporary password for the new employee.")
        return cleaned

    @transaction.atomic
    def save(self, commit=True):
        profile = super().save(commit=False)
        creating = not profile.pk
        user = User() if creating else profile.user
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        user.email = self.cleaned_data["email"]
        user.username = self.cleaned_data["username"]
        user.is_staff = profile.portal_access
        user.is_active = profile.active and profile.portal_access
        password = self.cleaned_data.get("password")
        if password:
            user.set_password(password)
        user.save()

        group, _ = Group.objects.get_or_create(name=self.cleaned_data["role"])
        user.groups.clear()
        user.groups.add(group)
        profile.user = user
        if commit:
            profile.save()
        return profile


class AdminStaffForm(StyledFormMixin, forms.Form):
    ROLE_CHOICES = EMPLOYEE_ROLE_CHOICES
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
        widgets = {
            "summary": forms.Textarea(attrs={"rows": 2}),
            "body": forms.Textarea(attrs={"rows": 8}),
        }


class RoleAssignmentForm(StyledFormMixin, forms.Form):
    staff = forms.ModelChoiceField(queryset=User.objects.none())
    role = forms.ChoiceField(choices=AdminStaffForm.ROLE_CHOICES)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["staff"].queryset = User.objects.filter(
            is_staff=True, is_superuser=False
        ).order_by("first_name", "username")
