import base64
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (
    Appointment,
    ChatMessage,
    CMSContent,
    ContactMessage,
    DoctorProfile,
    EmployeeProfile,
    EmailDelivery,
    Exercise,
    ExerciseAssignment,
    MedicalRecord,
    Notification,
    PatientProfile,
    Payment,
    Prescription,
    ProgressEntry,
    TreatmentPlan,
)
from .backups import decrypt_and_validate_backup
from .emailing import send_due_appointment_reminders
from .forms import AppointmentForm, DoctorFeedbackForm, MedicalRecordForm


TEST_BACKUP_KEY = base64.urlsafe_b64encode(b"p" * 32).decode()
VALID_PDF = b"%PDF-1.4\n% PhysioCare test document\n%%EOF\n"


class FormAccessibilityTests(SimpleTestCase):
    def test_selects_use_readable_prompts_and_model_choices_are_searchable(self):
        record_type = MedicalRecordForm().fields["record_type"]
        self.assertEqual(list(record_type.choices)[0][1], "Choose record type")

        patient = DoctorFeedbackForm().fields["patient"]
        self.assertEqual(patient.empty_label, "Type or choose a patient")
        self.assertEqual(patient.widget.attrs["data-searchable-select"], "true")

        self.assertEqual(
            list(AppointmentForm().fields["mode"].choices),
            [("clinic", "In-clinic")],
        )

    def test_disguised_medical_upload_is_rejected_without_database_access(self):
        form = MedicalRecordForm(
            data={
                "title": "Disguised file",
                "record_type": "lab",
                "record_date": timezone.localdate().isoformat(),
                "doctor_name": "Lab",
                "notes": "",
            },
            files={
                "file": SimpleUploadedFile(
                    "disguised.pdf", b"not a pdf", content_type="application/pdf"
                )
            },
        )
        self.assertFalse(form.is_valid())
        self.assertIn("file", form.errors)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_ENABLED=True,
    CONTACT_EMAIL="clinic@test.local",
    EMAIL_REPLY_TO="clinic@test.local",
    SITE_URL="https://testserver",
)
class EmailWorkflowTests(TestCase):
    def setUp(self):
        doctor_user = User.objects.create_user(
            "email-doctor",
            "doctor@test.local",
            "StrongPass123",
            first_name="Meera",
            last_name="Kapoor",
        )
        self.doctor = DoctorProfile.objects.create(
            user=doctor_user, specialization="Physiotherapist"
        )

    def test_registration_otp_verifies_and_activates_patient(self):
        response = self.client.post(
            reverse("register"),
            {
                "first_name": "Asha",
                "last_name": "Nair",
                "email": "asha@test.local",
                "phone": "9000000000",
                "username": "asha-email-test",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
            },
        )
        self.assertRedirects(response, reverse("verify_email"))
        user = User.objects.get(username="asha-email-test")
        self.assertFalse(user.is_active)
        self.assertEqual(len(mail.outbox), 1)
        code = next(
            part
            for part in mail.outbox[0].body.split()
            if part.isdigit() and len(part) == 6
        )
        response = self.client.post(reverse("verify_email"), {"code": code})
        self.assertRedirects(response, reverse("dashboard"))
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertIsNotNone(user.patient_profile.email_verified_at)

    def test_password_reset_contact_and_reminder_emails(self):
        patient_user = User.objects.create_user(
            "email-patient", "patient@test.local", "StrongPass123", first_name="Ravi"
        )
        patient = PatientProfile.objects.create(user=patient_user)

        response = self.client.post(
            reverse("password_reset"), {"email": patient_user.email}
        )
        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)

        response = self.client.post(
            reverse("contact"),
            {
                "name": "Site Visitor",
                "email": "visitor@test.local",
                "phone": "9000000001",
                "subject": "Appointment enquiry",
                "message": "Please contact me about a consultation.",
            },
        )
        self.assertRedirects(response, reverse("contact"))
        self.assertTrue(
            ContactMessage.objects.filter(email="visitor@test.local").exists()
        )
        self.assertEqual(len(mail.outbox), 3)

        appointment = Appointment.objects.create(
            patient=patient,
            doctor=self.doctor,
            scheduled_at=timezone.now() + timedelta(hours=5),
            concern="Recovery review",
            status="confirmed",
        )
        self.assertEqual(send_due_appointment_reminders(), 1)
        self.assertEqual(send_due_appointment_reminders(), 0)
        schedule_version = int(appointment.scheduled_at.timestamp())
        self.assertTrue(
            EmailDelivery.objects.filter(
                event_key=f"appointment:{appointment.pk}:reminder:{schedule_version}:24-hour",
                status="sent",
            ).exists()
        )

        appointment.scheduled_at += timedelta(hours=1)
        appointment.save(update_fields=["scheduled_at", "updated_at"])
        self.assertEqual(send_due_appointment_reminders(), 1)


class SecurityRegressionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.patient_user = User.objects.create_user(
            "security-patient", password="StrongPass123", first_name="Asha"
        )
        cls.patient = PatientProfile.objects.create(user=cls.patient_user)
        cls.doctor_user = User.objects.create_user(
            "security-doctor", password="StrongPass123", first_name="Meera"
        )
        cls.doctor = DoctorProfile.objects.create(
            user=cls.doctor_user, specialization="Physiotherapist"
        )
        cls.appointment = Appointment.objects.create(
            patient=cls.patient,
            doctor=cls.doctor,
            scheduled_at=timezone.now() + timedelta(days=2),
            concern="Security review",
        )

    def test_login_next_url_accepts_local_path_and_rejects_external_host(self):
        response = self.client.post(
            f"{reverse('login')}?next=https://attacker.example/phishing",
            {"username": self.patient_user.username, "password": "StrongPass123"},
        )
        self.assertRedirects(
            response, reverse("dashboard"), fetch_redirect_response=False
        )

        self.client.logout()
        response = self.client.post(
            f"{reverse('login')}?next={reverse('appointment_history')}",
            {"username": self.patient_user.username, "password": "StrongPass123"},
        )
        self.assertRedirects(
            response, reverse("appointment_history"), fetch_redirect_response=False
        )

    def test_staff_roles_are_limited_to_their_own_workspaces(self):
        billing_group = Group.objects.create(name="Billing")
        billing = User.objects.create_user(
            "billing-limited", password="StrongPass123", is_staff=True
        )
        billing.groups.add(billing_group)
        self.client.force_login(billing)
        self.assertEqual(
            self.client.get(reverse("admin_manage", args=["payments"])).status_code, 200
        )
        self.assertRedirects(
            self.client.get(reverse("admin_manage", args=["patients"])),
            reverse("admin_manage", args=["payments"]),
        )

        content_group = Group.objects.create(name="Content Editor")
        content = User.objects.create_user(
            "content-limited", password="StrongPass123", is_staff=True
        )
        content.groups.add(content_group)
        self.client.force_login(content)
        self.assertEqual(
            self.client.get(reverse("admin_manage", args=["cms"])).status_code, 200
        )
        self.assertRedirects(
            self.client.get(reverse("admin_manage", args=["payments"])),
            reverse("admin_manage", args=["cms"]),
        )

        manager_group = Group.objects.create(name="Clinic Manager")
        manager = User.objects.create_user(
            "clinic-manager", password="StrongPass123", is_staff=True
        )
        manager.groups.add(manager_group)
        self.client.force_login(manager)
        self.assertEqual(self.client.get(reverse("admin_dashboard")).status_code, 200)
        self.assertRedirects(
            self.client.post(reverse("admin_backup_download")),
            reverse("admin_dashboard"),
        )
        self.assertEqual(self.client.get("/django-admin/").status_code, 302)

    def test_patient_booking_rejects_past_and_overlapping_times(self):
        self.client.force_login(self.patient_user)
        base_data = {
            "doctor": self.doctor.pk,
            "mode": "clinic",
            "concern": "Follow-up",
            "notes": "",
            "reminder_channel": "Email",
        }
        overlapping = timezone.localtime(
            self.appointment.scheduled_at + timedelta(minutes=15)
        ).strftime("%Y-%m-%dT%H:%M")
        response = self.client.post(
            reverse("book_appointment"), {**base_data, "scheduled_at": overlapping}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "overlapping appointment")

        past = (timezone.localtime() - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
        response = self.client.post(
            reverse("book_appointment"), {**base_data, "scheduled_at": past}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "future appointment time")
        self.assertEqual(self.patient.appointments.count(), 1)

    def test_chat_routes_to_the_patients_actual_appointment_doctor(self):
        other_user = User.objects.create_user("assigned-doctor", first_name="Arun")
        assigned_doctor = DoctorProfile.objects.create(
            user=other_user, specialization="Sports Physiotherapist"
        )
        other_patient_user = User.objects.create_user("chat-routing-patient")
        other_patient = PatientProfile.objects.create(user=other_patient_user)
        Appointment.objects.create(
            patient=other_patient,
            doctor=assigned_doctor,
            scheduled_at=timezone.now() + timedelta(days=3),
            concern="Sports recovery",
        )
        self.client.force_login(other_patient_user)
        response = self.client.post(
            reverse("chat"), {"body": "Question for my doctor", "message_type": "text"}
        )
        self.assertRedirects(response, reverse("chat"))
        self.assertTrue(
            ChatMessage.objects.filter(
                sender=other_patient_user,
                recipient=other_user,
                body="Question for my doctor",
            ).exists()
        )

    def test_private_file_downloads_require_ownership_or_care_relationship(self):
        record = MedicalRecord.objects.create(
            patient=self.patient,
            title="Private report",
            record_type="lab",
            file=SimpleUploadedFile(
                "private.pdf", VALID_PDF, content_type="application/pdf"
            ),
        )
        message = ChatMessage.objects.create(
            sender=self.patient_user,
            recipient=self.doctor_user,
            body="Private attachment",
            attachment=SimpleUploadedFile(
                "message.pdf", VALID_PDF, content_type="application/pdf"
            ),
            message_type="report",
        )

        self.client.force_login(self.patient_user)
        response = self.client.get(reverse("medical_record_download", args=[record.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store, max-age=0")
        self.assertEqual(b"".join(response.streaming_content), VALID_PDF)

        self.client.force_login(self.doctor_user)
        self.assertEqual(
            self.client.get(
                reverse("medical_record_download", args=[record.pk])
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(
                reverse("chat_attachment_download", args=[message.pk])
            ).status_code,
            200,
        )

        stranger_user = User.objects.create_user("unrelated-patient")
        PatientProfile.objects.create(user=stranger_user)
        self.client.force_login(stranger_user)
        self.assertEqual(
            self.client.get(
                reverse("medical_record_download", args=[record.pk])
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                reverse("chat_attachment_download", args=[message.pk])
            ).status_code,
            404,
        )

    def test_disguised_upload_is_rejected(self):
        form = MedicalRecordForm(
            data={
                "title": "Disguised file",
                "record_type": "lab",
                "record_date": timezone.localdate().isoformat(),
                "doctor_name": "Lab",
                "notes": "",
            },
            files={
                "file": SimpleUploadedFile(
                    "disguised.pdf", b"not a pdf", content_type="application/pdf"
                )
            },
        )
        self.assertFalse(form.is_valid())
        self.assertIn("file", form.errors)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_ENABLED=True,
    CONTACT_EMAIL="clinic@test.local",
    EMAIL_REPLY_TO="clinic@test.local",
    SITE_URL="https://testserver",
)
class ReceptionWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        reception_group = Group.objects.create(name="Reception")
        cls.reception_user = User.objects.create_user(
            "reception-test",
            "desk@test.local",
            "StrongPass123",
            first_name="Priya",
            is_staff=True,
        )
        cls.reception_user.groups.add(reception_group)
        doctor_user = User.objects.create_user(
            "reception-doctor",
            "doctor-desk@test.local",
            "StrongPass123",
            first_name="Meera",
        )
        cls.doctor = DoctorProfile.objects.create(
            user=doctor_user,
            specialization="Musculoskeletal Physiotherapist",
            consultation_fee=Decimal("850.00"),
        )

    def setUp(self):
        self.client.login(username="reception-test", password="StrongPass123")

    def test_reception_access_patient_booking_queue_payment_and_enquiry(self):
        self.assertEqual(
            self.client.get(reverse("reception_dashboard")).status_code, 200
        )
        denied = self.client.get(reverse("admin_dashboard"))
        self.assertEqual(denied.status_code, 302)
        self.assertEqual(denied.url, reverse("dashboard"))

        response = self.client.post(
            reverse("reception_patient_new"),
            {
                "first_name": "Ravi",
                "last_name": "Kumar",
                "email": "ravi.reception@test.local",
                "phone": "9000012345",
                "date_of_birth": "1990-03-12",
                "gender": "Male",
                "address": "Bengaluru",
                "emergency_contact": "Anita · 9000099999",
            },
        )
        patient = PatientProfile.objects.get(user__email="ravi.reception@test.local")
        self.assertEqual(response.status_code, 302)
        self.assertIn(f"patient={patient.pk}", response.url)
        self.assertEqual(patient.registered_by, self.reception_user)
        self.assertFalse(patient.user.has_usable_password())
        self.assertEqual(len(mail.outbox), 1)

        when = (
            (timezone.localtime() + timedelta(days=3))
            .replace(hour=10, minute=0, second=0, microsecond=0)
            .strftime("%Y-%m-%dT%H:%M")
        )
        response = self.client.post(
            reverse("reception_appointment_new"),
            {
                "patient": patient.pk,
                "doctor": self.doctor.pk,
                "scheduled_at": when,
                "mode": "clinic",
                "concern": "Initial mobility assessment",
                "duration_minutes": 45,
                "reminder_channel": "Email",
                "create_invoice": "on",
            },
        )
        appointment = Appointment.objects.get(
            patient=patient, concern="Initial mobility assessment"
        )
        self.assertRedirects(
            response, reverse("reception_patient_detail", args=[patient.pk])
        )
        payment = Payment.objects.get(appointment=appointment)
        self.assertEqual(payment.amount, Decimal("850.00"))
        self.assertEqual(payment.status, "pending")

        new_when = (
            (timezone.localtime() + timedelta(days=4))
            .replace(hour=11, minute=0, second=0, microsecond=0)
            .strftime("%Y-%m-%dT%H:%M")
        )
        response = self.client.post(
            reverse("reception_appointment_edit", args=[appointment.pk]),
            {
                "patient": patient.pk,
                "doctor": self.doctor.pk,
                "scheduled_at": new_when,
                "mode": "clinic",
                "concern": "Initial mobility assessment",
                "duration_minutes": 45,
                "reminder_channel": "Email",
            },
        )
        self.assertRedirects(
            response, reverse("reception_patient_detail", args=[patient.pk])
        )
        appointment.refresh_from_db()
        self.assertEqual(
            timezone.localtime(appointment.scheduled_at).day,
            (timezone.localdate() + timedelta(days=4)).day,
        )

        response = self.client.post(
            reverse("reception_appointment_status", args=[appointment.pk]),
            {"status": "checked_in"},
        )
        self.assertRedirects(response, reverse("reception_dashboard"))
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, "checked_in")
        self.assertIsNotNone(appointment.checked_in_at)

        response = self.client.post(
            reverse("reception_payment_collect", args=[payment.pk]), {"method": "card"}
        )
        self.assertRedirects(
            response, reverse("reception_patient_detail", args=[patient.pk])
        )
        payment.refresh_from_db()
        self.assertEqual(payment.status, "paid")
        self.assertEqual(payment.collected_by, self.reception_user)
        self.assertIsNotNone(payment.paid_at)

        enquiry = ContactMessage.objects.create(
            name="Visitor",
            email="visitor-reception@test.local",
            subject="Clinic timing",
            message="Is Saturday available?",
        )
        response = self.client.post(
            reverse("reception_enquiry_status", args=[enquiry.pk]), {"status": "closed"}
        )
        self.assertRedirects(response, reverse("reception_dashboard"))
        enquiry.refresh_from_db()
        self.assertEqual(enquiry.status, "closed")
        self.assertEqual(enquiry.handled_by, self.reception_user)


@override_settings(BACKUP_ENCRYPTION_KEY=TEST_BACKUP_KEY)
class PortalFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.patient_user = User.objects.create_user(
            "patient-test",
            password="StrongPass123",
            first_name="Asha",
            last_name="Nair",
        )
        cls.patient = PatientProfile.objects.create(
            user=cls.patient_user, phone="9000000000"
        )
        cls.doctor_user = User.objects.create_user(
            "doctor-test",
            password="StrongPass123",
            first_name="Meera",
            last_name="Kapoor",
        )
        cls.doctor = DoctorProfile.objects.create(
            user=cls.doctor_user, specialization="Musculoskeletal Physiotherapist"
        )
        cls.admin_user = User.objects.create_superuser(
            "admin-test", "admin@test.local", "StrongPass123"
        )
        cls.appointment = Appointment.objects.create(
            patient=cls.patient,
            doctor=cls.doctor,
            scheduled_at=timezone.now() + timedelta(days=2),
            concern="Mobility review",
            mode="clinic",
            status="confirmed",
        )
        cls.prescription = Prescription.objects.create(
            patient=cls.patient,
            doctor=cls.doctor,
            diagnosis="Back pain",
            medicines="Medicine as needed",
            instructions="Continue exercises",
        )
        cls.payment = Payment.objects.create(
            patient=cls.patient,
            appointment=cls.appointment,
            invoice_number="TEST-001",
            amount=Decimal("900.00"),
            status="pending",
        )
        cls.exercise = Exercise.objects.create(
            title="Test bridge",
            category="Core",
            description="Controlled bridge exercise",
        )

    def setUp(self):
        self.client.login(username="patient-test", password="StrongPass123")

    def test_patient_pages_render(self):
        route_names = [
            "dashboard",
            "profile",
            "book_appointment",
            "appointment_history",
            "treatment_plan",
            "exercise_videos",
            "reports",
            "progress",
            "chat",
            "video_call",
            "notifications",
            "payments",
            "community",
        ]
        for route_name in route_names:
            with self.subTest(route=route_name):
                self.assertEqual(self.client.get(reverse(route_name)).status_code, 200)

    def test_role_protected_workspaces(self):
        self.assertRedirects(
            self.client.get(reverse("doctor_dashboard")), reverse("dashboard")
        )
        self.assertRedirects(
            self.client.get(reverse("admin_dashboard")), reverse("dashboard")
        )
        self.client.logout()
        self.client.login(username="doctor-test", password="StrongPass123")
        self.assertEqual(self.client.get(reverse("doctor_dashboard")).status_code, 200)
        self.client.logout()
        self.client.login(username="admin-test", password="StrongPass123")
        self.assertEqual(self.client.get(reverse("admin_dashboard")).status_code, 200)

    def test_appointment_progress_chat_and_upload_flows(self):
        when = (timezone.localtime() + timedelta(days=4)).strftime("%Y-%m-%dT%H:%M")
        response = self.client.post(
            reverse("book_appointment"),
            {
                "doctor": self.doctor.pk,
                "scheduled_at": when,
                "mode": "clinic",
                "concern": "Follow-up assessment",
                "notes": "Pain is improving",
                "reminder_channel": "Email & WhatsApp",
            },
        )
        self.assertRedirects(response, reverse("appointment_history"))
        self.assertEqual(self.patient.appointments.count(), 2)

        response = self.client.post(
            reverse("progress"),
            {
                "pain_score": 3,
                "mobility_score": 82,
                "exercise_adherence": 90,
                "note": "Moving more comfortably today.",
            },
        )
        self.assertRedirects(response, reverse("progress"))
        self.assertTrue(
            ProgressEntry.objects.filter(patient=self.patient, pain_score=3).exists()
        )

        response = self.client.post(
            reverse("chat"),
            {"body": "Can I add another stretch?", "message_type": "text"},
        )
        self.assertRedirects(response, reverse("chat"))
        self.assertTrue(
            ChatMessage.objects.filter(
                sender=self.patient_user, recipient=self.doctor_user
            ).exists()
        )

        upload = SimpleUploadedFile(
            "report.pdf", VALID_PDF, content_type="application/pdf"
        )
        response = self.client.post(
            reverse("reports"),
            {
                "title": "Test lab report",
                "record_type": "lab",
                "record_date": timezone.localdate().isoformat(),
                "doctor_name": "Test Lab",
                "notes": "Test upload",
                "file": upload,
            },
        )
        self.assertRedirects(response, reverse("reports"))
        self.assertTrue(
            MedicalRecord.objects.filter(
                patient=self.patient, title="Test lab report"
            ).exists()
        )

    def test_pdf_and_payment_downloads(self):
        response = self.client.get(
            reverse("prescription_pdf", args=[self.prescription.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")

        response = self.client.post(
            reverse("pay_due", args=[self.payment.pk]), {"method": "upi"}
        )
        self.assertRedirects(response, reverse("payments"))
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "paid")
        self.assertTrue(self.payment.transaction_id.startswith("TXN-"))

        response = self.client.get(reverse("invoice_pdf", args=[self.payment.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")

    def test_doctor_workspace_actions(self):
        self.client.logout()
        self.client.login(username="doctor-test", password="StrongPass123")

        response = self.client.post(
            reverse("doctor_action", args=["prescription"]),
            {
                "patient": self.patient.pk,
                "diagnosis": "Improving back pain",
                "medicines": "Continue current care",
                "instructions": "Keep moving gently",
                "issued_on": timezone.localdate().isoformat(),
            },
        )
        self.assertRedirects(
            response, reverse("doctor_patient_detail", args=[self.patient.pk])
        )
        self.assertTrue(
            Prescription.objects.filter(
                patient=self.patient, diagnosis="Improving back pain"
            ).exists()
        )

        response = self.client.post(
            reverse("doctor_action", args=["exercise"]),
            {
                "patient": self.patient.pk,
                "exercise": self.exercise.pk,
                "repetitions": "10 reps × 2",
                "frequency": "Once daily",
            },
        )
        self.assertRedirects(
            response, reverse("doctor_patient_detail", args=[self.patient.pk])
        )
        self.assertTrue(
            ExerciseAssignment.objects.filter(
                patient=self.patient, exercise=self.exercise
            ).exists()
        )

        response = self.client.post(
            reverse("doctor_action", args=["treatment"]),
            {
                "patient": self.patient.pk,
                "title": "Updated recovery plan",
                "diagnosis": "Back pain",
                "goal": "Walk comfortably",
                "instructions": "Daily mobility",
                "progress": 55,
                "started_on": timezone.localdate().isoformat(),
                "next_review": (timezone.localdate() + timedelta(days=7)).isoformat(),
                "active": "on",
            },
        )
        self.assertRedirects(
            response, reverse("doctor_patient_detail", args=[self.patient.pk])
        )
        self.assertTrue(
            TreatmentPlan.objects.filter(
                patient=self.patient, title="Updated recovery plan"
            ).exists()
        )

        when = (timezone.localtime() + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M")
        response = self.client.post(
            reverse("doctor_action", args=["followup"]),
            {
                "patient": self.patient.pk,
                "scheduled_at": when,
                "mode": "clinic",
                "concern": "Doctor-scheduled review",
                "duration_minutes": 45,
                "reminder_channel": "Email & WhatsApp",
            },
        )
        self.assertRedirects(
            response, reverse("doctor_patient_detail", args=[self.patient.pk])
        )
        self.assertTrue(
            Appointment.objects.filter(
                patient=self.patient, concern="Doctor-scheduled review"
            ).exists()
        )

        response = self.client.post(
            reverse("doctor_action", args=["feedback"]),
            {
                "patient": self.patient.pk,
                "body": "Your mobility is improving well.",
            },
        )
        self.assertRedirects(
            response, reverse("doctor_patient_detail", args=[self.patient.pk])
        )
        self.assertTrue(
            ChatMessage.objects.filter(
                sender=self.doctor_user, body__contains="improving well"
            ).exists()
        )

        document = SimpleUploadedFile(
            "care-note.pdf", VALID_PDF, content_type="application/pdf"
        )
        response = self.client.post(
            reverse("doctor_action", args=["document"]),
            {
                "patient": self.patient.pk,
                "title": "Shared care note",
                "record_type": "visit",
                "record_date": timezone.localdate().isoformat(),
                "notes": "Shared after review",
                "file": document,
            },
        )
        self.assertRedirects(
            response, reverse("doctor_patient_detail", args=[self.patient.pk])
        )
        self.assertTrue(
            MedicalRecord.objects.filter(
                patient=self.patient, title="Shared care note"
            ).exists()
        )

        response = self.client.post(
            reverse("doctor_messages"),
            {
                "patient": self.patient.pk,
                "body": "Secure doctor reply from the inbox.",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            ChatMessage.objects.filter(
                sender=self.doctor_user, body__contains="Secure doctor reply"
            ).exists()
        )

        response = self.client.post(
            reverse("doctor_session", args=[self.appointment.pk]),
            {
                "status": "completed",
                "notes": "Assessment completed and home plan reviewed.",
            },
        )
        self.assertRedirects(
            response, reverse("doctor_patient_detail", args=[self.patient.pk])
        )
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, "completed")
        self.assertTrue(
            MedicalRecord.objects.filter(
                patient=self.patient, title=f"Visit note #{self.appointment.pk}"
            ).exists()
        )
        self.assertTrue(Notification.objects.filter(user=self.patient_user).exists())

    def test_admin_management_actions_and_exports(self):
        self.client.logout()
        self.client.login(username="admin-test", password="StrongPass123")

        response = self.client.post(
            reverse("admin_manage", args=["cms"]),
            {
                "content_type": "faq",
                "title": "Test FAQ",
                "summary": "A test answer",
                "body": "This is the complete answer.",
                "published": "on",
            },
        )
        self.assertRedirects(response, reverse("admin_manage", args=["cms"]))
        content = CMSContent.objects.get(title="Test FAQ")
        self.assertTrue(content.published)
        self.client.post(reverse("admin_toggle_content", args=[content.pk]))
        content.refresh_from_db()
        self.assertFalse(content.published)

        response = self.client.post(
            reverse("admin_update_appointment", args=[self.appointment.pk]),
            {"status": "cancelled"},
        )
        self.assertRedirects(response, reverse("admin_manage", args=["appointments"]))
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, "cancelled")

        response = self.client.post(
            reverse("admin_manage", args=["staff"]),
            {
                "first_name": "Billing",
                "last_name": "Officer",
                "email": "billing@test.local",
                "username": "billing-test",
                "password": "StrongPass456",
                "role": "Billing",
            },
        )
        self.assertRedirects(response, reverse("admin_manage", args=["staff"]))
        staff = User.objects.get(username="billing-test")
        self.assertTrue(staff.is_staff)

        response = self.client.post(
            reverse("admin_manage", args=["roles"]),
            {
                "staff": staff.pk,
                "role": "Content Editor",
            },
        )
        self.assertRedirects(response, reverse("admin_manage", args=["roles"]))
        self.assertTrue(staff.groups.filter(name="Content Editor").exists())

        response = self.client.post(
            reverse("admin_manage", args=["employees"]),
            {
                "first_name": "Kavya",
                "last_name": "Sharma",
                "email": "kavya.employee@test.local",
                "phone": "9000011111",
                "job_title": "Front Desk Executive",
                "department": "front_desk",
                "employment_type": "full_time",
                "shift": "morning",
                "joined_on": timezone.localdate().isoformat(),
                "monthly_salary": "28000.00",
                "emergency_contact": "9000022222",
                "address": "Bengaluru",
                "notes": "",
                "username": "kavya-employee",
                "password": "StrongPass789",
                "role": "Reception",
                "portal_access": "on",
                "active": "on",
            },
        )
        self.assertRedirects(response, reverse("admin_manage", args=["employees"]))
        employee = EmployeeProfile.objects.select_related("user").get(
            user__username="kavya-employee"
        )
        self.assertTrue(employee.portal_access)
        self.assertTrue(employee.user.is_staff)
        self.assertTrue(employee.employee_id.startswith("EMP-"))

        self.client.post(reverse("admin_employee_toggle_access", args=[employee.pk]))
        employee.refresh_from_db()
        employee.user.refresh_from_db()
        self.assertFalse(employee.portal_access)
        self.assertFalse(employee.user.is_active)

        self.client.post(reverse("admin_employee_toggle_active", args=[employee.pk]))
        employee.refresh_from_db()
        self.assertFalse(employee.active)

        response = self.client.post(
            reverse("admin_manage", args=["doctors"]),
            {
                "first_name": "Arun",
                "last_name": "Test",
                "email": "arun@test.local",
                "username": "doctor-new",
                "password": "StrongPass789",
                "specialization": "Sports Physiotherapist",
                "qualifications": "MPT",
                "experience_years": 5,
                "consultation_fee": "750.00",
            },
        )
        self.assertRedirects(response, reverse("admin_manage", args=["doctors"]))
        new_doctor = DoctorProfile.objects.get(user__username="doctor-new")
        self.client.post(reverse("admin_toggle_doctor", args=[new_doctor.pk]))
        new_doctor.refresh_from_db()
        self.assertFalse(new_doctor.available)

        for report_type in (
            "appointments",
            "payments",
            "patients",
            "doctors",
            "employees",
        ):
            response = self.client.get(reverse("admin_export", args=[report_type]))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "text/csv")
        response = self.client.post(reverse("admin_backup_download"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/octet-stream")
        self.assertNotIn(b"StrongPass123", response.content)
        archive, manifest = decrypt_and_validate_backup(response.content)
        self.assertTrue(manifest["encrypted"])
        self.assertIn("manifest.json", archive.namelist())
        archive.close()
