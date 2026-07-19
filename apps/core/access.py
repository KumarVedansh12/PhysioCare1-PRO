"""Central role and capability policy for the clinic portals."""

from django.urls import reverse


ROLE_CLINIC_MANAGER = "Clinic Manager"
ROLE_RECEPTION = "Reception"
ROLE_BILLING = "Billing"
ROLE_CONTENT_EDITOR = "Content Editor"

ROLE_CAPABILITIES = {
    ROLE_CLINIC_MANAGER: {
        "admin.dashboard",
        "admin.doctors",
        "admin.patients",
        "admin.appointments",
        "admin.payments",
        "admin.employees",
        "admin.staff",
        "admin.roles",
        "admin.cms",
        "admin.export.appointments",
        "admin.export.payments",
        "admin.export.patients",
        "admin.export.doctors",
        "admin.export.employees",
    },
    ROLE_RECEPTION: {"reception.workspace"},
    ROLE_BILLING: {"admin.payments", "admin.export.payments"},
    ROLE_CONTENT_EDITOR: {"admin.cms"},
}

ADMIN_SECTION_CAPABILITIES = {
    "doctors": "admin.doctors",
    "patients": "admin.patients",
    "appointments": "admin.appointments",
    "payments": "admin.payments",
    "employees": "admin.employees",
    "staff": "admin.staff",
    "roles": "admin.roles",
    "cms": "admin.cms",
    "backup": "admin.backup",
}


def _role_names(user):
    if not getattr(user, "is_authenticated", False):
        return set()
    cached = getattr(user, "_physiocare_role_names", None)
    if cached is None:
        cached = set(user.groups.values_list("name", flat=True))
        user._physiocare_role_names = cached
    return cached


def has_role(user, role):
    return bool(
        getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", False)
        and getattr(user, "is_staff", False)
        and role in _role_names(user)
    )


def has_capability(user, capability):
    if not getattr(user, "is_authenticated", False) or not getattr(
        user, "is_active", False
    ):
        return False
    if getattr(user, "is_superuser", False):
        return True
    if not getattr(user, "is_staff", False):
        return False
    return any(
        capability in ROLE_CAPABILITIES.get(role, set()) for role in _role_names(user)
    )


def is_receptionist(user):
    return has_role(user, ROLE_RECEPTION)


def can_use_admin_portal(user):
    return any(
        has_capability(user, capability)
        for capability in (
            "admin.dashboard",
            "admin.payments",
            "admin.cms",
            "admin.backup",
        )
    )


def portal_home_url(user):
    if is_receptionist(user):
        return reverse("reception_dashboard")
    if hasattr(user, "doctor_profile"):
        return reverse("doctor_dashboard")
    if has_capability(user, "admin.dashboard"):
        return reverse("admin_dashboard")
    if has_capability(user, "admin.payments"):
        return reverse("admin_manage", args=["payments"])
    if has_capability(user, "admin.cms"):
        return reverse("admin_manage", args=["cms"])
    return reverse("dashboard")


def portal_role_label(user):
    if getattr(user, "is_superuser", False):
        return "System Administrator"
    if is_receptionist(user):
        return "Reception"
    if hasattr(user, "doctor_profile"):
        return "Doctor"
    for role in (ROLE_CLINIC_MANAGER, ROLE_BILLING, ROLE_CONTENT_EDITOR):
        if has_role(user, role):
            return role
    return "Patient"
