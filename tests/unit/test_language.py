"""Unit tests: deterministic language detection & response-language resolution."""

from __future__ import annotations

import pytest
from app.conversation.language import detect_script_language, resolve_response_language
from app.conversation.schemas import Language


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("How many notebooks are available?", None),
        ("notebooklu enni unnayi?", None),  # romanized Telugu is Latin script
        ("notebook kitne hain?", None),  # romanized Hindi is Latin script
        ("నోట్‌బుక్స్ ఎన్ని ఉన్నాయి?", Language.TE),
        ("कितने नोटबुक उपलब्ध हैं?", Language.HI),
        ("20 నోట్‌బుక్స్ స్టాక్‌లో చేర్చండి", Language.TE),
        ("20 नोटबुक स्टॉक में जोड़ो", Language.HI),
        ("", None),
    ],
)
def test_detect_script_language(text: str, expected: Language | None) -> None:
    assert detect_script_language(text) == expected


def test_script_wins_over_model_hint() -> None:
    # Even if the model claims English, Telugu script in the text is authoritative.
    assert resolve_response_language("నోట్‌బుక్స్", Language.EN) is Language.TE


def test_model_hint_used_for_romanized_text() -> None:
    # Latin script is inconclusive; honour the model's hint for romanized input.
    assert resolve_response_language("notebook kitne hain", Language.HI) is Language.HI
    assert resolve_response_language("notebooklu enni unnayi", Language.TE) is Language.TE


def test_defaults_to_english() -> None:
    assert resolve_response_language("how many notebooks", None) is Language.EN
    assert resolve_response_language("plain english text") is Language.EN


def test_mixed_script_prefers_majority() -> None:
    # A code-mixed string with more Devanagari than Telugu resolves to Hindi.
    assert detect_script_language("नोटबुक कितने हैं notebook") is Language.HI
