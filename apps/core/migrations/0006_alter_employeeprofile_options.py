from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0005_employeeprofile"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="employeeprofile",
            options={
                "ordering": ["user__first_name", "user__last_name", "employee_id"],
                "verbose_name": "Clinic employee",
                "verbose_name_plural": "Clinic employees",
            },
        ),
    ]
