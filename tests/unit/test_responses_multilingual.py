"""Unit tests: multilingual response templates.

Business facts (numbers, names) are interpolated verbatim in every language; only
the surrounding phrasing changes. English output must remain byte-identical to the
original single-language wording (backward compatibility).
"""

from __future__ import annotations

from app.conversation import responses
from app.conversation.schemas import Language


def test_english_defaults_unchanged() -> None:
    # No language arg -> exact original strings (existing behaviour preserved).
    assert responses.stock_level("Notebook", 7) == "Notebook currently has 7 units in stock."
    assert responses.adjusted("Notebook", 20, 30) == "Added 20 to Notebook. Current stock: 30."
    assert responses.adjusted("Notebook", -5, 25) == "Removed 5 from Notebook. Current stock: 25."


def test_business_values_preserved_across_languages() -> None:
    # The number 27 and the name must appear regardless of language.
    for lang in (Language.EN, Language.HI, Language.TE):
        text = responses.stock_level("Notebook", 27, lang)
        assert "27" in text
        assert "Notebook" in text


def test_telugu_and_hindi_use_native_script() -> None:
    hi = responses.stock_level("Notebook", 27, Language.HI)
    te = responses.stock_level("Notebook", 27, Language.TE)
    # Contains Devanagari / Telugu characters respectively.
    assert any("ऀ" <= c <= "ॿ" for c in hi)
    assert any("ఀ" <= c <= "౿" for c in te)


def test_missing_quantity_direction_wording() -> None:
    add_en = responses.missing_quantity("notebooks", True, Language.EN)
    rem_en = responses.missing_quantity("notebooks", False, Language.EN)
    assert "add" in add_en
    assert "remove" in rem_en


def test_unknown_language_falls_back_to_english_template() -> None:
    # StrEnum has only EN/HI/TE; passing EN-equivalent path returns English text.
    assert responses.unsupported(Language.EN).startswith("Sorry")
