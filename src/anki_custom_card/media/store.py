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
DEFAULT_MAX_MEDIA_BYTES = 25 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class StoredMedia:
    sha256: str
    media_type: str
    mime_type: str
    byte_size: int
    relative_path: str


class ContentAddressedMediaStore:
    def __init__(self, root: Path, *, max_bytes: int = DEFAULT_MAX_MEDIA_BYTES) -> None:
        self.root = root.resolve()
        self.max_bytes = max_bytes
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, content: bytes, *, media_type: str, mime_type: str) -> StoredMedia:
        if not content:
            raise ValueError("media content must not be empty")
        if len(content) > self.max_bytes:
            raise ValueError(f"media content exceeds {self.max_bytes} bytes")

        extension = MEDIA_EXTENSIONS.get((media_type, mime_type))
        if extension is None:
            raise ValueError(f"unsupported media type: {media_type}/{mime_type}")
        self._reject_known_mismatch(content, mime_type)

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

    def read(self, relative_path: str) -> bytes:
        return self._safe_path(Path(relative_path)).read_bytes()

    def _safe_path(self, relative_path: Path) -> Path:
        candidate = (self.root / relative_path).resolve()
        if not candidate.is_relative_to(self.root) or candidate == self.root:
            raise ValueError("unsafe media path")
        return candidate

    @staticmethod
    def _reject_known_mismatch(content: bytes, mime_type: str) -> None:
        signatures = {
            "image/png": (b"\x89PNG\r\n\x1a\n",),
            "image/jpeg": (b"\xff\xd8\xff",),
            "image/webp": (b"RIFF",),
            "audio/mpeg": (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"),
            "audio/ogg": (b"OggS",),
        }
        detected = next(
            (
                candidate
                for candidate, prefixes in signatures.items()
                if any(content.startswith(prefix) for prefix in prefixes)
            ),
            None,
        )
        if detected is not None and detected != mime_type:
            raise ValueError(f"media signature is {detected}, not {mime_type}")
