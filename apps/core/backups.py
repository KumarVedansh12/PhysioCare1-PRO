import hashlib
import json
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core import serializers
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.utils import timezone

from .models import (
    Appointment,
    ChatMessage,
    CMSContent,
    ContactMessage,
    DoctorProfile,
    EmailDelivery,
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


BACKUP_FORMAT = "PhysioCare encrypted backup v2"
BACKUP_MODELS = (
    ("groups", Group),
    ("users", User),
    ("patients", PatientProfile),
    ("employees", EmployeeProfile),
    ("doctors", DoctorProfile),
    ("appointments", Appointment),
    ("treatment_plans", TreatmentPlan),
    ("exercises", Exercise),
    ("exercise_assignments", ExerciseAssignment),
    ("progress", ProgressEntry),
    ("prescriptions", Prescription),
    ("medical_records", MedicalRecord),
    ("notifications", Notification),
    ("messages", ChatMessage),
    ("payments", Payment),
    ("feedback", Feedback),
    ("cms", CMSContent),
    ("contact_messages", ContactMessage),
    ("email_deliveries", EmailDelivery),
)
MEDIA_FIELDS = (
    (PatientProfile, "profile_picture"),
    (MedicalRecord, "file"),
    (ChatMessage, "attachment"),
)


def _fernet():
    key = settings.BACKUP_ENCRYPTION_KEY
    if not key:
        raise ImproperlyConfigured("BACKUP_ENCRYPTION_KEY is not configured")
    try:
        return Fernet(key.encode())
    except (TypeError, ValueError) as exc:
        raise ImproperlyConfigured("BACKUP_ENCRYPTION_KEY is invalid") from exc


def backup_encryption_ready():
    try:
        _fernet()
    except ImproperlyConfigured:
        return False
    return True


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def build_encrypted_backup():
    archive_buffer = BytesIO()
    entries = []
    media_entries = []
    with ZipFile(
        archive_buffer, "w", compression=ZIP_DEFLATED, compresslevel=6
    ) as archive:
        for name, model in BACKUP_MODELS:
            data = serializers.serialize(
                "json", model._default_manager.all(), indent=2
            ).encode()
            archive_name = f"data/{name}.json"
            archive.writestr(archive_name, data)
            entries.append(
                {"name": archive_name, "sha256": _digest(data), "size": len(data)}
            )

        for model, field_name in MEDIA_FIELDS:
            for obj in model._default_manager.exclude(**{field_name: ""}).iterator():
                field_file = getattr(obj, field_name)
                if not field_file or not field_file.name:
                    continue
                safe_name = Path(field_file.name).name
                archive_name = (
                    f"media/{model._meta.label_lower}/{obj.pk}/{field_name}/{safe_name}"
                )
                try:
                    field_file.open("rb")
                    data = field_file.read()
                finally:
                    try:
                        field_file.close()
                    except Exception:
                        pass
                archive.writestr(archive_name, data)
                media_entries.append(
                    {
                        "name": archive_name,
                        "sha256": _digest(data),
                        "size": len(data),
                        "model": model._meta.label,
                        "pk": obj.pk,
                        "field": field_name,
                        "storage_name": field_file.name,
                    }
                )

        manifest = {
            "format": BACKUP_FORMAT,
            "generated_at": timezone.now().isoformat(),
            "data_entries": entries,
            "media_entries": media_entries,
            "encrypted": True,
        }
        archive.writestr("manifest.json", json.dumps(manifest, indent=2).encode())
    return _fernet().encrypt(archive_buffer.getvalue())


def decrypt_and_validate_backup(encrypted_data):
    try:
        archive_data = _fernet().decrypt(encrypted_data)
    except InvalidToken as exc:
        raise ValidationError(
            "The backup is damaged or was encrypted with a different key."
        ) from exc
    try:
        archive = ZipFile(BytesIO(archive_data), "r")
        manifest = json.loads(archive.read("manifest.json"))
    except (BadZipFile, KeyError, json.JSONDecodeError) as exc:
        raise ValidationError("The backup archive or manifest is invalid.") from exc
    if manifest.get("format") != BACKUP_FORMAT:
        archive.close()
        raise ValidationError("This backup format is not supported.")
    for entry in manifest.get("data_entries", []) + manifest.get("media_entries", []):
        try:
            data = archive.read(entry["name"])
        except KeyError as exc:
            archive.close()
            raise ValidationError(
                f"Backup entry {entry.get('name', 'unknown')} is missing."
            ) from exc
        if len(data) != entry["size"] or _digest(data) != entry["sha256"]:
            archive.close()
            raise ValidationError(
                f"Backup entry {entry['name']} failed its integrity check."
            )
    return archive, manifest
