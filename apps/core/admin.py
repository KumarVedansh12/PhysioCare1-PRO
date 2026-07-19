from django.contrib.admin import AdminSite
from django.contrib.auth.admin import GroupAdmin, UserAdmin
from django.contrib.auth.models import Group, User
from .models import (
    Appointment,
    ChatMessage,
    CMSContent,
    ContactMessage,
    DoctorProfile,
    EmployeeProfile,
    EmailDelivery,
    EmailOTP,
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


class PhysioCareAdminSite(AdminSite):
    site_header = "PhysioCare Administration"
    site_title = "PhysioCare Admin"
    index_title = "Advanced system administration"

    def has_permission(self, request):
        return bool(request.user.is_active and request.user.is_superuser)


clinic_admin_site = PhysioCareAdminSite(name="physiocare_admin")
clinic_admin_site.register(User, UserAdmin)
clinic_admin_site.register(Group, GroupAdmin)

for model in [
    PatientProfile,
    DoctorProfile,
    EmployeeProfile,
    Appointment,
    TreatmentPlan,
    Exercise,
    ExerciseAssignment,
    ProgressEntry,
    Prescription,
    MedicalRecord,
    Notification,
    ChatMessage,
    Payment,
    Feedback,
    CMSContent,
    EmailOTP,
    ContactMessage,
    EmailDelivery,
]:
    clinic_admin_site.register(model)
