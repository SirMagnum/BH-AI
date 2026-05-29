"""
OCR Module
Extracts text from PIL Images using pytesseract.
Falls back gracefully when Tesseract is not installed.
"""

from PIL import Image, ImageEnhance, ImageFilter
import threading

# Try importing pytesseract; mark unavailable if Tesseract not installed.
_TESSERACT_AVAILABLE = False
try:
    import pytesseract
    import os

    # Common Tesseract install locations on Windows
    _CANDIDATE_PATHS = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Tesseract-OCR", "tesseract.exe"),
    ]

    for _path in _CANDIDATE_PATHS:
        if os.path.isfile(_path):
            pytesseract.pytesseract.tesseract_cmd = _path
            break

    # Verify the binary actually works
    pytesseract.get_tesseract_version()
    _TESSERACT_AVAILABLE = True

except Exception:
    _TESSERACT_AVAILABLE = False


class OCRProcessor:
    """Thread-safe OCR processor."""

    def __init__(self, lang: str = "eng", scale: float = 2.0):
        """
        :param lang: Tesseract language string
        :param scale: upscale factor for better OCR accuracy
        """
        self.lang = lang
        self.scale = scale
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return _TESSERACT_AVAILABLE

    def preprocess(self, image: Image.Image) -> Image.Image:
        """Upscale + sharpen + convert to greyscale for better OCR."""
        w, h = image.size
        image = image.resize((int(w * self.scale), int(h * self.scale)), Image.LANCZOS)
        image = image.convert("L")
        image = ImageEnhance.Contrast(image).enhance(2.0)
        image = image.filter(ImageFilter.SHARPEN)
        return image

    def extract_text(self, image: Image.Image) -> str:
        """
        Run OCR on a PIL image and return extracted text.
        Returns placeholder string when Tesseract is unavailable.
        """
        if not _TESSERACT_AVAILABLE:
            return "[OCR unavailable – install Tesseract and pytesseract]"

        with self._lock:
            processed = self.preprocess(image)
            try:
                text = pytesseract.image_to_string(
                    processed,
                    lang=self.lang,
                    config="--psm 6",
                )
                return text.strip()
            except Exception as exc:
                return f"[OCR error: {exc}]"
