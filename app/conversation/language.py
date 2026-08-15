"""Deterministic language handling for the conversational layer.

The *response* language is decided here, not by the model, so it cannot be
spoofed or hallucinated. Detection is purely script-based (Unicode ranges) and
has no external dependency:

- Telugu block  U+0C00..U+0C7F  -> Telugu
- Devanagari    U+0900..U+097F  -> Hindi
- otherwise (Latin / undetermined) -> fall back to the model's stated language
  if it is a supported non-English language, else English.

Romanised Telugu/Hindi ("notebooklu enni unnayi", "kitne hain") is Latin script,
so script detection is inconclusive; there we trust the model's ``language`` hint
when it supplied one. Language never affects the business operation — it only
selects the reply template.
"""

from __future__ import annotations

from app.conversation.schemas import Language


def detect_script_language(text: str) -> Language | None:
    """Return the language implied by the script, or ``None`` if inconclusive.

    Whichever supported non-Latin script contributes the most characters wins;
    ``None`` means the text is Latin/undetermined and the caller should fall back.
    """
    telugu = 0
    devanagari = 0
    for ch in text:
        code = ord(ch)
        if 0x0C00 <= code <= 0x0C7F:
            telugu += 1
        elif 0x0900 <= code <= 0x097F:
            devanagari += 1
    if telugu == 0 and devanagari == 0:
        return None
    return Language.TE if telugu >= devanagari else Language.HI


def resolve_response_language(text: str, model_language: Language | None = None) -> Language:
    """Decide the language to reply in.

    Script evidence in the user's own text is authoritative; only when the text
    is Latin/undetermined do we honour the model's hint. Defaults to English.
    """
    script = detect_script_language(text or "")
    if script is not None:
        return script
    if model_language is not None:
        return model_language
    return Language.EN
