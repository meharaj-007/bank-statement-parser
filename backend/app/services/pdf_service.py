import io
import logging
import shutil
from pathlib import Path
from typing import List

import fitz  # PyMuPDF
from PIL import Image

from ..core.config import settings

logger = logging.getLogger(__name__)


class PDFProcessingService:
    """Renders PDF pages to JPEG images sized for the vision model."""

    def __init__(self, dpi: int = None, max_pages: int = None, max_image_bytes: int = None):
        self.dpi = dpi or settings.PDF_DPI
        self.max_pages = max_pages or settings.MAX_PAGES
        self.max_image_bytes = max_image_bytes or settings.MAX_IMAGE_BYTES

    def page_count(self, pdf_path: str) -> int:
        with fitz.open(pdf_path) as doc:
            return len(doc)

    def render_pages(self, pdf_path: str, output_dir: Path) -> List[str]:
        """
        Render every page to `output_dir/page_NNN.jpg`.

        Returns:
            Image paths in page order
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        with fitz.open(pdf_path) as doc:
            if doc.needs_pass:
                raise ValueError("PDF is password protected")
            if len(doc) == 0:
                raise ValueError("PDF has no pages")
            if len(doc) > self.max_pages:
                raise ValueError(f"PDF has {len(doc)} pages, exceeding maximum of {self.max_pages}")

            image_paths = []
            zoom = self.dpi / 72
            for index, page in enumerate(doc):
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
                image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

                image_path = output_dir / f"page_{index + 1:03d}.jpg"
                image_path.write_bytes(self._encode_within_limit(image))
                image_paths.append(str(image_path))

        logger.info(f"Rendered {len(image_paths)} pages from {pdf_path}")
        return image_paths

    def _encode_within_limit(self, image: Image.Image) -> bytes:
        """JPEG-encode, shrinking the image until it fits the size limit."""
        quality = settings.JPEG_QUALITY
        while True:
            buffer = io.BytesIO()
            image.save(buffer, "JPEG", quality=quality, optimize=True)
            data = buffer.getvalue()
            if len(data) <= self.max_image_bytes or min(image.size) < 500:
                return data
            image = image.resize((int(image.width * 0.8), int(image.height * 0.8)), Image.LANCZOS)

    @staticmethod
    def cleanup(output_dir: Path) -> None:
        if not settings.CLEANUP_TEMP_FILES:
            return
        shutil.rmtree(output_dir, ignore_errors=True)
