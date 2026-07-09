from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from django.utils import timezone
from django.utils.text import slugify


DEFAULT_ZIP_CATEGORY_FOLDERS = {
    "ceremony": "01_Ceremonie",
    "arrival": "02_Arrivee",
    "cocktail": "03_Cocktail",
    "reception": "04_Reception",
    "speech": "05_Discours",
    "dancefloor": "06_Piste_de_danse",
    "cake": "07_Gateau",
    "funny": "08_Moment_drole",
    "emotional": "09_Moment_emouvant",
    "other": "10_Autre",
}


def build_event_zip(event):
    root_name = f"Memora_{_clean_name(event.title)}"
    buffer = BytesIO()

    uploads = (
        event.guest_uploads.filter(
            is_deleted=False,
            moderation_status="approved",
        )
        .select_related("category")
        .order_by("category__sort_order", "uploaded_at", "pk")
    )

    used_paths = set()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        categories = list(event.upload_categories.filter(is_active=True).order_by("sort_order", "label"))
        category_folders = {
            category.id: _category_folder_name(category)
            for category in categories
        }

        for folder_name in category_folders.values():
            archive.writestr(f"{root_name}/{folder_name}/", "")

        for upload in uploads:
            if not upload.media_file:
                continue

            folder_name = category_folders.get(upload.category_id, _category_folder_name(upload.category))
            archive_name = _build_archive_name(upload)
            archive_path = f"{root_name}/{folder_name}/{archive_name}"
            archive_path = _dedupe_path(archive_path, used_paths)

            try:
                upload.media_file.open("rb")
                archive.writestr(archive_path, upload.media_file.read())
            finally:
                upload.media_file.close()

    buffer.seek(0)
    filename = f"{root_name}.zip"
    return filename, buffer.getvalue()


def _clean_name(value):
    cleaned = slugify(value).replace("-", "_")
    return cleaned or "Evenement"


def _category_folder_name(category):
    default_name = DEFAULT_ZIP_CATEGORY_FOLDERS.get(category.code)
    if default_name:
        return default_name
    return f"{category.sort_order:02d}_{_clean_name(category.label)}"


def _build_archive_name(upload):
    uploaded_at = timezone.localtime(upload.uploaded_at)
    timestamp = uploaded_at.strftime("%Y-%m-%d_%H-%M-%S")
    extension = Path(upload.original_filename).suffix.lower()
    if not extension:
        extension = Path(upload.media_file.name).suffix.lower()
    return f"{timestamp}_{upload.media_type}{extension}"


def _dedupe_path(path, used_paths):
    if path not in used_paths:
        used_paths.add(path)
        return path

    stem = Path(path).stem
    suffix = Path(path).suffix
    parent = str(Path(path).parent).replace("\\", "/")
    counter = 2
    while True:
        candidate = f"{parent}/{stem}_{counter}{suffix}"
        if candidate not in used_paths:
            used_paths.add(candidate)
            return candidate
        counter += 1
