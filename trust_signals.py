"""
Trust, Urgency & Personalization Signal Audit
-----------------------------------------------
pro_scanner.py's existing ecommerce_audit() checks for the presence of CTA,
price, reviews, delivery, returns, payment -- the "can I even buy this"
basics. This module goes one layer deeper into conversion psychology, which
is exactly the kind of thing that makes a founder go "oh, we're leaving
money on the table":

  - Urgency / scarcity ("only 3 left", countdown timers, "sale ends in")
  - Social proof ("124 people bought this today", "trending", bestseller tags)
  - Trust badges (SSL/secure-checkout seals, recognizable payment logos)
  - Personalization / cross-sell ("customers also bought", "recommended for you")
  - Guest checkout / low-friction checkout signals
  - Free-shipping threshold messaging

Grounded in: Baymard Institute checkout-usability research and the Visa /
Stanford Digital Trust Lab (2026) finding that visible SSL badges + payment
logos + a money-back guarantee cut security-related checkout abandonment by
roughly half. See FEATURES.md for full citations.

This module returns plain dicts shaped like pro_scanner.ProIssue kwargs
(category/severity/location/message/...), same convention as web_vitals.py,
so pro_scanner.py can convert them with `issue(**d)`.
"""
from __future__ import annotations
import re
from typing import Any, Dict, List, Tuple


URGENCY_PATTERNS = [
    r"only\s+\d+\s+left", r"hurry", r"limited\s+(stock|time|offer|edition)",
    r"sale\s+ends", r"offer\s+ends", r"selling\s+fast", r"almost\s+gone",
    r"while\s+supplies\s+last", r"deal\s+ends\s+in", r"\d+\s*:\s*\d+\s*:\s*\d+",
]
SOCIAL_PROOF_PATTERNS = [
    r"\d+[\d,]*\s+(people|customers|shoppers)\s+(bought|viewing|purchased)",
    r"bestseller", r"best\s*seller", r"trending\s+now", r"top\s+rated",
    r"\d+[\d,]*\s+sold", r"popular\s+choice", r"\d+[\d,]*\s+in\s+(cart|carts)",
]
PERSONALIZATION_PATTERNS = [
    r"customers?\s+also\s+(bought|viewed|liked)", r"recommended\s+for\s+you",
    r"you\s+may\s+also\s+like", r"similar\s+products?", r"complete\s+the\s+look",
    r"frequently\s+bought\s+together", r"based\s+on\s+your", r"pairs\s+well\s+with",
]
GUEST_CHECKOUT_PATTERNS = [r"guest\s+checkout", r"checkout\s+as\s+guest", r"no\s+account\s+(needed|required)"]
FREE_SHIPPING_PATTERNS = [r"free\s+shipping", r"free\s+delivery\s+(on|over|above)", r"spend\s+.{0,10}\s+for\s+free"]
TRUST_BADGE_KEYWORDS = ["ssl", "secure checkout", "verified", "norton", "mcafee", "trustpilot",
                          "trusted", "money back", "money-back", "satisfaction guarantee", "authentic"]
PAYMENT_LOGO_KEYWORDS = ["visa", "mastercard", "amex", "american express", "paypal", "razorpay",
                          "stripe", "upi", "google pay", "apple pay", "klarna", "afterpay"]


def _search_any(patterns: List[str], text: str) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)


def _count_any(patterns: List[str], text: str) -> int:
    return sum(len(re.findall(p, text, re.I)) for p in patterns)


def _image_alt_and_class_text(soup) -> str:
    parts = []
    for img in soup.find_all("img"):
        parts.append(img.get("alt") or "")
        parts.append(" ".join(img.get("class") or []))
        src = img.get("src") or ""
        parts.append(src)
    for el in soup.find_all(attrs={"class": True}):
        parts.append(" ".join(el.get("class") or []))
    return " ".join(parts)


def audit(soup, content=None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    body = soup.get_text(" ", strip=True)
    aux = _image_alt_and_class_text(soup)
    combined = body + " " + aux
    lower = combined.lower()

    has_countdown_widget = bool(soup.find(attrs={"class": re.compile(r"countdown|timer", re.I)})) \
        or bool(soup.find(attrs={"id": re.compile(r"countdown|timer", re.I)}))
    urgency = _search_any(URGENCY_PATTERNS, lower) or has_countdown_widget
    social_proof = _search_any(SOCIAL_PROOF_PATTERNS, lower)
    personalization = _search_any(PERSONALIZATION_PATTERNS, lower)
    guest_checkout = _search_any(GUEST_CHECKOUT_PATTERNS, lower)
    free_shipping = _search_any(FREE_SHIPPING_PATTERNS, lower)
    trust_badges = any(k in lower for k in TRUST_BADGE_KEYWORDS)
    payment_logos = any(k in lower for k in PAYMENT_LOGO_KEYWORDS)

    out: List[Dict[str, Any]] = []

    def opportunity(flag, location, message, remediation, impact="medium", signal_tag=None):
        if not flag:
            out.append(dict(category="conversion", severity="info", location=location, message=message,
                             impact=impact, remediation=remediation, signal_tag=signal_tag, confidence=.75))

    opportunity(urgency, "urgency signals",
                "No urgency/scarcity messaging (low-stock counts, sale countdowns) is detectable.",
                "Add genuine scarcity signals (real stock counts, real sale-end timers) near the CTA -- "
                "these are consistently among the highest-leverage, lowest-cost PDP changes when the "
                "underlying claim is truthful. Avoid fake countdowns; they erode trust once noticed.",
                impact="medium", signal_tag="urgency")
    opportunity(social_proof, "social proof signals",
                "No social-proof signal ('bestseller', 'N bought today', 'trending') is detectable.",
                "Surface real purchase/view counts or a bestseller badge if the data exists -- "
                "social proof is one of the most reliably cited conversion levers in checkout research.",
                impact="medium", signal_tag="social proof")
    opportunity(personalization, "personalization / cross-sell",
                "No cross-sell or personalization module ('customers also bought', 'recommended for you') is detectable.",
                "Add a 'frequently bought together' or 'you may also like' module -- raises AOV as well as conversion.",
                impact="medium", signal_tag="cross-sell / AOV")
    opportunity(trust_badges, "trust badges",
                "No security/trust badge (SSL seal, 'secure checkout', satisfaction guarantee) is detectable near purchase content.",
                "Add a recognizable security badge and a clear guarantee/return promise near the CTA. Published "
                "2026 research (Visa / Stanford Digital Trust Lab) found this combination roughly halves "
                "security-related checkout abandonment.",
                impact="high", signal_tag="trust")
    opportunity(payment_logos, "payment method logos",
                "No recognizable payment-method logo (Visa/Mastercard/PayPal/UPI/etc.) is detectable.",
                "Display recognizable payment logos near checkout -- familiarity reduces perceived risk at the point of payment.",
                impact="medium", signal_tag="checkout confidence")
    opportunity(guest_checkout, "guest checkout",
                "No 'guest checkout' / 'no account required' messaging is detectable.",
                "Offer and clearly label guest checkout -- forced account creation is one of the most-cited "
                "checkout abandonment reasons in Baymard Institute's usability research.",
                impact="high", signal_tag="checkout friction")
    opportunity(free_shipping, "free shipping messaging",
                "No free-shipping / shipping-threshold messaging is detectable.",
                "If free or threshold-based shipping exists, message it early (PDP, not just cart) -- "
                "surprise shipping costs are a top-cited cause of cart abandonment.",
                impact="medium", signal_tag="checkout confidence")

    metrics = {
        "urgency_detected": urgency,
        "social_proof_detected": social_proof,
        "personalization_detected": personalization,
        "trust_badge_detected": trust_badges,
        "payment_logo_detected": payment_logos,
        "guest_checkout_detected": guest_checkout,
        "free_shipping_messaging_detected": free_shipping,
        "conversion_psychology_signals_present": sum([urgency, social_proof, personalization,
                                                        trust_badges, payment_logos, guest_checkout, free_shipping]),
        "conversion_psychology_signals_total": 7,
    }
    return out, metrics
