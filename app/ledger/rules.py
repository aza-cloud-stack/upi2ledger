"""Built-in merchant-to-account rules for common Indian merchants.

These rules provide sensible defaults so new users get auto-categorization
out of the box. User-saved mappings in the DB always override these.

Keys are lowercase substrings matched against the payee name.
Values are hledger account strings.
"""

from __future__ import annotations

BUILTIN_RULES: dict[str, str] = {
    # ── Food & Delivery ──────────────────────────────────────────────
    "swiggy": "expenses:food:delivery",
    "zomato": "expenses:food:delivery",
    "dominos": "expenses:food:delivery",
    "pizza hut": "expenses:food:delivery",
    "dunzo": "expenses:food:delivery",
    "eatsure": "expenses:food:delivery",
    "box8": "expenses:food:delivery",
    "faasos": "expenses:food:delivery",
    "burger king": "expenses:food:delivery",
    "mcdonalds": "expenses:food:delivery",
    "kfc": "expenses:food:delivery",
    "starbucks": "expenses:food:dining",
    # ── Groceries ────────────────────────────────────────────────────
    "bigbasket": "expenses:food:groceries",
    "blinkit": "expenses:food:groceries",
    "zepto": "expenses:food:groceries",
    "instamart": "expenses:food:groceries",
    "jiomart": "expenses:food:groceries",
    "dmart": "expenses:food:groceries",
    "grofers": "expenses:food:groceries",
    "more retail": "expenses:food:groceries",
    "spencers": "expenses:food:groceries",
    # ── Telecom ──────────────────────────────────────────────────────
    "airtel": "expenses:telecom",
    "bharti": "expenses:telecom",
    "jio": "expenses:telecom",
    "vodafone": "expenses:telecom",
    "bsnl": "expenses:telecom",
    # ── Transport ────────────────────────────────────────────────────
    "uber": "expenses:transport",
    "ola": "expenses:transport",
    "rapido": "expenses:transport",
    "irctc": "expenses:transport",
    "redbus": "expenses:transport",
    "makemytrip": "expenses:transport",
    "yatra": "expenses:transport",
    "cleartrip": "expenses:transport",
    "goibibo": "expenses:transport",
    # ── Fuel ─────────────────────────────────────────────────────────
    "indian oil": "expenses:transport:fuel",
    "bharat petroleum": "expenses:transport:fuel",
    "hindustan petroleum": "expenses:transport:fuel",
    "hp petrol": "expenses:transport:fuel",
    # ── Shopping ─────────────────────────────────────────────────────
    "amazon": "expenses:shopping",
    "flipkart": "expenses:shopping",
    "myntra": "expenses:shopping",
    "ajio": "expenses:shopping",
    "meesho": "expenses:shopping",
    "nykaa": "expenses:shopping",
    "croma": "expenses:shopping",
    "reliance digital": "expenses:shopping",
    "snapdeal": "expenses:shopping",
    # ── Entertainment & Subscriptions ────────────────────────────────
    "netflix": "expenses:entertainment:subscriptions",
    "hotstar": "expenses:entertainment:subscriptions",
    "spotify": "expenses:entertainment:subscriptions",
    "youtube": "expenses:entertainment:subscriptions",
    "prime video": "expenses:entertainment:subscriptions",
    "zee5": "expenses:entertainment:subscriptions",
    "sonyliv": "expenses:entertainment:subscriptions",
    "bookmyshow": "expenses:entertainment:outings",
    # ── Utilities ────────────────────────────────────────────────────
    "bescom": "expenses:housing:utilities",
    "electricity": "expenses:housing:utilities",
    "water board": "expenses:housing:utilities",
    "gas cylinder": "expenses:housing:utilities",
    "indane": "expenses:housing:utilities",
    # ── Health ───────────────────────────────────────────────────────
    "apollo": "expenses:health",
    "pharmeasy": "expenses:health",
    "1mg": "expenses:health",
    "netmeds": "expenses:health",
    "practo": "expenses:health",
    "medplus": "expenses:health",
    # ── Insurance ────────────────────────────────────────────────────
    "lic": "expenses:insurance",
    "icici prudential": "expenses:insurance",
    "hdfc life": "expenses:insurance",
    "star health": "expenses:insurance",
    # ── Education ────────────────────────────────────────────────────
    "coursera": "expenses:education",
    "udemy": "expenses:education",
    "unacademy": "expenses:education",
    "byju": "expenses:education",
}
