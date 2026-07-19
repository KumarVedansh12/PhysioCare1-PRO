from django.conf import settings

from .access import (
    can_use_admin_portal,
    has_capability,
    is_receptionist,
    portal_home_url,
    portal_role_label,
)
from .backups import backup_encryption_ready


def portal_context(request):
    unread_count = 0
    reception_access = False
    if request.user.is_authenticated:
        unread_count = request.user.portal_notifications.filter(is_read=False).count()
        reception_access = is_receptionist(request.user)
    return {
        "unread_count": unread_count,
        "is_receptionist": reception_access,
        "can_use_admin_portal": can_use_admin_portal(request.user),
        "can_admin_dashboard": has_capability(request.user, "admin.dashboard"),
        "can_manage_doctors": has_capability(request.user, "admin.doctors"),
        "can_manage_patients": has_capability(request.user, "admin.patients"),
        "can_manage_appointments": has_capability(request.user, "admin.appointments"),
        "can_manage_payments": has_capability(request.user, "admin.payments"),
        "can_manage_employees": has_capability(request.user, "admin.employees"),
        "can_manage_roles": has_capability(request.user, "admin.roles"),
        "can_manage_cms": has_capability(request.user, "admin.cms"),
        "can_manage_backup": has_capability(request.user, "admin.backup"),
        "backup_encryption_ready": backup_encryption_ready(),
        "portal_home_url": portal_home_url(request.user)
        if request.user.is_authenticated
        else "",
        "portal_role_label": portal_role_label(request.user)
        if request.user.is_authenticated
        else "",
        "support_email": settings.CONTACT_EMAIL,
    }
