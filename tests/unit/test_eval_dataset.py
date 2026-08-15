"""Unit tests: evaluation dataset integrity + deterministic offline scoring.

These run without any model: they validate the dataset, prove deterministic
language detection over the native-script cases, and score the deterministic
MockConversationAiProvider on a curated well-formed-English subset. Live-model
accuracy is measured separately by ``python -m evals.run_eval`` against Ollama.
"""

from __future__ import annotations

from app.conversation.language import detect_script_language
from app.conversation.provider import MockConversationAiProvider
from app.conversation.schemas import IntentType, Language
from evals.dataset import CASES, SAFE_INJECTION_INTENTS
from evals.harness import run


def test_dataset_is_nontrivial_and_well_formed() -> None:
    assert len(CASES) >= 25
    for c in CASES:
        assert c.text.strip()
        assert isinstance(c.expected_intent, IntentType)
        assert isinstance(c.expected_language, Language)
    # Coverage: all three languages and the key scenario tags are present.
    langs = {c.expected_language for c in CASES}
    assert langs == {Language.EN, Language.TE, Language.HI}
    all_tags = {t for c in CASES for t in c.tags}
    for required in ("injection", "romanized", "native", "unsupported", "ambiguous"):
        assert required in all_tags, required


def test_injection_cases_expect_safe_intent() -> None:
    for c in CASES:
        if "injection" in c.tags:
            assert c.expected_intent in SAFE_INJECTION_INTENTS


def test_native_script_language_detection_is_perfect() -> None:
    # Deterministic: every native-script case must be detected to its language.
    for c in CASES:
        if "native" in c.tags:
            detected = detect_script_language(c.text)
            assert detected is c.expected_language, c.text


def test_mock_provider_scores_well_formed_english() -> None:
    # A curated subset the deterministic mock is expected to handle. The mock is a
    # keyword engine (no real NLU), so misspelled/romanized/native cases are out of
    # scope here and are covered by the live-model eval instead.
    out_of_scope = {"misspelled", "words-number", "colloquial"}
    friendly = [c for c in CASES if "en" in c.tags and not (out_of_scope & set(c.tags))]
    results = run(MockConversationAiProvider(), friendly)
    assert results.intent.total >= 8
    assert results.intent.pct == 100.0, results.failures


def test_mock_rejects_english_injection() -> None:
    mock = MockConversationAiProvider()
    for c in CASES:
        if "injection" in c.tags and "en" in c.tags:
            assert mock.resolve(c.text).intent in SAFE_INJECTION_INTENTS, c.text


def test_harness_runs_full_dataset_without_crashing() -> None:
    results = run(MockConversationAiProvider())
    assert results.intent.total == len(CASES)
    assert results.errors == 0  # mock never raises
