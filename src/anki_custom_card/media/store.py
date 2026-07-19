import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

MEDIA_EXTENSIONS = {
    ("audio", "audio/mpeg"): ".mp3",
    ("audio", "audio/ogg"): ".ogg",
    ("image", "image/jpeg"): ".jpg",
    ("image", "image/png"): ".png",
    ("image", "image/webp"): ".webp",
}


@dataclass(frozen=True, slots=True)
class StoredMedia:
    sha256: str
    media_type: str
    mime_type: str
    byte_size: int
    relative_path: str


class ContentAddressedMediaStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, content: bytes, *, media_type: str, mime_type: str) -> StoredMedia:
        if not content:
            raise ValueError("media content must not be empty")

        extension = MEDIA_EXTENSIONS.get((media_type, mime_type))
        if extension is None:
            raise ValueError(f"unsupported media type: {media_type}/{mime_type}")

        digest = hashlib.sha256(content).hexdigest()
        relative_path = Path(media_type) / f"{digest}{extension}"
        target = self._safe_path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        if not target.exists():
            descriptor, temporary_name = tempfile.mkstemp(prefix=".media-", dir=target.parent)
            temporary_path = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "wb") as temporary_file:
                    temporary_file.write(content)
                    temporary_file.flush()
                    os.fsync(temporary_file.fileno())
                os.replace(temporary_path, target)
            finally:
                temporary_path.unlink(missing_ok=True)

        return StoredMedia(
            sha256=digest,
            media_type=media_type,
            mime_type=mime_type,
            byte_size=len(content),
            relative_path=relative_path.as_posix(),
        )

    def delete(self, relative_path: str) -> None:
        self._safe_path(Path(relative_path)).unlink(missing_ok=True)

    def _safe_path(self, relative_path: Path) -> Path:
        candidate = (self.root / relative_path).resolve()
        if not candidate.is_relative_to(self.root) or candidate == self.root:
            raise ValueError("unsafe media path")
        return candidate
