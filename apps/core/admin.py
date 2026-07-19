from django.contrib import admin
from .models import (
    Appointment, ChatMessage, CMSContent, DoctorProfile, Exercise, ExerciseAssignment,
    Feedback, MedicalRecord, Notification, PatientProfile, Payment,
    Prescription, ProgressEntry, TreatmentPlan,
)

for model in [PatientProfile, DoctorProfile, Appointment, TreatmentPlan, Exercise,
              ExerciseAssignment, ProgressEntry, Prescription, MedicalRecord,
              Notification, ChatMessage, Payment, Feedback, CMSContent]:
    admin.site.register(model)

admin.site.site_header = "PhysioCare Administration"
admin.site.site_title = "PhysioCare Admin"
