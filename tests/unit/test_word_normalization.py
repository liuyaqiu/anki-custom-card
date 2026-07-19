import pytest

from anki_custom_card.domain.words import normalize_english_word

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Deploy  ", "deploy"),
        ("pull   request", "pull request"),
        ("ＡＰＩ", "api"),  # noqa: RUF001 - verifies NFKC full-width normalization
        ("Straße", "strasse"),
    ],
)
def test_normalize_english_word_is_stable(raw: str, expected: str) -> None:
    assert normalize_english_word(raw) == expected


def test_normalize_english_word_rejects_blank_input() -> None:
    with pytest.raises(ValueError, match="must not be blank"):
        normalize_english_word(" \t ")
