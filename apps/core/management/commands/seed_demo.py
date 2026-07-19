from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.core.models import (
    Appointment,
    ChatMessage,
    CMSContent,
    DoctorProfile,
    EmployeeProfile,
    Exercise,
    ExerciseAssignment,
    Feedback,
    MedicalRecord,
    Notification,
    PatientProfile,
    Payment,
    Prescription,
    ProgressEntry,
    TreatmentPlan,
)


class Command(BaseCommand):
    help = "Create realistic, idempotent demo data for the PhysioCare portal"

    def handle(self, *args, **options):
        patient_user, _ = User.objects.get_or_create(
            username="patient",
            defaults={
                "first_name": "Anita",
                "last_name": "Sharma",
                "email": "anita@example.com",
            },
        )
        patient_user.set_password("Care@123")
        patient_user.save()
        patient, _ = PatientProfile.objects.get_or_create(
            user=patient_user,
            defaults={
                "phone": "+91 98765 43210",
                "date_of_birth": date(1987, 4, 18),
                "gender": "Female",
                "blood_group": "B+",
                "address": "Indiranagar, Bengaluru",
                "emergency_contact": "Raj Sharma · +91 98765 40000",
                "conditions": "Mechanical lower-back pain; occasional stiffness after prolonged sitting",
                "allergies": "No known drug allergies",
                "surgeries": "Appendectomy (2013)",
            },
        )

        doctor_data = [
            (
                "drmeera",
                "Meera",
                "Kapoor",
                "Musculoskeletal Physiotherapist",
                "MPT, Orthopaedics",
                12,
                "4.9",
            ),
            (
                "drarjun",
                "Arjun",
                "Rao",
                "Sports Rehabilitation Specialist",
                "MPT, Sports Medicine",
                9,
                "4.8",
            ),
            (
                "drnisha",
                "Nisha",
                "Shah",
                "Neurological Physiotherapist",
                "MPT, Neurology",
                11,
                "4.9",
            ),
        ]
        doctors = []
        for (
            username,
            first,
            last,
            specialty,
            qualifications,
            years,
            rating,
        ) in doctor_data:
            user, _ = User.objects.get_or_create(
                username=username,
                defaults={
                    "first_name": first,
                    "last_name": last,
                    "email": f"{username}@physiocare.in",
                },
            )
            user.set_password("Care@123")
            user.save()
            doctor, _ = DoctorProfile.objects.get_or_create(
                user=user,
                defaults={
                    "specialization": specialty,
                    "qualifications": qualifications,
                    "experience_years": years,
                    "rating": Decimal(rating),
                    "bio": "Patient-focused physiotherapist committed to clear guidance and evidence-based recovery.",
                    "consultation_fee": Decimal("900.00"),
                },
            )
            doctors.append(doctor)

        admin, _ = User.objects.get_or_create(
            username="admin",
            defaults={
                "first_name": "Clinic",
                "last_name": "Admin",
                "email": "admin@physiocare.in",
                "is_staff": True,
                "is_superuser": True,
            },
        )
        admin.is_staff = True
        admin.is_superuser = True
        admin.set_password("Care@123")
        admin.save()

        reception_user, _ = User.objects.get_or_create(
            username="reception",
            defaults={
                "first_name": "Priya",
                "last_name": "Front Desk",
                "email": "reception@physiocare.in",
            },
        )
        reception_user.is_staff = True
        reception_user.set_password("Care@123")
        reception_user.save()
        reception_group, _ = Group.objects.get_or_create(name="Reception")
        reception_user.groups.clear()
        reception_user.groups.add(reception_group)
        EmployeeProfile.objects.update_or_create(
            user=reception_user,
            defaults={
                "phone": "+91 80012 34567",
                "job_title": "Senior Reception Executive",
                "department": "front_desk",
                "employment_type": "full_time",
                "shift": "morning",
                "joined_on": timezone.localdate() - timedelta(days=240),
                "emergency_contact": "+91 90000 45678",
                "portal_access": True,
                "active": True,
            },
        )

        second_user, _ = User.objects.get_or_create(
            username="rahul",
            defaults={
                "first_name": "Rahul",
                "last_name": "Menon",
                "email": "rahul@example.com",
            },
        )
        second_user.set_password("Care@123")
        second_user.save()
        second_patient, _ = PatientProfile.objects.get_or_create(
            user=second_user,
            defaults={
                "phone": "+91 90000 11223",
                "conditions": "Post-operative knee rehabilitation",
            },
        )

        today = timezone.localdate()

        def aware(day, hour, minute=0):
            return timezone.make_aware(datetime.combine(day, time(hour, minute)))

        active_plan, _ = TreatmentPlan.objects.get_or_create(
            patient=patient,
            doctor=doctors[0],
            title="Lower-back mobility & strength",
            defaults={
                "diagnosis": "Mechanical lower-back pain with reduced hip mobility",
                "goal": "Move comfortably through the workday and return to 30-minute morning walks without pain.",
                "instructions": "Complete your mobility routine once each morning.\nTake a two-minute movement break every 45 minutes while working.\nUse heat for 10 minutes if stiffness increases, unless your therapist advises otherwise.",
                "progress": 68,
                "started_on": today - timedelta(days=35),
                "next_review": today + timedelta(days=7),
            },
        )
        TreatmentPlan.objects.get_or_create(
            patient=patient,
            doctor=doctors[1],
            title="Right shoulder recovery",
            defaults={
                "diagnosis": "Mild rotator cuff strain",
                "goal": "Restore pain-free overhead movement.",
                "instructions": "Completed with full range of motion.",
                "progress": 100,
                "started_on": today - timedelta(days=340),
                "next_review": today - timedelta(days=280),
                "active": False,
            },
        )

        exercise_data = [
            (
                "Cat–cow mobility",
                "Back mobility",
                "Move slowly between comfortable spinal flexion and extension while breathing steadily.",
                8,
                "easy",
            ),
            (
                "Supported bridge",
                "Core strength",
                "Lift your hips gently while keeping your ribs relaxed and both feet grounded.",
                10,
                "moderate",
            ),
            (
                "Hip flexor stretch",
                "Hip mobility",
                "Use a supported half-kneeling position and keep the movement small and controlled.",
                6,
                "easy",
            ),
            (
                "Bird dog control",
                "Spinal stability",
                "Reach the opposite arm and leg without allowing your trunk to rotate.",
                9,
                "moderate",
            ),
            (
                "Neck rotation reset",
                "Neck mobility",
                "Turn only within a comfortable range and keep both shoulders relaxed.",
                5,
                "easy",
            ),
        ]
        exercises = []
        for title, category, description, duration, difficulty in exercise_data:
            item, _ = Exercise.objects.get_or_create(
                title=title,
                defaults={
                    "category": category,
                    "description": description,
                    "duration_minutes": duration,
                    "difficulty": difficulty,
                },
            )
            exercises.append(item)
        for index, exercise in enumerate(exercises[:4]):
            ExerciseAssignment.objects.get_or_create(
                patient=patient,
                exercise=exercise,
                assigned_by=doctors[0],
                defaults={
                    "repetitions": [
                        "10 reps × 2 sets",
                        "8 reps × 2 sets",
                        "30 sec × 3 each side",
                        "6 reps × 2 each side",
                    ][index],
                    "frequency": "Once daily",
                    "completed_today": index < 2,
                },
            )

        appointments = [
            (
                patient,
                doctors[0],
                aware(today, min(timezone.localtime().hour + 1, 20), 30),
                "Progress review and manual therapy",
                "clinic",
                "confirmed",
            ),
            (
                patient,
                doctors[0],
                aware(today + timedelta(days=5), 16, 30),
                "Home programme review",
                "video",
                "confirmed",
            ),
            (
                patient,
                doctors[0],
                aware(today - timedelta(days=7), 11, 0),
                "Mobility reassessment",
                "clinic",
                "completed",
            ),
            (
                patient,
                doctors[1],
                aware(today - timedelta(days=310), 10, 30),
                "Shoulder rehabilitation review",
                "clinic",
                "completed",
            ),
            (
                second_patient,
                doctors[0],
                aware(today, min(timezone.localtime().hour + 2, 21), 0),
                "Knee rehabilitation review",
                "clinic",
                "confirmed",
            ),
        ]
        created_appointments = []
        for pat, doc, when, concern, mode, status in appointments:
            item, _ = Appointment.objects.get_or_create(
                patient=pat,
                doctor=doc,
                scheduled_at=when,
                defaults={
                    "concern": concern,
                    "mode": mode,
                    "status": status,
                    "duration_minutes": 45,
                },
            )
            created_appointments.append(item)

        progress_data = [
            (42, 7, 48, 55),
            (35, 6, 56, 62),
            (28, 5, 63, 70),
            (21, 5, 68, 76),
            (14, 4, 74, 82),
            (7, 3, 81, 90),
            (0, 3, 84, 92),
        ]
        for days, pain, mobility, adherence in progress_data:
            ProgressEntry.objects.get_or_create(
                patient=patient,
                recorded_on=today - timedelta(days=days),
                defaults={
                    "pain_score": pain,
                    "mobility_score": mobility,
                    "exercise_adherence": adherence,
                    "note": "Movement felt easier and I was able to sit more comfortably during work."
                    if days < 14
                    else "Completed the planned routine and noted gradual improvement.",
                },
            )

        Prescription.objects.get_or_create(
            patient=patient,
            doctor=doctors[0],
            diagnosis="Mechanical lower-back pain",
            issued_on=today - timedelta(days=7),
            defaults={
                "medicines": "Paracetamol 500 mg — only if needed, after food\nTopical pain-relief gel — thin layer, up to twice daily",
                "instructions": "Continue prescribed exercises. Avoid prolonged bed rest. Contact the clinic if symptoms change suddenly.",
            },
        )
        Prescription.objects.get_or_create(
            patient=patient,
            doctor=doctors[1],
            diagnosis="Right shoulder strain",
            issued_on=today - timedelta(days=300),
            defaults={
                "medicines": "Topical pain-relief gel — as advised",
                "instructions": "Gradual return to overhead activity.",
            },
        )
        MedicalRecord.objects.get_or_create(
            patient=patient,
            title="Lumbar spine X-ray",
            record_type="scan",
            record_date=today - timedelta(days=40),
            defaults={
                "doctor_name": "City Diagnostics",
                "notes": "No acute bony abnormality.",
            },
        )
        MedicalRecord.objects.get_or_create(
            patient=patient,
            title="Initial physiotherapy assessment",
            record_type="visit",
            record_date=today - timedelta(days=35),
            defaults={
                "doctor_name": "Dr. Meera Kapoor",
                "notes": "Mobility and strength baseline recorded.",
            },
        )
        MedicalRecord.objects.get_or_create(
            patient=patient,
            title="Fitness-to-work certificate",
            record_type="certificate",
            record_date=today - timedelta(days=20),
            defaults={"doctor_name": "Dr. Meera Kapoor"},
        )

        notification_data = [
            (
                "Appointment tomorrow",
                "Your session with Dr. Meera Kapoor is confirmed. Please arrive 10 minutes early.",
                "appointment",
                "/appointments/",
            ),
            (
                "Time for your mobility routine",
                "Your gentle back-mobility exercises are ready for today.",
                "exercise",
                "/exercises/",
            ),
            (
                "Medicine reminder",
                "Take medicine only as prescribed and after food.",
                "medicine",
                "/reports/",
            ),
            (
                "Progress check-in",
                "Tell us how your pain and movement feel today.",
                "followup",
                "/progress/",
            ),
            (
                "Invoice due soon",
                "Invoice PC-INV-1024 is due this week.",
                "payment",
                "/payments/",
            ),
        ]
        for title, body, kind, url in notification_data:
            Notification.objects.get_or_create(
                user=patient_user,
                title=title,
                defaults={
                    "message": body,
                    "notification_type": kind,
                    "action_url": url,
                },
            )

        Payment.objects.get_or_create(
            patient=patient,
            invoice_number="PC-INV-1024",
            defaults={
                "appointment": created_appointments[0],
                "amount": Decimal("900.00"),
                "method": "upi",
                "status": "pending",
                "issued_on": today,
                "due_on": today + timedelta(days=3),
            },
        )
        Payment.objects.get_or_create(
            patient=patient,
            invoice_number="PC-INV-1012",
            defaults={
                "appointment": created_appointments[2],
                "amount": Decimal("900.00"),
                "method": "card",
                "status": "paid",
                "transaction_id": "TXN-7F3A92C1DE",
                "issued_on": today - timedelta(days=7),
            },
        )
        Payment.objects.get_or_create(
            patient=patient,
            invoice_number="PC-INV-0874",
            defaults={
                "amount": Decimal("800.00"),
                "method": "upi",
                "status": "paid",
                "transaction_id": "TXN-19BD72A4EF",
                "issued_on": today - timedelta(days=300),
            },
        )

        ChatMessage.objects.get_or_create(
            sender=doctors[0].user,
            recipient=patient_user,
            body="Hello Anita, I reviewed your latest progress update. Your mobility is improving well. Continue the current routine and let me know if the bridge exercise causes discomfort.",
        )
        ChatMessage.objects.get_or_create(
            sender=patient_user,
            recipient=doctors[0].user,
            body="Thank you, doctor. The bridge feels comfortable now. I still notice some stiffness after long meetings—should I add another stretch?",
        )
        ChatMessage.objects.get_or_create(
            sender=doctors[0].user,
            recipient=patient_user,
            body="A short hip-flexor stretch after those meetings would be helpful. Keep it gentle, 30 seconds each side. I’ve added it to your programme.",
        )
        ChatMessage.objects.get_or_create(
            sender=second_user,
            recipient=doctors[0].user,
            body="I uploaded my latest scan. Could you please review it before today's appointment?",
        )

        Feedback.objects.get_or_create(
            patient=patient,
            doctor=doctors[0],
            review="The clear explanations and gentle reminders made recovery feel manageable. I always knew what to do next.",
            defaults={"rating": 5},
        )
        Feedback.objects.get_or_create(
            patient=second_patient,
            doctor=doctors[0],
            review="Thoughtful care and a very practical home programme. I feel confident moving again.",
            defaults={"rating": 5},
        )

        CMSContent.objects.get_or_create(
            title="Five gentle habits for lower-back stiffness",
            defaults={
                "content_type": "blog",
                "summary": "Simple movement and posture habits that reduce strain during long working days.",
                "body": "Change position regularly rather than searching for one perfect posture. Take a two-minute movement break every 45 minutes, keep both feet supported, and use a small cushion if your lower back feels tired. Gentle walking and your assigned mobility routine are usually more helpful than prolonged rest.",
                "published": True,
                "created_by": admin,
            },
        )
        CMSContent.objects.get_or_create(
            title="Can I reschedule an appointment online?",
            defaults={
                "content_type": "faq",
                "summary": "Appointment rescheduling guidance.",
                "body": "Yes. Open Appointments, choose your upcoming session, and select Reschedule. Your therapist and reminder schedule update automatically.",
                "published": True,
                "created_by": admin,
            },
        )
        CMSContent.objects.get_or_create(
            title="Clinic hours extended on Saturdays",
            defaults={
                "content_type": "announcement",
                "summary": "Saturday appointments are now available until 6:00 PM.",
                "body": "You can book Saturday in-clinic consultations until 6:00 PM through the appointment portal.",
                "published": True,
                "created_by": admin,
            },
        )

        self.stdout.write(self.style.SUCCESS("PhysioCare demo data is ready."))
        self.stdout.write("Patient login: patient / Care@123")
        self.stdout.write("Doctor login: drmeera / Care@123")
        self.stdout.write("Reception login: reception / Care@123")
        self.stdout.write("Admin login: admin / Care@123")
