from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    Appointment, ChatMessage, CMSContent, DoctorProfile, Exercise,
    ExerciseAssignment, MedicalRecord, Notification, PatientProfile, Payment,
    Prescription, ProgressEntry, TreatmentPlan,
)


class PortalFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.patient_user = User.objects.create_user("patient-test", password="StrongPass123", first_name="Asha", last_name="Nair")
        cls.patient = PatientProfile.objects.create(user=cls.patient_user, phone="9000000000")
        cls.doctor_user = User.objects.create_user("doctor-test", password="StrongPass123", first_name="Meera", last_name="Kapoor")
        cls.doctor = DoctorProfile.objects.create(user=cls.doctor_user, specialization="Musculoskeletal Physiotherapist")
        cls.admin_user = User.objects.create_superuser("admin-test", "admin@test.local", "StrongPass123")
        cls.appointment = Appointment.objects.create(
            patient=cls.patient, doctor=cls.doctor, scheduled_at=timezone.now() + timedelta(days=2),
            concern="Mobility review", mode="clinic", status="confirmed",
        )
        cls.prescription = Prescription.objects.create(
            patient=cls.patient, doctor=cls.doctor, diagnosis="Back pain",
            medicines="Medicine as needed", instructions="Continue exercises",
        )
        cls.payment = Payment.objects.create(
            patient=cls.patient, appointment=cls.appointment, invoice_number="TEST-001",
            amount=Decimal("900.00"), status="pending",
        )
        cls.exercise = Exercise.objects.create(title="Test bridge", category="Core", description="Controlled bridge exercise")

    def setUp(self):
        self.client.login(username="patient-test", password="StrongPass123")

    def test_patient_pages_render(self):
        route_names = [
            "dashboard", "profile", "book_appointment", "appointment_history",
            "treatment_plan", "exercise_videos", "reports", "progress", "chat",
            "video_call", "notifications", "payments", "community",
        ]
        for route_name in route_names:
            with self.subTest(route=route_name):
                self.assertEqual(self.client.get(reverse(route_name)).status_code, 200)

    def test_role_protected_workspaces(self):
        self.assertRedirects(self.client.get(reverse("doctor_dashboard")), reverse("dashboard"))
        self.assertRedirects(self.client.get(reverse("admin_dashboard")), reverse("dashboard"))
        self.client.logout()
        self.client.login(username="doctor-test", password="StrongPass123")
        self.assertEqual(self.client.get(reverse("doctor_dashboard")).status_code, 200)
        self.client.logout()
        self.client.login(username="admin-test", password="StrongPass123")
        self.assertEqual(self.client.get(reverse("admin_dashboard")).status_code, 200)

    def test_appointment_progress_chat_and_upload_flows(self):
        when = (timezone.localtime() + timedelta(days=4)).strftime("%Y-%m-%dT%H:%M")
        response = self.client.post(reverse("book_appointment"), {
            "doctor": self.doctor.pk, "scheduled_at": when, "mode": "video",
            "concern": "Follow-up assessment", "notes": "Pain is improving",
            "reminder_channel": "Email & WhatsApp",
        })
        self.assertRedirects(response, reverse("appointment_history"))
        self.assertEqual(self.patient.appointments.count(), 2)

        response = self.client.post(reverse("progress"), {
            "pain_score": 3, "mobility_score": 82, "exercise_adherence": 90,
            "note": "Moving more comfortably today.",
        })
        self.assertRedirects(response, reverse("progress"))
        self.assertTrue(ProgressEntry.objects.filter(patient=self.patient, pain_score=3).exists())

        response = self.client.post(reverse("chat"), {"body": "Can I add another stretch?", "message_type": "text"})
        self.assertRedirects(response, reverse("chat"))
        self.assertTrue(ChatMessage.objects.filter(sender=self.patient_user, recipient=self.doctor_user).exists())

        upload = SimpleUploadedFile("report.pdf", b"test medical report", content_type="application/pdf")
        response = self.client.post(reverse("reports"), {
            "title": "Test lab report", "record_type": "lab",
            "record_date": timezone.localdate().isoformat(), "doctor_name": "Test Lab",
            "notes": "Test upload", "file": upload,
        })
        self.assertRedirects(response, reverse("reports"))
        self.assertTrue(MedicalRecord.objects.filter(patient=self.patient, title="Test lab report").exists())

    def test_pdf_and_payment_downloads(self):
        response = self.client.get(reverse("prescription_pdf", args=[self.prescription.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")

        response = self.client.post(reverse("pay_due", args=[self.payment.pk]), {"method": "upi"})
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

        response = self.client.post(reverse("doctor_action", args=["prescription"]), {
            "patient": self.patient.pk, "diagnosis": "Improving back pain",
            "medicines": "Continue current care", "instructions": "Keep moving gently",
            "issued_on": timezone.localdate().isoformat(),
        })
        self.assertRedirects(response, reverse("doctor_patient_detail", args=[self.patient.pk]))
        self.assertTrue(Prescription.objects.filter(patient=self.patient, diagnosis="Improving back pain").exists())

        response = self.client.post(reverse("doctor_action", args=["exercise"]), {
            "patient": self.patient.pk, "exercise": self.exercise.pk,
            "repetitions": "10 reps × 2", "frequency": "Once daily",
        })
        self.assertRedirects(response, reverse("doctor_patient_detail", args=[self.patient.pk]))
        self.assertTrue(ExerciseAssignment.objects.filter(patient=self.patient, exercise=self.exercise).exists())

        response = self.client.post(reverse("doctor_action", args=["treatment"]), {
            "patient": self.patient.pk, "title": "Updated recovery plan", "diagnosis": "Back pain",
            "goal": "Walk comfortably", "instructions": "Daily mobility", "progress": 55,
            "started_on": timezone.localdate().isoformat(),
            "next_review": (timezone.localdate() + timedelta(days=7)).isoformat(), "active": "on",
        })
        self.assertRedirects(response, reverse("doctor_patient_detail", args=[self.patient.pk]))
        self.assertTrue(TreatmentPlan.objects.filter(patient=self.patient, title="Updated recovery plan").exists())

        when = (timezone.localtime() + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M")
        response = self.client.post(reverse("doctor_action", args=["followup"]), {
            "patient": self.patient.pk, "scheduled_at": when, "mode": "video",
            "concern": "Doctor-scheduled review", "duration_minutes": 45,
            "reminder_channel": "Email & WhatsApp",
        })
        self.assertRedirects(response, reverse("doctor_patient_detail", args=[self.patient.pk]))
        self.assertTrue(Appointment.objects.filter(patient=self.patient, concern="Doctor-scheduled review").exists())

        response = self.client.post(reverse("doctor_action", args=["feedback"]), {
            "patient": self.patient.pk, "body": "Your mobility is improving well.",
        })
        self.assertRedirects(response, reverse("doctor_patient_detail", args=[self.patient.pk]))
        self.assertTrue(ChatMessage.objects.filter(sender=self.doctor_user, body__contains="improving well").exists())

        document = SimpleUploadedFile("care-note.pdf", b"doctor care document", content_type="application/pdf")
        response = self.client.post(reverse("doctor_action", args=["document"]), {
            "patient": self.patient.pk, "title": "Shared care note", "record_type": "visit",
            "record_date": timezone.localdate().isoformat(), "notes": "Shared after review", "file": document,
        })
        self.assertRedirects(response, reverse("doctor_patient_detail", args=[self.patient.pk]))
        self.assertTrue(MedicalRecord.objects.filter(patient=self.patient, title="Shared care note").exists())

        response = self.client.post(reverse("doctor_messages"), {
            "patient": self.patient.pk, "body": "Secure doctor reply from the inbox.",
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(ChatMessage.objects.filter(sender=self.doctor_user, body__contains="Secure doctor reply").exists())

        response = self.client.post(reverse("doctor_session", args=[self.appointment.pk]), {
            "status": "completed", "notes": "Assessment completed and home plan reviewed.",
        })
        self.assertRedirects(response, reverse("doctor_patient_detail", args=[self.patient.pk]))
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, "completed")
        self.assertTrue(MedicalRecord.objects.filter(patient=self.patient, title=f"Visit note #{self.appointment.pk}").exists())
        self.assertTrue(Notification.objects.filter(user=self.patient_user).exists())

    def test_admin_management_actions_and_exports(self):
        self.client.logout()
        self.client.login(username="admin-test", password="StrongPass123")

        response = self.client.post(reverse("admin_manage", args=["cms"]), {
            "content_type": "faq", "title": "Test FAQ", "summary": "A test answer",
            "body": "This is the complete answer.", "published": "on",
        })
        self.assertRedirects(response, reverse("admin_manage", args=["cms"]))
        content = CMSContent.objects.get(title="Test FAQ")
        self.assertTrue(content.published)
        self.client.post(reverse("admin_toggle_content", args=[content.pk]))
        content.refresh_from_db()
        self.assertFalse(content.published)

        response = self.client.post(reverse("admin_update_appointment", args=[self.appointment.pk]), {"status": "cancelled"})
        self.assertRedirects(response, reverse("admin_manage", args=["appointments"]))
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, "cancelled")

        response = self.client.post(reverse("admin_manage", args=["staff"]), {
            "first_name": "Billing", "last_name": "Officer", "email": "billing@test.local",
            "username": "billing-test", "password": "StrongPass456", "role": "Billing",
        })
        self.assertRedirects(response, reverse("admin_manage", args=["staff"]))
        staff = User.objects.get(username="billing-test")
        self.assertTrue(staff.is_staff)

        response = self.client.post(reverse("admin_manage", args=["roles"]), {
            "staff": staff.pk, "role": "Content Editor",
        })
        self.assertRedirects(response, reverse("admin_manage", args=["roles"]))
        self.assertTrue(staff.groups.filter(name="Content Editor").exists())

        response = self.client.post(reverse("admin_manage", args=["doctors"]), {
            "first_name": "Arun", "last_name": "Test", "email": "arun@test.local",
            "username": "doctor-new", "password": "StrongPass789",
            "specialization": "Sports Physiotherapist", "qualifications": "MPT",
            "experience_years": 5, "consultation_fee": "750.00",
        })
        self.assertRedirects(response, reverse("admin_manage", args=["doctors"]))
        new_doctor = DoctorProfile.objects.get(user__username="doctor-new")
        self.client.post(reverse("admin_toggle_doctor", args=[new_doctor.pk]))
        new_doctor.refresh_from_db()
        self.assertFalse(new_doctor.available)

        for report_type in ("appointments", "payments", "patients", "doctors"):
            response = self.client.get(reverse("admin_export", args=[report_type]))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "text/csv")
        response = self.client.get(reverse("admin_backup_download"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
