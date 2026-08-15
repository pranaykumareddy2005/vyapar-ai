"""Deterministic, multilingual response templates.

The LLM never invents the final business result: every reply is built here from
the actual values returned by the domain services. The AI only influences *which*
template and *which* language — never the numbers, prices, or stock levels.

Each builder takes an optional ``lang`` (defaulting to English) and selects a
template from a per-language table. English output is intentionally identical to
the original single-language wording, so existing behaviour is preserved exactly.
Product names and numeric business facts are interpolated verbatim regardless of
language.
"""

from __future__ import annotations

from app.catalog.models import Product
from app.conversation.schemas import Language

_MAX_LISTED = 5


def _pick(table: dict[Language, str], lang: Language) -> str:
    """Return the template for ``lang`` with an English fallback."""
    return table.get(lang, table[Language.EN])


def search_results(products: list[Product], lang: Language = Language.EN) -> str:
    shown = products[:_MAX_LISTED]
    items = ", ".join(f"{p.name} (SKU {p.sku}, ₹{p.price_amt})" for p in shown)
    extra = "" if len(products) <= _MAX_LISTED else f" (+{len(products) - _MAX_LISTED} more)"
    table = {
        Language.EN: f"Found {len(products)} product(s): {items}{extra}.",
        Language.HI: f"{len(products)} उत्पाद मिले: {items}{extra}।",
        Language.TE: f"{len(products)} ఉత్పత్తులు దొరికాయి: {items}{extra}.",
    }
    return _pick(table, lang)


def not_found(query: str, lang: Language = Language.EN) -> str:
    table = {
        Language.EN: f"Could not find a product matching '{query}'.",
        Language.HI: f"'{query}' से मेल खाता कोई उत्पाद नहीं मिला।",
        Language.TE: f"'{query}'కి సరిపోయే ఉత్పత్తి దొరకలేదు.",
    }
    return _pick(table, lang)


def multiple_matches(query: str, products: list[Product], lang: Language = Language.EN) -> str:
    names = ", ".join(p.name for p in products[:_MAX_LISTED])
    table = {
        Language.EN: (
            f"I found multiple products matching '{query}': {names}. Which one did you mean?"
        ),
        Language.HI: f"'{query}' से मेल खाते कई उत्पाद मिले: {names}। आपका मतलब कौन-सा था?",
        Language.TE: f"'{query}'కి సరిపోయే అనేక ఉత్పత్తులు దొరికాయి: {names}. మీరు ఏది అనుకున్నారు?",
    }
    return _pick(table, lang)


def stock_level(product_name: str, quantity: int, lang: Language = Language.EN) -> str:
    table = {
        Language.EN: f"{product_name} currently has {quantity} units in stock.",
        Language.HI: f"{product_name} में अभी {quantity} इकाइयाँ स्टॉक में हैं।",
        Language.TE: f"{product_name}లో ప్రస్తుతం {quantity} యూనిట్లు స్టాక్‌లో ఉన్నాయి.",
    }
    return _pick(table, lang)


def no_inventory(product_name: str, lang: Language = Language.EN) -> str:
    table = {
        Language.EN: f"There is no inventory record for {product_name} yet.",
        Language.HI: f"{product_name} के लिए अभी कोई इन्वेंट्री रिकॉर्ड नहीं है।",
        Language.TE: f"{product_name} కోసం ఇంకా ఇన్వెంటరీ రికార్డ్ లేదు.",
    }
    return _pick(table, lang)


def adjusted(product_name: str, delta: int, quantity: int, lang: Language = Language.EN) -> str:
    if delta >= 0:
        table = {
            Language.EN: f"Added {delta} to {product_name}. Current stock: {quantity}.",
            Language.HI: f"{product_name} में {delta} जोड़े गए। वर्तमान स्टॉक: {quantity}।",
            Language.TE: f"{product_name}కి {delta} జోడించబడ్డాయి. ప్రస్తుత స్టాక్: {quantity}.",
        }
        return _pick(table, lang)
    removed = abs(delta)
    table = {
        Language.EN: f"Removed {removed} from {product_name}. Current stock: {quantity}.",
        Language.HI: f"{product_name} से {removed} हटाए गए। वर्तमान स्टॉक: {quantity}।",
        Language.TE: f"{product_name} నుండి {removed} తీసివేయబడ్డాయి. ప్రస్తుత స్టాక్: {quantity}.",
    }
    return _pick(table, lang)


def insufficient_stock(
    product_name: str, requested: int, current: int, lang: Language = Language.EN
) -> str:
    table = {
        Language.EN: (
            f"Not enough stock to remove {requested} from {product_name}. Current stock: {current}."
        ),
        Language.HI: (
            f"{product_name} से {requested} हटाने के लिए पर्याप्त स्टॉक नहीं है। वर्तमान स्टॉक: {current}।"
        ),
        Language.TE: (
            f"{product_name} నుండి {requested} తీసివేయడానికి సరిపడా స్టాక్ లేదు. ప్రస్తుత స్టాక్: {current}."
        ),
    }
    return _pick(table, lang)


def missing_product(lang: Language = Language.EN) -> str:
    table = {
        Language.EN: "Which product would you like to adjust?",
        Language.HI: "आप किस उत्पाद को समायोजित करना चाहते हैं?",
        Language.TE: "మీరు ఏ ఉత్పత్తిని సర్దుబాటు చేయాలనుకుంటున్నారు?",
    }
    return _pick(table, lang)


def missing_quantity(product_query: str, increasing: bool, lang: Language = Language.EN) -> str:
    if increasing:
        table = {
            Language.EN: f"How many units of {product_query} would you like to add?",
            Language.HI: f"आप {product_query} की कितनी इकाइयाँ जोड़ना चाहते हैं?",
            Language.TE: f"మీరు {product_query} ఎన్ని యూనిట్లు చేర్చాలనుకుంటున్నారు?",
        }
        return _pick(table, lang)
    table = {
        Language.EN: f"How many units of {product_query} would you like to remove?",
        Language.HI: f"आप {product_query} की कितनी इकाइयाँ हटाना चाहते हैं?",
        Language.TE: f"మీరు {product_query} ఎన్ని యూనిట్లు తీసివేయాలనుకుంటున్నారు?",
    }
    return _pick(table, lang)


def missing_search_product(lang: Language = Language.EN) -> str:
    table = {
        Language.EN: "What product would you like to search for?",
        Language.HI: "आप कौन-सा उत्पाद खोजना चाहते हैं?",
        Language.TE: "మీరు ఏ ఉత్పత్తిని వెతకాలనుకుంటున్నారు?",
    }
    return _pick(table, lang)


def unsupported(lang: Language = Language.EN) -> str:
    table = {
        Language.EN: (
            "Sorry, I can only help with product search, stock checks, and inventory "
            "adjustments right now."
        ),
        Language.HI: ("क्षमा करें, मैं अभी केवल उत्पाद खोज, स्टॉक जाँच और इन्वेंट्री समायोजन में मदद कर सकता हूँ।"),
        Language.TE: (
            "క్షమించండి, నేను ప్రస్తుతం ఉత్పత్తి శోధన, స్టాక్ తనిఖీ మరియు ఇన్వెంటరీ సర్దుబాట్లలో మాత్రమే సహాయం చేయగలను."
        ),
    }
    return _pick(table, lang)


def low_confidence(lang: Language = Language.EN) -> str:
    table = {
        Language.EN: (
            "I'm not sure I understood. Could you rephrase, including the product and amount?"
        ),
        Language.HI: "मुझे ठीक से समझ नहीं आया। कृपया उत्पाद और मात्रा सहित दोबारा बताएँ।",
        Language.TE: "నాకు సరిగ్గా అర్థం కాలేదు. దయచేసి ఉత్పత్తి మరియు పరిమాణంతో సహా మళ్లీ చెప్పండి.",
    }
    return _pick(table, lang)


def empty_message(lang: Language = Language.EN) -> str:
    table = {
        Language.EN: "Please send a text message describing what you need.",
        Language.HI: "कृपया अपनी ज़रूरत बताते हुए एक टेक्स्ट संदेश भेजें।",
        Language.TE: "దయచేసి మీకు ఏమి కావాలో తెలియజేస్తూ ఒక టెక్స్ట్ సందేశం పంపండి.",
    }
    return _pick(table, lang)


def ai_error(lang: Language = Language.EN) -> str:
    table = {
        Language.EN: "Sorry, I couldn't process that right now. Please try again.",
        Language.HI: "क्षमा करें, मैं अभी इसे संसाधित नहीं कर सका। कृपया पुनः प्रयास करें।",
        Language.TE: "క్షమించండి, నేను దీన్ని ఇప్పుడు ప్రాసెస్ చేయలేకపోయాను. దయచేసి మళ్లీ ప్రయత్నించండి.",
    }
    return _pick(table, lang)


def internal_error(lang: Language = Language.EN) -> str:
    table = {
        Language.EN: "Sorry, something went wrong handling that. Please try again.",
        Language.HI: "क्षमा करें, इसे संभालने में कुछ गड़बड़ हो गई। कृपया पुनः प्रयास करें।",
        Language.TE: "క్షమించండి, దీన్ని నిర్వహించడంలో ఏదో తప్పు జరిగింది. దయచేసి మళ్లీ ప్రయత్నించండి.",
    }
    return _pick(table, lang)
