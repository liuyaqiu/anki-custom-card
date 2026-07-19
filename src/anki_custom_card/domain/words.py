import unicodedata


def normalize_english_word(value: str) -> str:
    """Normalize an English word or expression for business identity comparisons."""

    normalized = unicodedata.normalize("NFKC", value)
    normalized = " ".join(normalized.split()).casefold()
    if not normalized:
        raise ValueError("word must not be blank")
    return normalized


def clean_word_display(value: str) -> str:
    """Remove accidental surrounding/repeated whitespace without changing display case."""

    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValueError("word must not be blank")
    return cleaned
