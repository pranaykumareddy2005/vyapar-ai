"""Scoring harness: run a ConversationAiProvider over the dataset and compute
accuracy metrics.

Metrics are model-accuracy only (does the provider return the right structured
intent/entities/language). Business-operation correctness is proven separately by
the integration tests, which assert the domain services return the real numbers.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.conversation.language import resolve_response_language
from app.conversation.provider import ConversationAiError, ConversationAiProvider
from app.conversation.schemas import IntentType, Language

from evals.dataset import CASES, SAFE_INJECTION_INTENTS, EvalCase


@dataclass
class Metric:
    correct: int = 0
    total: int = 0

    def add(self, ok: bool) -> None:
        self.total += 1
        if ok:
            self.correct += 1

    @property
    def pct(self) -> float:
        return 100.0 * self.correct / self.total if self.total else 0.0


# Ordered language buckets for the multilingual breakdown (plan item 13). A case
# is assigned to exactly one bucket, "mixed" taking precedence over the base
# language tag so code-mixed input is reported on its own.
_LANGUAGE_BUCKETS = ("english", "telugu", "hindi", "mixed")


def _language_bucket(tags: tuple[str, ...]) -> str | None:
    """Map a case's tags to one multilingual reporting bucket (or ``None``)."""
    if "mixed" in tags:
        return "mixed"
    if "te" in tags:
        return "telugu"
    if "hi" in tags:
        return "hindi"
    if "en" in tags:
        return "english"
    return None


@dataclass
class EvalResults:
    intent: Metric = field(default_factory=Metric)
    quantity: Metric = field(default_factory=Metric)
    direction: Metric = field(default_factory=Metric)
    product: Metric = field(default_factory=Metric)
    model_language: Metric = field(default_factory=Metric)
    response_language: Metric = field(default_factory=Metric)
    unsupported: Metric = field(default_factory=Metric)
    injection_rejection: Metric = field(default_factory=Metric)
    # Intent accuracy sliced per language bucket (plan item 13).
    by_language: dict[str, Metric] = field(
        default_factory=lambda: {b: Metric() for b in _LANGUAGE_BUCKETS}
    )
    errors: int = 0
    failures: list[str] = field(default_factory=list)
    latencies_ms: list[float] = field(default_factory=list)

    @property
    def avg_latency_ms(self) -> float:
        return sum(self.latencies_ms) / len(self.latencies_ms) if self.latencies_ms else 0.0


def _product_ok(resolved_query: str | None, expected_any: tuple[str, ...]) -> bool:
    if not expected_any:
        return True
    if not resolved_query:
        return False
    low = resolved_query.lower()
    return any(sub.lower() in low for sub in expected_any)


def score_case(provider: ConversationAiProvider, case: EvalCase, results: EvalResults) -> None:
    start = time.perf_counter()
    try:
        resolved = provider.resolve(case.text)
    except ConversationAiError as exc:
        results.errors += 1
        results.failures.append(f"[error:{exc.code}] {case.text!r}")
        return
    results.latencies_ms.append((time.perf_counter() - start) * 1000.0)

    intent_ok = resolved.intent is case.expected_intent
    results.intent.add(intent_ok)
    bucket = _language_bucket(case.tags)
    if bucket is not None:
        results.by_language[bucket].add(intent_ok)
    if not intent_ok:
        results.failures.append(
            f"[intent] {case.text!r}: got {resolved.intent}, want {case.expected_intent}"
        )

    # Injection cases: the only requirement is a *safe* classification.
    if "injection" in case.tags:
        results.injection_rejection.add(resolved.intent in SAFE_INJECTION_INTENTS)

    if case.expected_intent is IntentType.UNSUPPORTED:
        results.unsupported.add(resolved.intent is IntentType.UNSUPPORTED)

    if case.expected_quantity is not None:
        results.quantity.add(resolved.entities.quantity == case.expected_quantity)
    if case.expected_direction is not None:
        results.direction.add(resolved.entities.direction is case.expected_direction)
    if case.product_any:
        results.product.add(_product_ok(resolved.entities.product_query, case.product_any))

    # Language: model's own claim vs. the pipeline's authoritative response language.
    results.model_language.add(resolved.language is case.expected_language)
    response_lang = resolve_response_language(case.text, resolved.language)
    # For native-script cases the reply language must match; for romanized cases
    # English is an acceptable reply (script is inconclusive), so only score when
    # the expected language is derivable from script or the model agrees.
    expected_response = _expected_response_language(case)
    results.response_language.add(response_lang is expected_response)


def _expected_response_language(case: EvalCase) -> Language:
    """The language we expect to *reply* in for this case.

    Native-script input must be answered in that script; romanized/Latin input is
    acceptably answered in English (the deterministic fallback).
    """
    from app.conversation.language import detect_script_language

    script = detect_script_language(case.text)
    return script if script is not None else Language.EN


def run(provider: ConversationAiProvider, cases: list[EvalCase] | None = None) -> EvalResults:
    results = EvalResults()
    for case in cases or CASES:
        score_case(provider, case, results)
    return results
