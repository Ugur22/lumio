import base64
import logging
import shutil
import time
import uuid
from pathlib import Path

from models import IMAGE_EXTENSIONS, ImageData, ImageRef, Settings

log = logging.getLogger("dolphinllm")

DAY = 24 * 60 * 60


def chat_dir(settings: Settings, chat_id: str) -> Path:
    return settings.images_dir / chat_id


def image_path(settings: Settings, chat_id: str, ref: ImageRef) -> Path:
    return chat_dir(settings, chat_id) / f"{ref.id}.{IMAGE_EXTENSIONS[ref.media_type]}"


def save_images(settings: Settings, chat_id: str, images: list[ImageData]) -> list[ImageRef]:
    refs = []
    for image in images:
        ref = ImageRef(id=uuid.uuid4().hex, media_type=image.media_type)
        path = image_path(settings, chat_id, ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(image.data))
        refs.append(ref)
    return refs


def data_url(settings: Settings, chat_id: str, ref: ImageRef) -> str | None:
    """None once the file has been pruned, so callers can degrade to a placeholder."""
    path = image_path(settings, chat_id, ref)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    return f"data:{ref.media_type};base64,{base64.b64encode(raw).decode()}"


def delete_chat_images(settings: Settings, chat_id: str) -> None:
    shutil.rmtree(chat_dir(settings, chat_id), ignore_errors=True)


def prune(settings: Settings, now: float | None = None) -> int:
    """Deletes images past the retention period and returns how many went."""
    cutoff = (now if now is not None else time.time()) - settings.image_retention_days * DAY
    removed = 0
    if not settings.images_dir.exists():
        return removed
    for folder in settings.images_dir.iterdir():
        if not folder.is_dir():
            continue
        for file in folder.iterdir():
            try:
                if file.stat().st_mtime < cutoff:
                    file.unlink()
                    removed += 1
            except OSError:
                log.warning("Could not prune %s", file.name)
        try:
            folder.rmdir()  # only succeeds when empty
        except OSError:
            pass
    return removed
