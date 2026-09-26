"""
High-Performance OCR Module for BH-AI.
Supports multi-backend execution:
  - RapidOCR (PP-OCRv4 via ONNX runtime) for high-performance line/block detection
  - Tesseract (pytesseract) as standard local fallback
  - Mock backend for deterministic testing / fallback

Extracts both raw plain-text and structured bounding boxes (OCRBox) for downstream
local PII redaction and spatial HUD overlay highlighting.
"""

from __future__ import annotations

import enum
import logging
import os
import threading
from dataclasses import dataclass
from typing import Any
from PIL import Image, ImageEnhance, ImageFilter

logger = logging.getLogger("BH-AI.OCR")


@dataclass(frozen=True)
class OCRBox:
    """Represents an extracted text token or line with spatial coordinates."""
    text: str
    confidence: float                         # 0.0 - 1.0
    bbox: tuple[int, int, int, int]           # (left, top, width, height) in original image coords
    level: str = "word"                       # "word" | "line" | "block"


class OCRBackend(str, enum.Enum):
    AUTO = "auto"
    RAPIDOCR = "rapidocr"
    TESSERACT = "tesseract"
    MOCK = "mock"


# ------------------------------------------------------------------ #
#  Backend Availability Discovery
# ------------------------------------------------------------------ #

_RAPIDOCR_AVAILABLE = False
_RapidOCRClass = None
try:
    # pyrefly: ignore [missing-import]
    from rapidocr_onnxruntime import RapidOCR as _RapidOCRClass
    _RAPIDOCR_AVAILABLE = True
except Exception:
    _RAPIDOCR_AVAILABLE = False


_TESSERACT_AVAILABLE = False
try:
    import pytesseract

    # Check common Tesseract install paths on Windows if not already on PATH
    _CANDIDATE_PATHS = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Tesseract-OCR", "tesseract.exe"),
    ]
    for _p in _CANDIDATE_PATHS:
        if os.path.isfile(_p):
            pytesseract.pytesseract.tesseract_cmd = _p
            break

    pytesseract.get_tesseract_version()
    _TESSERACT_AVAILABLE = True
except Exception:
    _TESSERACT_AVAILABLE = False


# ------------------------------------------------------------------ #
#  OCR Processor
# ------------------------------------------------------------------ #

class OCRProcessor:
    """
    Thread-safe OCR processor with multi-backend execution
    and structured bounding-box spatial extraction.
    """

    def __init__(
        self,
        lang: str = "eng",
        scale: float = 2.0,
        backend: OCRBackend | str = OCRBackend.AUTO,
    ):
        """
        :param lang: Language string (e.g. 'eng')
        :param scale: Upscale factor for preprocessing image before recognition
        :param backend: OCRBackend selection ('auto', 'rapidocr', 'tesseract', 'mock')
        """
        self.lang = lang
        self.scale = max(scale, 1.0)
        if isinstance(backend, OCRBackend):
            self._backend_pref = backend
        else:
            self._backend_pref = OCRBackend(str(backend).lower())
        self._lock = threading.RLock()
        self._rapidocr_engine: Any = None
        self._active_backend: OCRBackend = self._resolve_backend()

    def _resolve_backend(self) -> OCRBackend:
        """Determine the active backend based on preference and library availability."""
        if self._backend_pref == OCRBackend.MOCK:
            return OCRBackend.MOCK

        if self._backend_pref == OCRBackend.RAPIDOCR:
            if _RAPIDOCR_AVAILABLE:
                self._init_rapidocr()
                return OCRBackend.RAPIDOCR
            logger.warning("[OCR] RapidOCR requested but not installed. Falling back to Auto.")

        if self._backend_pref == OCRBackend.TESSERACT:
            if _TESSERACT_AVAILABLE:
                return OCRBackend.TESSERACT
            logger.warning("[OCR] Tesseract requested but not available. Falling back to Auto.")

        # AUTO selection
        if _RAPIDOCR_AVAILABLE:
            try:
                self._init_rapidocr()
                return OCRBackend.RAPIDOCR
            except Exception as exc:
                logger.warning(f"[OCR] Failed to initialize RapidOCR: {exc}")

        if _TESSERACT_AVAILABLE:
            return OCRBackend.TESSERACT

        return OCRBackend.MOCK

    def _init_rapidocr(self) -> None:
        """Initialize RapidOCR engine if not already loaded."""
        if self._rapidocr_engine is None and _RapidOCRClass is not None:
            self._rapidocr_engine = _RapidOCRClass()

    # ------------------------------------------------------------------ #
    #  Inspection Properties
    # ------------------------------------------------------------------ #

    @property
    def available(self) -> bool:
        """Returns True if a real OCR backend (RapidOCR or Tesseract) is operational."""
        return self._active_backend in (OCRBackend.RAPIDOCR, OCRBackend.TESSERACT)

    @property
    def backend_name(self) -> str:
        """Return the active backend name."""
        return self._active_backend.value

    # ------------------------------------------------------------------ #
    #  Preprocessing
    # ------------------------------------------------------------------ #

    def preprocess(self, image: Image.Image) -> Image.Image:
        """Upscale + sharpen + contrast enhancement in greyscale."""
        w, h = image.size
        processed = image.resize(
            (int(w * self.scale), int(h * self.scale)),
            Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
        )
        processed = processed.convert("L")
        processed = ImageEnhance.Contrast(processed).enhance(1.8)
        processed = processed.filter(ImageFilter.SHARPEN)
        return processed

    # ------------------------------------------------------------------ #
    #  Text & Box Extraction
    # ------------------------------------------------------------------ #

    def extract_text(self, image: Image.Image) -> str:
        """
        Extract full plain text string from PIL image.
        Fully backward-compatible with UI and context analyzer.
        """
        boxes = self.extract_boxes(image)
        if not boxes:
            if not self.available:
                return "[OCR unavailable – install Tesseract or rapidocr_onnxruntime]"
            return ""

        # Join text lines/tokens
        return " ".join(box.text for box in boxes if box.text.strip()).strip()

    def extract_boxes(self, image: Image.Image) -> list[OCRBox]:
        """
        Extract structured bounding boxes and text from image.
        Returned bounding boxes are mapped back to original image dimensions.
        """
        if image is None:
            return []

        with self._lock:
            if self._active_backend == OCRBackend.RAPIDOCR:
                return self._extract_rapidocr(image)
            elif self._active_backend == OCRBackend.TESSERACT:
                return self._extract_tesseract(image)
            else:
                return self._extract_mock(image)

    # ------------------------------------------------------------------ #
    #  Backend Implementations
    # ------------------------------------------------------------------ #

    def _extract_tesseract(self, image: Image.Image) -> list[OCRBox]:
        """Tesseract implementation using image_to_data for spatial bounding boxes."""
        import pytesseract

        processed = self.preprocess(image)
        try:
            data = pytesseract.image_to_data(
                processed,
                lang=self.lang,
                config="--psm 6",
                output_type=pytesseract.Output.DICT,
            )

            boxes: list[OCRBox] = []
            inv_scale = 1.0 / self.scale
            n_boxes = len(data["text"])

            for i in range(n_boxes):
                text = (data["text"][i] or "").strip()
                if not text:
                    continue

                conf_val = float(data["conf"][i])
                confidence = max(conf_val / 100.0, 0.0) if conf_val >= 0 else 0.5

                left = int(data["left"][i] * inv_scale)
                top = int(data["top"][i] * inv_scale)
                width = int(data["width"][i] * inv_scale)
                height = int(data["height"][i] * inv_scale)

                boxes.append(
                    OCRBox(
                        text=text,
                        confidence=round(confidence, 2),
                        bbox=(left, top, width, height),
                        level="word",
                    )
                )

            return boxes
        except Exception as exc:
            logger.error(f"[OCR] Tesseract extraction failed: {exc}")
            return []

    def _extract_rapidocr(self, image: Image.Image) -> list[OCRBox]:
        """RapidOCR (PP-OCRv4) inference for line and block bounding boxes."""
        if self._rapidocr_engine is None:
            self._init_rapidocr()

        try:
            import numpy as np
            img_np = np.array(image.convert("RGB"))
            ocr_results, _ = self._rapidocr_engine(img_np)
            if not ocr_results:
                return []

            boxes: list[OCRBox] = []
            for item in ocr_results:
                # RapidOCR format: [poly_points, text, confidence]
                # poly_points: [[x1, y1], [x2, y2], [x3, y3], [x4, y4]]
                points, text, conf = item
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                left = int(min(xs))
                top = int(min(ys))
                width = int(max(xs) - left)
                height = int(max(ys) - top)

                boxes.append(
                    OCRBox(
                        text=str(text).strip(),
                        confidence=round(float(conf), 2),
                        bbox=(left, top, width, height),
                        level="line",
                    )
                )
            return boxes
        except Exception as exc:
            logger.error(f"[OCR] RapidOCR extraction failed: {exc}")
            return []

    def _extract_mock(self, image: Image.Image) -> list[OCRBox]:
        """Mock backend for headless CI/testing or when no engines exist."""
        return []
