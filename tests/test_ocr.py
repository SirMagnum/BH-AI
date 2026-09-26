"""
Unit tests for the upgraded high-performance OCR module.
"""

import unittest
from unittest.mock import MagicMock, patch
from PIL import Image, ImageDraw

from src.ocr import OCRProcessor, OCRBox, OCRBackend


class TestOCR(unittest.TestCase):

    def test_mock_backend(self):
        processor = OCRProcessor(backend=OCRBackend.MOCK)
        self.assertEqual(processor.backend_name, OCRBackend.MOCK.value)
        self.assertFalse(processor.available)

        img = Image.new("RGB", (100, 50), color="white")
        boxes = processor.extract_boxes(img)
        self.assertEqual(boxes, [])

        text = processor.extract_text(img)
        self.assertIn("OCR unavailable", text)

    def test_preprocessing(self):
        processor = OCRProcessor(scale=2.0, backend=OCRBackend.MOCK)
        img = Image.new("RGB", (60, 40), color="blue")
        processed = processor.preprocess(img)

        # Upscaled 2x
        self.assertEqual(processed.size, (120, 80))
        # Greyscale mode
        self.assertEqual(processed.mode, "L")

    def test_tesseract_backend_with_synthetic_image(self):
        # Create synthetic image with readable text
        img = Image.new("RGB", (200, 80), color="white")
        draw = ImageDraw.Draw(img)
        draw.text((20, 30), "TEST 123", fill="black")

        processor = OCRProcessor(backend=OCRBackend.TESSERACT, scale=2.0)
        if not processor.available:
            self.skipTest("Tesseract binary not available in environment")

        self.assertEqual(processor.backend_name, OCRBackend.TESSERACT.value)
        self.assertTrue(processor.available)

        # Test extract_boxes
        boxes = processor.extract_boxes(img)
        self.assertIsInstance(boxes, list)
        self.assertGreater(len(boxes), 0)

        # Assert OCRBox attributes
        first_box = boxes[0]
        self.assertIsInstance(first_box, OCRBox)
        self.assertGreaterEqual(first_box.confidence, 0.0)
        self.assertLessEqual(first_box.confidence, 1.0)
        self.assertEqual(len(first_box.bbox), 4)

        # Test extract_text
        text = processor.extract_text(img)
        self.assertIn("TEST", text.upper())

    def test_rapidocr_mock_dispatch(self):
        processor = OCRProcessor(backend=OCRBackend.MOCK)
        processor._active_backend = OCRBackend.RAPIDOCR
        processor._rapidocr_engine = MagicMock()

        # Mock RapidOCR return format: list of [polygon_points, text, confidence]
        fake_result = [
            [[[10, 10], [50, 10], [50, 30], [10, 30]], "Hello Rapid", 0.98]
        ]
        processor._rapidocr_engine.return_value = (fake_result, None)

        img = Image.new("RGB", (100, 50), color="white")
        boxes = processor.extract_boxes(img)

        self.assertEqual(len(boxes), 1)
        self.assertEqual(boxes[0].text, "Hello Rapid")
        self.assertEqual(boxes[0].confidence, 0.98)
        self.assertEqual(boxes[0].bbox, (10, 10, 40, 20))
        self.assertEqual(boxes[0].level, "line")

        # Test text concatenation
        text = processor.extract_text(img)
        self.assertEqual(text, "Hello Rapid")

    def test_none_image_handling(self):
        processor = OCRProcessor(backend=OCRBackend.MOCK)
        self.assertEqual(processor.extract_boxes(None), [])
        self.assertEqual(processor.extract_text(None), "[OCR unavailable – install Tesseract or rapidocr_onnxruntime]")


if __name__ == "__main__":
    unittest.main()
