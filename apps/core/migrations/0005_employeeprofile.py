from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


def create_existing_employee_profiles(apps, schema_editor):
    User = apps.get_model("auth", "User")
    EmployeeProfile = apps.get_model("core", "EmployeeProfile")

    users = User.objects.filter(is_staff=True, is_superuser=False).exclude(
        doctor_profile__isnull=False
    ).prefetch_related("groups")
    for user in users:
        role = user.groups.first().name if user.groups.exists() else "Clinic staff"
        department = {
            "Reception": "front_desk",
            "Billing": "billing",
            "Content Editor": "administration",
            "Clinic Manager": "administration",
        }.get(role, "operations")
        profile = EmployeeProfile.objects.create(
            user=user,
            phone="",
            job_title=role,
            department=department,
            employment_type="full_time",
            shift="full_day",
            joined_on=user.date_joined.date(),
            portal_access=True,
            active=user.is_active,
        )
        profile.employee_id = f"EMP-{profile.pk:05d}"
        profile.save(update_fields=["employee_id"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0004_appointment_checked_in_at_appointment_updated_at_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="EmployeeProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("employee_id", models.CharField(blank=True, max_length=20, unique=True)),
                ("phone", models.CharField(max_length=20)),
                ("job_title", models.CharField(max_length=120)),
                ("department", models.CharField(choices=[("administration", "Administration"), ("front_desk", "Front desk"), ("billing", "Billing and accounts"), ("clinical_support", "Clinical support"), ("operations", "Clinic operations"), ("housekeeping", "Housekeeping"), ("other", "Other")], default="operations", max_length=30)),
                ("employment_type", models.CharField(choices=[("full_time", "Full-time"), ("part_time", "Part-time"), ("contract", "Contract"), ("intern", "Intern / trainee")], default="full_time", max_length=30)),
                ("shift", models.CharField(choices=[("morning", "Morning"), ("evening", "Evening"), ("full_day", "Full day"), ("flexible", "Flexible / rotating")], default="full_day", max_length=30)),
                ("joined_on", models.DateField(default=django.utils.timezone.localdate)),
                ("monthly_salary", models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ("emergency_contact", models.CharField(blank=True, max_length=120)),
                ("address", models.TextField(blank=True)),
                ("notes", models.TextField(blank=True)),
                ("portal_access", models.BooleanField(default=False)),
                ("active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="employee_profile", to="auth.user")),
            ],
            options={"ordering": ["user__first_name", "user__last_name", "employee_id"]},
        ),
        migrations.RunPython(create_existing_employee_profiles, migrations.RunPython.noop),
    ]
