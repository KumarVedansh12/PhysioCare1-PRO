from pathlib import Path

from django.apps import apps
from django.core import serializers
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core.backups import BACKUP_MODELS, decrypt_and_validate_backup


class Command(BaseCommand):
    help = "Validate or restore an encrypted PhysioCare .pcbackup archive into an empty database."

    def add_arguments(self, parser):
        parser.add_argument("backup_file")
        parser.add_argument(
            "--restore",
            action="store_true",
            help="Restore after validation. Without this flag the command is read-only.",
        )
        parser.add_argument(
            "--confirm-empty-database",
            action="store_true",
            help="Required with --restore; restoration is allowed only when clinic tables are empty.",
        )

    def handle(self, *args, **options):
        path = Path(options["backup_file"]).expanduser()
        if not path.is_file():
            raise CommandError(f"Backup file not found: {path}")
        try:
            archive, manifest = decrypt_and_validate_backup(path.read_bytes())
        except ValidationError as exc:
            raise CommandError(" ".join(exc.messages)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Backup validated: {len(manifest['data_entries'])} data files and "
                f"{len(manifest['media_entries'])} private media files."
            )
        )
        if not options["restore"]:
            archive.close()
            self.stdout.write(
                "Validation only; no database or storage changes were made."
            )
            return
        if not options["confirm_empty_database"]:
            archive.close()
            raise CommandError(
                "Use --confirm-empty-database with --restore after verifying the target is empty."
            )

        nonempty = [
            name for name, model in BACKUP_MODELS if model._default_manager.exists()
        ]
        if nonempty:
            archive.close()
            raise CommandError(
                "Restore refused because these target tables are not empty: "
                + ", ".join(nonempty)
            )

        saved_media = []
        try:
            with transaction.atomic():
                for entry in manifest["data_entries"]:
                    payload = archive.read(entry["name"]).decode()
                    for item in serializers.deserialize("json", payload):
                        item.save()

                for entry in manifest["media_entries"]:
                    storage_name = entry["storage_name"]
                    if default_storage.exists(storage_name):
                        raise CommandError(
                            f"Media restore refused because {storage_name} already exists."
                        )
                    saved_name = default_storage.save(
                        storage_name, ContentFile(archive.read(entry["name"]))
                    )
                    saved_media.append(saved_name)
                    if saved_name != storage_name:
                        model = apps.get_model(entry["model"])
                        obj = model._default_manager.get(pk=entry["pk"])
                        setattr(obj, entry["field"], saved_name)
                        obj.save(update_fields=[entry["field"]])
        except Exception:
            for name in saved_media:
                default_storage.delete(name)
            raise
        finally:
            archive.close()
        self.stdout.write(
            self.style.SUCCESS("Clinic data and private media restored successfully.")
        )
