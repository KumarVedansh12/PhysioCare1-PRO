from django.urls import path, reverse_lazy
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path("healthz/", views.health_check, name="health_check"),
    path("", views.home, name="home"),
    path("register/", views.register_view, name="register"),
    path("verify-email/", views.verify_email, name="verify_email"),
    path(
        "verify-email/resend/",
        views.resend_verification_email,
        name="resend_verification_email",
    ),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path(
        "password-reset/",
        views.PortalPasswordResetView.as_view(),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="accounts/password_reset_done.html"
        ),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="accounts/password_reset_confirm.html",
            success_url=reverse_lazy("password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),
    path(
        "reset/complete/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="accounts/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
    path(
        "activate/<uidb64>/<token>/",
        views.activate_patient_account,
        name="activate_patient_account",
    ),
    path("contact/", views.contact, name="contact"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("profile/", views.profile_view, name="profile"),
    path("appointments/book/", views.book_appointment, name="book_appointment"),
    path("appointments/", views.appointment_history, name="appointment_history"),
    path(
        "appointments/<int:pk>/reschedule/",
        views.reschedule_appointment,
        name="reschedule_appointment",
    ),
    path(
        "appointments/<int:pk>/cancel/",
        views.cancel_appointment,
        name="cancel_appointment",
    ),
    path("treatment/", views.treatment_plan, name="treatment_plan"),
    path("exercises/", views.exercise_library, name="exercise_videos"),
    path(
        "exercises/<int:pk>/complete/",
        views.complete_exercise,
        name="complete_exercise",
    ),
    path("reports/", views.reports, name="reports"),
    path(
        "reports/<int:pk>/download/",
        views.medical_record_download,
        name="medical_record_download",
    ),
    path(
        "prescriptions/<int:pk>/download/",
        views.prescription_pdf,
        name="prescription_pdf",
    ),
    path("progress/", views.progress, name="progress"),
    path("chat/", views.chat, name="chat"),
    path(
        "chat/attachments/<int:pk>/download/",
        views.chat_attachment_download,
        name="chat_attachment_download",
    ),
    path("consultation/", views.video_consultation, name="video_call"),
    path("follow-up/", views.follow_up, name="follow_up"),
    path("notifications/", views.notifications_view, name="notifications"),
    path(
        "notifications/read-all/",
        views.mark_notifications_read,
        name="notifications_read_all",
    ),
    path("payments/", views.payments, name="payments"),
    path("payments/<int:pk>/pay/", views.pay_due, name="pay_due"),
    path("payments/<int:pk>/invoice/", views.invoice_pdf, name="invoice_pdf"),
    path("community/", views.community, name="community"),
    path("doctor/", views.doctor_dashboard, name="doctor_dashboard"),
    path("doctor/calendar/", views.doctor_calendar, name="doctor_calendar"),
    path("doctor/messages/", views.doctor_messages, name="doctor_messages"),
    path(
        "doctor/patients/<int:pk>/",
        views.doctor_patient_detail,
        name="doctor_patient_detail",
    ),
    path("doctor/session/<int:pk>/", views.doctor_session, name="doctor_session"),
    path("doctor/action/<slug:action>/", views.doctor_action, name="doctor_action"),
    path("reception/", views.reception_dashboard, name="reception_dashboard"),
    path(
        "reception/patients/new/",
        views.reception_patient_new,
        name="reception_patient_new",
    ),
    path(
        "reception/patients/<int:pk>/",
        views.reception_patient_detail,
        name="reception_patient_detail",
    ),
    path(
        "reception/patients/<int:pk>/invite/",
        views.reception_patient_invite,
        name="reception_patient_invite",
    ),
    path(
        "reception/appointments/new/",
        views.reception_appointment_new,
        name="reception_appointment_new",
    ),
    path(
        "reception/appointments/<int:pk>/edit/",
        views.reception_appointment_edit,
        name="reception_appointment_edit",
    ),
    path(
        "reception/appointments/<int:pk>/status/",
        views.reception_appointment_status,
        name="reception_appointment_status",
    ),
    path(
        "reception/payments/<int:pk>/collect/",
        views.reception_payment_collect,
        name="reception_payment_collect",
    ),
    path(
        "reception/payments/<int:pk>/invoice/",
        views.reception_invoice,
        name="reception_invoice",
    ),
    path(
        "reception/enquiries/<int:pk>/status/",
        views.reception_enquiry_status,
        name="reception_enquiry_status",
    ),
    path("clinic-admin/", views.admin_dashboard, name="admin_dashboard"),
    path(
        "clinic-admin/manage/<slug:section>/", views.admin_manage, name="admin_manage"
    ),
    path(
        "clinic-admin/export/<slug:report_type>/",
        views.admin_export,
        name="admin_export",
    ),
    path(
        "clinic-admin/doctor/<int:pk>/toggle/",
        views.admin_toggle_doctor,
        name="admin_toggle_doctor",
    ),
    path(
        "clinic-admin/patient/<int:pk>/toggle/",
        views.admin_toggle_patient,
        name="admin_toggle_patient",
    ),
    path(
        "clinic-admin/employee/<int:pk>/edit/",
        views.admin_employee_edit,
        name="admin_employee_edit",
    ),
    path(
        "clinic-admin/employee/<int:pk>/toggle-active/",
        views.admin_employee_toggle_active,
        name="admin_employee_toggle_active",
    ),
    path(
        "clinic-admin/employee/<int:pk>/toggle-access/",
        views.admin_employee_toggle_access,
        name="admin_employee_toggle_access",
    ),
    path(
        "clinic-admin/appointment/<int:pk>/update/",
        views.admin_update_appointment,
        name="admin_update_appointment",
    ),
    path(
        "clinic-admin/content/<int:pk>/toggle/",
        views.admin_toggle_content,
        name="admin_toggle_content",
    ),
    path(
        "clinic-admin/content/<int:pk>/delete/",
        views.admin_delete_content,
        name="admin_delete_content",
    ),
    path(
        "clinic-admin/backup/download/",
        views.admin_backup_download,
        name="admin_backup_download",
    ),
]
