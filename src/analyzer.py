"""
Context Analyzer Module
Keyword-based logic to detect page/form type from OCR text.
Returns structured insight objects consumed by the UI and voice modules.
"""

import re
from dataclasses import dataclass, field


# ------------------------------------------------------------------ #
#  Data types
# ------------------------------------------------------------------ #

@dataclass
class Insight:
    label: str          # Human-readable category
    confidence: float   # 0.0 – 1.0
    keywords: list[str] = field(default_factory=list)
    suggestion: str = ""
    highlight_hint: str = ""   # "top" | "form" | "search" | "password" | ""


# ------------------------------------------------------------------ #
#  Rule definitions
# ------------------------------------------------------------------ #

_RULES: list[dict] = [
    {
        "label": "Login / Authentication Page",
        "keywords": [
            "login", "log in", "sign in", "signin", "username", "password",
            "forgot password", "remember me", "authentication", "credentials",
        ],
        "suggestion": "This looks like a login page. Make sure you're on the correct site before entering credentials.",
        "highlight_hint": "password",
    },
    {
        "label": "Search Interface",
        "keywords": [
            "search", "find", "query", "look up", "explore", "browse",
            "search results", "results for",
        ],
        "suggestion": "A search interface is detected. Refine your query for better results.",
        "highlight_hint": "search",
    },
    {
        "label": "Registration / Sign-Up Form",
        "keywords": [
            "register", "sign up", "signup", "create account", "new account",
            "confirm password", "email address", "date of birth", "full name",
        ],
        "suggestion": "This appears to be a registration form. Review all fields before submitting.",
        "highlight_hint": "form",
    },
    {
        "label": "Payment / Checkout Form",
        "keywords": [
            "credit card", "debit card", "card number", "cvv", "expiry",
            "billing", "checkout", "pay now", "total", "order summary",
            "shipping address",
        ],
        "suggestion": "Payment form detected. Verify the site is secure (HTTPS) before entering card details.",
        "highlight_hint": "form",
    },
    {
        "label": "Error / Alert Page",
        "keywords": [
            "error", "404", "403", "500", "not found", "access denied",
            "forbidden", "something went wrong", "try again", "oops",
        ],
        "suggestion": "An error state is visible on screen. Check your connection or try refreshing.",
        "highlight_hint": "top",
    },
    {
        "label": "Email / Messaging Interface",
        "keywords": [
            "inbox", "compose", "reply", "forward", "subject", "send",
            "unread", "cc", "bcc", "attachment", "draft",
        ],
        "suggestion": "Email or messaging interface detected.",
        "highlight_hint": "top",
    },
    {
        "label": "Settings / Preferences",
        "keywords": [
            "settings", "preferences", "configuration", "privacy", "security",
            "notifications", "account settings", "theme", "language",
        ],
        "suggestion": "Settings panel detected. Review privacy options regularly.",
        "highlight_hint": "top",
    },
    {
        "label": "Document / Text Editor",
        "keywords": [
            "file", "save", "undo", "redo", "font", "paragraph",
            "bold", "italic", "format", "print", "document",
        ],
        "suggestion": "Document editor detected. Remember to save your work frequently.",
        "highlight_hint": "",
    },
    {
        "label": "Code / Developer Tool",
        "keywords": [
            "function", "class", "import", "const", "var", "let",
            "return", "def ", "console", "debug", "terminal",
        ],
        "suggestion": "Developer environment detected.",
        "highlight_hint": "",
    },
]


# ------------------------------------------------------------------ #
#  Analyzer
# ------------------------------------------------------------------ #

class ContextAnalyzer:
    """
    Scores OCR text against keyword rules and returns ranked Insights.
    """

    def __init__(self, top_n: int = 3):
        self.top_n = top_n

    def analyze(self, text: str) -> list[Insight]:
        """
        :param text: Raw OCR output string
        :returns: List of Insight objects sorted by confidence, best first.
        """
        if not text or len(text.strip()) < 5:
            return []

        lower = text.lower()
        results: list[Insight] = []

        for rule in _RULES:
            matched = [kw for kw in rule["keywords"] if kw in lower]
            if not matched:
                continue

            confidence = min(len(matched) / max(len(rule["keywords"]) * 0.5, 1), 1.0)
            results.append(
                Insight(
                    label=rule["label"],
                    confidence=round(confidence, 2),
                    keywords=matched,
                    suggestion=rule["suggestion"],
                    highlight_hint=rule["highlight_hint"],
                )
            )

        results.sort(key=lambda r: r.confidence, reverse=True)
        return results[: self.top_n]

    def summarize(self, insights: list[Insight]) -> str:
        """Return a brief human-readable summary of the top insight."""
        if not insights:
            return "No specific context detected in the current view."
        top = insights[0]
        return (
            f"Detected: {top.label} "
            f"({int(top.confidence * 100)}% confidence). "
            f"{top.suggestion}"
        )
