import hashlib
from pathlib import Path

import pytest

from anki_custom_card.media.store import ContentAddressedMediaStore

pytestmark = pytest.mark.unit


def test_media_store_writes_content_to_stable_hash_path(tmp_path: Path) -> None:
    store = ContentAddressedMediaStore(tmp_path)
    content = b"fake-mp3-content"

    first = store.put(content, media_type="audio", mime_type="audio/mpeg")
    second = store.put(content, media_type="audio", mime_type="audio/mpeg")

    expected_hash = hashlib.sha256(content).hexdigest()
    assert first.sha256 == expected_hash
    assert first == second
    assert first.relative_path == f"audio/{expected_hash}.mp3"
    assert (tmp_path / first.relative_path).read_bytes() == content
    assert list((tmp_path / "audio").iterdir()) == [tmp_path / first.relative_path]


def test_media_store_rejects_empty_or_unsupported_content(tmp_path: Path) -> None:
    store = ContentAddressedMediaStore(tmp_path)

    with pytest.raises(ValueError, match="must not be empty"):
        store.put(b"", media_type="audio", mime_type="audio/mpeg")

    with pytest.raises(ValueError, match="unsupported media type"):
        store.put(b"content", media_type="document", mime_type="application/pdf")


def test_media_store_rejects_paths_outside_root(tmp_path: Path) -> None:
    store = ContentAddressedMediaStore(tmp_path)

    with pytest.raises(ValueError, match="unsafe media path"):
        store.delete("../outside.mp3")


def test_media_store_enforces_size_and_rejects_known_signature_mismatch(tmp_path: Path) -> None:
    store = ContentAddressedMediaStore(tmp_path, max_bytes=8)
    with pytest.raises(ValueError, match="exceeds"):
        store.put(b"123456789", media_type="audio", mime_type="audio/mpeg")
    with pytest.raises(ValueError, match="signature"):
        store.put(b"\x89PNG\r\n\x1a\n", media_type="audio", mime_type="audio/mpeg")
