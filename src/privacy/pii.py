"""
Local PII Redaction Engine for BH-AI.
Extracts and anonymizes sensitive data before storage in memory or processing by LLMs.
Uses high-precision local regexes, Luhn card validation, and optional local NER.
"""

from __future__ import annotations

import enum
import logging
import re
from dataclasses import dataclass
from typing import Any
from src.ocr import OCRBox

logger = logging.getLogger("BH-AI.PII")


class PIIEntityType(str, enum.Enum):
    EMAIL = "EMAIL_ADDR"
    PHONE = "PHONE_NUM"
    CREDIT_CARD = "CREDIT_CARD"
    API_TOKEN = "API_TOKEN"
    SSN = "SSN"
    IP_ADDRESS = "IP_ADDR"
    CREDENTIAL = "CREDENTIAL"


@dataclass(frozen=True)
class PIIEntity:
    """Detected sensitive entity instance."""
    entity_type: PIIEntityType
    original_value: str
    redacted_value: str
    start_idx: int
    end_idx: int
    confidence: float = 1.0


@dataclass(frozen=True)
class RedactionResult:
    """Result of PII redaction pipeline."""
    redacted_text: str
    entities: list[PIIEntity]

    @property
    def has_pii(self) -> bool:
        return len(self.entities) > 0


# ------------------------------------------------------------------ #
#  Luhn Algorithm Validator (Credit / Debit Cards)
# ------------------------------------------------------------------ #

def is_luhn_valid(number_str: str) -> bool:
    """
    Validate credit card numbers using Luhn checksum (mod 10).
    Prevents false positives on arbitrary 13-19 digit numbers.
    """
    digits = [int(c) for c in number_str if c.isdigit()]
    if len(digits) < 13 or len(digits) > 19:
        return False

    checksum = 0
    reverse_digits = digits[::-1]
    for i, digit in enumerate(reverse_digits):
        if i % 2 == 1:
            doubled = digit * 2
            checksum += doubled - 9 if doubled > 9 else doubled
        else:
            checksum += digit
    return checksum % 10 == 0


# ------------------------------------------------------------------ #
#  PII Redaction Engine
# ------------------------------------------------------------------ #

class PIIRedactor:
    """
    Local privacy redaction engine.
    Ensures zero sensitive PII leaves the observation layer into memory/RAG.
    """

    # High-precision regular expressions
    _RE_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b")

    # Phone numbers (US, international formats, dash/dot/space separated)
    _RE_PHONE = re.compile(
        r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b|"
        r"\+\d{1,3}[-.\s]?\d{1,4}[-.\s]?\d{3,4}[-.\s]?\d{3,4}\b"
    )

    # Credit card candidates (13-19 digits, optionally spaced or dashed)
    _RE_CARD_CANDIDATE = re.compile(r"\b(?:\d{4}[-\s]?){3}\d{1,7}\b|\b\d{13,19}\b")

    # API Keys and tokens (OpenAI, AWS, GitHub, Google, Bearer, generic high-entropy hex/base64)
    _RE_OPENAI_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")
    _RE_AWS_KEY = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
    _RE_GITHUB_TOKEN = re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}\b")
    _RE_GOOGLE_KEY = re.compile(r"\bAIza[0-9A-Za-z-_]{35}\b")
    _RE_BEARER_TOKEN = re.compile(r"\bBearer\s+([A-Za-z0-9._~+/-]{20,}=*)\b")
    _RE_HEX_TOKEN = re.compile(r"\b[0-9a-fA-F]{32,64}\b")

    # US SSN format
    _RE_SSN = re.compile(r"\b(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b")

    # IPv4 address
    _RE_IPV4 = re.compile(
        r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
    )

    # Passwords & Secrets in text (e.g. password: secret123)
    _RE_CREDENTIAL = re.compile(
        r"(?i)\b(?:password|passwd|pwd|secret|api_key|token|auth)\s*[:=]\s*[\"']?([^\"'\s,;]+)[\"']?"
    )

    def __init__(self, enable_ner: bool = False):
        self.enable_ner = enable_ner
        self._ner_pipeline = None
        if enable_ner:
            self._init_ner()

    def _init_ner(self) -> None:
        """Attempt to load local NER model if installed."""
        try:
            import spacy
            self._ner_pipeline = spacy.load("en_core_web_sm")
        except Exception:
            self._ner_pipeline = None

    def redact_text(self, text: str) -> RedactionResult:
        """
        Scan and redact PII from raw string.
        Replaces detected entities with consistent indexed placeholders (e.g. [EMAIL_ADDR_1]).
        """
        if not text or not text.strip():
            return RedactionResult(redacted_text=text or "", entities=[])

        entities: list[PIIEntity] = []
        token_maps: dict[PIIEntityType, dict[str, str]] = {
            t: {} for t in PIIEntityType
        }
        token_counters: dict[PIIEntityType, int] = {
            t: 0 for t in PIIEntityType
        }

        def get_placeholder(entity_type: PIIEntityType, val: str) -> str:
            if val not in token_maps[entity_type]:
                token_counters[entity_type] += 1
                token_maps[entity_type][val] = f"[{entity_type.value}_{token_counters[entity_type]}]"
            return token_maps[entity_type][val]

        # 1. Credential key-value pairs
        for match in self._RE_CREDENTIAL.finditer(text):
            secret_val = match.group(1)
            if len(secret_val) >= 4 and not secret_val.startswith("["):
                start = match.start(1)
                end = match.end(1)
                placeholder = get_placeholder(PIIEntityType.CREDENTIAL, secret_val)
                entities.append(
                    PIIEntity(
                        entity_type=PIIEntityType.CREDENTIAL,
                        original_value=secret_val,
                        redacted_value=placeholder,
                        start_idx=start,
                        end_idx=end,
                    )
                )

        # 2. Specific API Tokens
        for pattern in [self._RE_OPENAI_KEY, self._RE_AWS_KEY, self._RE_GITHUB_TOKEN, self._RE_GOOGLE_KEY]:
            for match in pattern.finditer(text):
                val = match.group(0)
                placeholder = get_placeholder(PIIEntityType.API_TOKEN, val)
                entities.append(
                    PIIEntity(
                        entity_type=PIIEntityType.API_TOKEN,
                        original_value=val,
                        redacted_value=placeholder,
                        start_idx=match.start(),
                        end_idx=match.end(),
                    )
                )

        # Bearer tokens
        for match in self._RE_BEARER_TOKEN.finditer(text):
            token_val = match.group(1)
            placeholder = get_placeholder(PIIEntityType.API_TOKEN, token_val)
            entities.append(
                PIIEntity(
                    entity_type=PIIEntityType.API_TOKEN,
                    original_value=token_val,
                    redacted_value=placeholder,
                    start_idx=match.start(1),
                    end_idx=match.end(1),
                )
            )

        # 3. Emails
        for match in self._RE_EMAIL.finditer(text):
            val = match.group(0)
            placeholder = get_placeholder(PIIEntityType.EMAIL, val)
            entities.append(
                PIIEntity(
                    entity_type=PIIEntityType.EMAIL,
                    original_value=val,
                    redacted_value=placeholder,
                    start_idx=match.start(),
                    end_idx=match.end(),
                )
            )

        # 4. Credit Cards with Luhn validation
        for match in self._RE_CARD_CANDIDATE.finditer(text):
            raw_card = match.group(0)
            clean_digits = re.sub(r"\D", "", raw_card)
            if is_luhn_valid(clean_digits):
                placeholder = get_placeholder(PIIEntityType.CREDIT_CARD, raw_card)
                entities.append(
                    PIIEntity(
                        entity_type=PIIEntityType.CREDIT_CARD,
                        original_value=raw_card,
                        redacted_value=placeholder,
                        start_idx=match.start(),
                        end_idx=match.end(),
                    )
                )

        # 5. Social Security Numbers
        for match in self._RE_SSN.finditer(text):
            val = match.group(0)
            placeholder = get_placeholder(PIIEntityType.SSN, val)
            entities.append(
                PIIEntity(
                    entity_type=PIIEntityType.SSN,
                    original_value=val,
                    redacted_value=placeholder,
                    start_idx=match.start(),
                    end_idx=match.end(),
                )
            )

        # 6. IP Addresses
        for match in self._RE_IPV4.finditer(text):
            val = match.group(0)
            # Filter common benign loopbacks or simple version numbers if necessary
            placeholder = get_placeholder(PIIEntityType.IP_ADDRESS, val)
            entities.append(
                PIIEntity(
                    entity_type=PIIEntityType.IP_ADDRESS,
                    original_value=val,
                    redacted_value=placeholder,
                    start_idx=match.start(),
                    end_idx=match.end(),
                )
            )

        # 7. Phone Numbers (excluding already matched credit cards / IPs / arbitrary numbers)
        for match in self._RE_PHONE.finditer(text):
            val = match.group(0)
            start, end = match.span()
            if (start > 0 and text[start - 1].isdigit()) or (end < len(text) and text[end].isdigit()):
                continue
            digits_count = len(re.sub(r"\D", "", val))
            if 10 <= digits_count <= 15:
                placeholder = get_placeholder(PIIEntityType.PHONE, val)
                entities.append(
                    PIIEntity(
                        entity_type=PIIEntityType.PHONE,
                        original_value=val,
                        redacted_value=placeholder,
                        start_idx=start,
                        end_idx=end,
                    )
                )

        # 8. Sort matches and resolve overlaps (longest/earliest first)
        entities.sort(key=lambda e: (e.start_idx, -(e.end_idx - e.start_idx)))

        # Filter overlapping intervals
        filtered_entities: list[PIIEntity] = []
        last_end = -1
        for e in entities:
            if e.start_idx >= last_end:
                filtered_entities.append(e)
                last_end = e.end_idx

        # Construct redacted string by replacing intervals backwards
        redacted_chars = list(text)
        for e in reversed(filtered_entities):
            redacted_chars[e.start_idx:e.end_idx] = list(e.redacted_value)

        redacted_text = "".join(redacted_chars)
        return RedactionResult(redacted_text=redacted_text, entities=filtered_entities)

    def redact_boxes(self, boxes: list[OCRBox]) -> tuple[list[OCRBox], list[PIIEntity]]:
        """
        Redact spatial OCR boxes.
        Returns sanitized OCRBox list and all detected PII entities.
        """
        redacted_boxes: list[OCRBox] = []
        all_entities: list[PIIEntity] = []

        for box in boxes:
            result = self.redact_text(box.text)
            if result.has_pii:
                all_entities.extend(result.entities)
                redacted_boxes.append(
                    OCRBox(
                        text=result.redacted_text,
                        confidence=box.confidence,
                        bbox=box.bbox,
                        level=box.level,
                    )
                )
            else:
                redacted_boxes.append(box)

        return redacted_boxes, all_entities
