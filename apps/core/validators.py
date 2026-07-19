from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError


MEDICAL_EXTENSIONS = {"pdf", "jpg", "jpeg", "png", "webp", "doc", "docx"}
CHAT_EXTENSIONS = MEDICAL_EXTENSIONS | {"mp4", "mov", "webm", "mp3", "m4a", "wav"}

MIME_TYPES = {
    "pdf": {"application/pdf"},
    "jpg": {"image/jpeg"},
    "jpeg": {"image/jpeg"},
    "png": {"image/png"},
    "webp": {"image/webp"},
    "doc": {"application/msword", "application/octet-stream"},
    "docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",
        "application/octet-stream",
    },
    "mp4": {"video/mp4", "application/mp4"},
    "mov": {"video/quicktime"},
    "webm": {"video/webm", "audio/webm"},
    "mp3": {"audio/mpeg", "audio/mp3"},
    "m4a": {"audio/mp4", "audio/x-m4a", "video/mp4"},
    "wav": {"audio/wav", "audio/x-wav"},
}


def _has_expected_signature(extension, header):
    if extension == "pdf":
        return header.startswith(b"%PDF-")
    if extension in {"jpg", "jpeg"}:
        return header.startswith(b"\xff\xd8\xff")
    if extension == "png":
        return header.startswith(b"\x89PNG\r\n\x1a\n")
    if extension == "webp":
        return header.startswith(b"RIFF") and header[8:12] == b"WEBP"
    if extension == "doc":
        return header.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    if extension == "docx":
        return header.startswith(b"PK\x03\x04")
    if extension in {"mp4", "mov", "m4a"}:
        return b"ftyp" in header[4:16]
    if extension == "webm":
        return header.startswith(b"\x1aE\xdf\xa3")
    if extension == "mp3":
        return header.startswith(b"ID3") or (
            len(header) >= 2 and header[0] == 0xFF and header[1] & 0xE0 == 0xE0
        )
    if extension == "wav":
        return header.startswith(b"RIFF") and header[8:12] == b"WAVE"
    return False


def _validate_upload(value, allowed_extensions):
    if not value:
        return
    extension = Path(value.name).suffix.lower().lstrip(".")
    if extension not in allowed_extensions:
        raise ValidationError(
            "This file type is not allowed.", code="invalid_extension"
        )

    max_size = getattr(settings, "MAX_PRIVATE_UPLOAD_SIZE", 10 * 1024 * 1024)
    if value.size > max_size:
        raise ValidationError(
            f"Files must be {max_size // (1024 * 1024)} MB or smaller.",
            code="file_too_large",
        )

    # Existing committed files were validated when uploaded. Avoid downloading a
    # remote object merely because another model field is being edited.
    if getattr(value, "_committed", False):
        return

    upload = getattr(value, "file", value)
    content_type = getattr(upload, "content_type", "")
    if content_type and content_type.lower() not in MIME_TYPES[extension]:
        raise ValidationError(
            "The file content does not match its extension.", code="invalid_mime"
        )

    try:
        position = upload.tell()
    except (AttributeError, OSError):
        position = None
    try:
        upload.seek(0)
        header = upload.read(32)
    except (AttributeError, OSError) as exc:
        raise ValidationError(
            "The uploaded file could not be inspected.", code="unreadable_file"
        ) from exc
    finally:
        if position is not None:
            upload.seek(position)

    if not _has_expected_signature(extension, header):
        raise ValidationError(
            "The file content is invalid or does not match its extension.",
            code="invalid_signature",
        )


def validate_medical_document(value):
    _validate_upload(value, MEDICAL_EXTENSIONS)


def validate_chat_attachment(value):
    _validate_upload(value, CHAT_EXTENSIONS)
