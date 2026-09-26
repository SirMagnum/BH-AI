"""
Unit tests for the local PII redaction pipeline.
"""

import unittest
from src.ocr import OCRBox
from src.privacy.pii import (
    PIIRedactor,
    PIIEntity,
    PIIEntityType,
    RedactionResult,
    is_luhn_valid,
)


class TestPIIRedaction(unittest.TestCase):

    def setUp(self):
        self.redactor = PIIRedactor()

    def test_clean_text(self):
        text = "The quick brown fox jumps over the lazy dog."
        res = self.redactor.redact_text(text)
        self.assertEqual(res.redacted_text, text)
        self.assertFalse(res.has_pii)
        self.assertEqual(len(res.entities), 0)

    def test_email_redaction_and_consistency(self):
        text = "Contact alice@example.com or bob@company.org. Again, send to alice@example.com!"
        res = self.redactor.redact_text(text)

        self.assertTrue(res.has_pii)
        self.assertIn("[EMAIL_ADDR_1]", res.redacted_text)
        self.assertIn("[EMAIL_ADDR_2]", res.redacted_text)
        self.assertNotIn("alice@example.com", res.redacted_text)
        self.assertNotIn("bob@company.org", res.redacted_text)

        # Ensure consistent pseudonymization: alice@example.com replaced with [EMAIL_ADDR_1] both times
        self.assertEqual(res.redacted_text.count("[EMAIL_ADDR_1]"), 2)
        self.assertEqual(res.redacted_text.count("[EMAIL_ADDR_2]"), 1)

    def test_phone_number_redaction(self):
        text = "Call support at (555) 123-4567 or international +1-800-555-0199."
        res = self.redactor.redact_text(text)

        self.assertTrue(res.has_pii)
        self.assertIn("[PHONE_NUM_1]", res.redacted_text)
        self.assertNotIn("(555) 123-4567", res.redacted_text)

    def test_credit_card_with_luhn_validation(self):
        # Valid Visa test card (4111 1111 1111 1111 is Luhn-valid)
        valid_card = "4111 1111 1111 1111"
        self.assertTrue(is_luhn_valid(valid_card))

        # Invalid card (fails Luhn)
        invalid_card = "4111 1111 1111 1112"
        self.assertFalse(is_luhn_valid(invalid_card))

        text = f"Paid with valid card {valid_card} and invoice id {invalid_card}."
        res = self.redactor.redact_text(text)

        self.assertTrue(res.has_pii)
        self.assertIn("[CREDIT_CARD_1]", res.redacted_text)
        self.assertNotIn(valid_card, res.redacted_text)
        # Invalid card number should NOT be flagged as a credit card
        self.assertIn(invalid_card, res.redacted_text)

    def test_api_keys_and_tokens(self):
        text = (
            "OpenAI: sk-abc123456789012345678901234567890, "
            "AWS: AKIAIOSFODNN7EXAMPLE, "
            "GitHub: ghp_123456789012345678901234567890123456"
        )
        res = self.redactor.redact_text(text)

        self.assertTrue(res.has_pii)
        self.assertNotIn("sk-abc", res.redacted_text)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", res.redacted_text)
        self.assertNotIn("ghp_", res.redacted_text)
        self.assertIn("[API_TOKEN_", res.redacted_text)

    def test_credentials_detection(self):
        text = "Login with password: SuperSecretP@ssword123 and user: admin"
        res = self.redactor.redact_text(text)

        self.assertTrue(res.has_pii)
        self.assertNotIn("SuperSecretP@ssword123", res.redacted_text)
        self.assertIn("[CREDENTIAL_1]", res.redacted_text)

    def test_ssn_and_ip_address(self):
        text = "SSN is 123-45-6789 connecting from 192.168.1.100."
        res = self.redactor.redact_text(text)

        self.assertTrue(res.has_pii)
        self.assertNotIn("123-45-6789", res.redacted_text)
        self.assertNotIn("192.168.1.100", res.redacted_text)
        self.assertIn("[SSN_1]", res.redacted_text)
        self.assertIn("[IP_ADDR_1]", res.redacted_text)

    def test_redact_ocr_boxes(self):
        boxes = [
            OCRBox(text="Welcome user", confidence=0.99, bbox=(10, 10, 50, 20)),
            OCRBox(text="Email: test@secure.com", confidence=0.95, bbox=(10, 40, 120, 20)),
        ]

        sanitized_boxes, entities = self.redactor.redact_boxes(boxes)

        self.assertEqual(len(sanitized_boxes), 2)
        self.assertEqual(sanitized_boxes[0].text, "Welcome user")
        self.assertEqual(sanitized_boxes[1].text, "Email: [EMAIL_ADDR_1]")
        # Bounding box spatial coordinates must be preserved for overlay masking
        self.assertEqual(sanitized_boxes[1].bbox, (10, 40, 120, 20))
        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0].entity_type, PIIEntityType.EMAIL)


if __name__ == "__main__":
    unittest.main()
