"""Deterministic brand extraction from a product title.

Aggregator sources (Google Shopping) don't return a clean brand field, so
ingested products would otherwise show "Unknown". Retail titles almost always
lead with the brand ("Dell 15 Laptop…", "Ninja Air Fryer Pro…"), so a small
known-brand lookup plus a first-token fallback recovers it cheaply — no LLM call.
"""

from __future__ import annotations

import re

# Curated multi-word / well-known brands. Matched case-insensitively anywhere in
# the title (checked before the first-token fallback so "Amazon Basics" beats
# "Amazon" and multi-word brands aren't split). Lowercase keys; display values
# preserve real casing.
_KNOWN_BRANDS = {
    "amazon basics": "Amazon Basics", "amazonbasics": "Amazon Basics",
    # Product lines that imply a brand.
    "iphone": "Apple", "ipad": "Apple", "macbook": "Apple", "airpods": "Apple",
    "imac": "Apple", "galaxy": "Samsung", "kindle": "Amazon", "echo": "Amazon",
    "samsung": "Samsung", "lg": "LG", "sony": "Sony", "apple": "Apple",
    "dell": "Dell", "hp": "HP", "lenovo": "Lenovo", "asus": "ASUS",
    "acer": "Acer", "microsoft": "Microsoft", "razer": "Razer", "msi": "MSI",
    "vizio": "VIZIO", "tcl": "TCL", "hisense": "Hisense", "insignia": "Insignia",
    "roku": "Roku", "pioneer": "Pioneer", "onn": "onn.",
    "ninja": "Ninja", "instant pot": "Instant Pot", "cosori": "COSORI",
    "gourmia": "Gourmia", "powerxl": "PowerXL", "cuisinart": "Cuisinart",
    "kitchenaid": "KitchenAid", "breville": "Breville", "keurig": "Keurig",
    "dyson": "Dyson", "shark": "Shark", "irobot": "iRobot", "roomba": "iRobot",
    "bissell": "Bissell", "eufy": "eufy", "tineco": "Tineco",
    "bose": "Bose", "sennheiser": "Sennheiser", "jbl": "JBL", "beats": "Beats",
    "anker": "Anker", "soundcore": "Soundcore", "tozo": "TOZO",
    "google": "Google", "garmin": "Garmin", "fitbit": "Fitbit",
    "logitech": "Logitech", "nintendo": "Nintendo", "playstation": "PlayStation",
    "xbox": "Xbox", "gopro": "GoPro", "canon": "Canon", "nikon": "Nikon",
}

# Title tokens that are never a brand (units, descriptors) — skipped by the
# first-token fallback so we don't pick e.g. "65" from "65 inch tv".
_NON_BRAND_TOKENS = {
    "the", "new", "for", "with", "and", "all", "best", "open", "refurbished",
    "certified", "pro", "max", "plus", "mini", "inch", "qt", "cu", "ft",
}


# Tokens that look like a model code but aren't (spec abbreviations).
_NOT_A_MODEL = {
    "HDR10", "USB3", "USB2", "DDR4", "DDR5", "AC1200", "AC1900",  # keep AC routers? rare
}
# A model code: 2-5 leading letters + 2+ digits + optional trailing alphanumerics
# (EG201, AF141, QN65Q80D, RX6700). Excludes pure sizes ("65", "4K") and the
# spec abbreviations above.
_MODEL_RE = re.compile(r"\b([A-Z]{2,5}[- ]?\d{2,}[A-Z0-9]{0,6})\b")


def extract_model(name: str) -> str:
    """Best-effort manufacturer model code from a title (e.g. 'EG201', 'QN65Q80D').
    Returns '' when none is confidently present."""
    if not name:
        return ""
    best = ""
    for m in _MODEL_RE.finditer(name):
        tok = m.group(1).replace(" ", "").replace("-", "")
        if tok.upper() in _NOT_A_MODEL:
            continue
        # Prefer the longest plausible code (real models carry more entropy).
        if len(tok) > len(best):
            best = tok
    return best


def extract_brand(name: str, fallback: str = "Unknown") -> str:
    """Best-effort brand from a product title.

    1) longest known-brand phrase found in the title, else
    2) the first alphabetic token (capitalized), else
    3) ``fallback``.
    """
    if not name:
        return fallback
    low = name.lower()

    # 1) Known brands — prefer the longest match (so "instant pot" wins over a
    #    bare token, and multi-word brands stay intact).
    matches = [disp for key, disp in _KNOWN_BRANDS.items()
               if re.search(rf"\b{re.escape(key)}\b", low)]
    if matches:
        return max(matches, key=len)

    # 2) First meaningful token. Brands are often ALLCAPS or Capitalized; accept
    #    a leading alphabetic token that isn't a generic descriptor.
    for tok in re.findall(r"[A-Za-z][A-Za-z'&.\-]*", name):
        if tok.lower() in _NON_BRAND_TOKENS or len(tok) < 2:
            continue
        # Preserve ALLCAPS (VIZIO), else title-case (dell -> Dell).
        return tok if tok.isupper() else tok[:1].upper() + tok[1:]

    return fallback
