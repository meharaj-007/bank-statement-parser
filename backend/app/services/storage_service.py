import hashlib
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Optional

from ..core.config import settings

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1024 * 1024


class UploadTooLarge(Exception):
    pass


class NotAPDF(Exception):
    pass


class StoredFile:
    def __init__(self, temp_path: Path, file_hash: str, size: int):
        self.temp_path = temp_path
        self.hash = file_hash
        self.size = size


def safe_display_name(filename: Optional[str]) -> str:
    """Basename only, no control characters, capped length. Used for display, never for paths."""
    name = Path((filename or '').replace('\\', '/')).name
    name = re.sub(r'[\x00-\x1f\x7f]', '', name).strip()
    return (name or 'statement.pdf')[:255]


class StorageService:
    """
    Stores uploaded PDFs as UPLOAD_DIR/YYYY/MM/DD/<hash>.pdf.

    Paths are built from the content hash, never from the client filename.
    """

    def __init__(self, base_path: Optional[str] = None):
        self.base_path = Path(base_path or settings.UPLOAD_DIR)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def receive(self, source: BinaryIO, max_size: int = None) -> StoredFile:
        """Stream an upload to a temp file, hashing and size-checking as it goes."""
        max_size = max_size or settings.MAX_UPLOAD_SIZE
        temp_path = self.base_path / f".incoming-{uuid.uuid4().hex}"
        digest = hashlib.sha256()
        size = 0

        try:
            with open(temp_path, 'wb') as out:
                first = True
                while chunk := source.read(CHUNK_SIZE):
                    if first:
                        if not chunk.startswith(b'%PDF-'):
                            raise NotAPDF("File is not a PDF")
                        first = False
                    size += len(chunk)
                    if size > max_size:
                        raise UploadTooLarge(f"File exceeds {max_size // (1024 * 1024)}MB limit")
                    digest.update(chunk)
                    out.write(chunk)
            if size == 0:
                raise NotAPDF("File is empty")
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

        return StoredFile(temp_path, digest.hexdigest(), size)

    def commit(self, stored: StoredFile) -> str:
        """Move a received file into place. Returns the path relative to UPLOAD_DIR."""
        now = datetime.utcnow()
        relative = Path(now.strftime('%Y')) / now.strftime('%m') / now.strftime('%d') / f"{stored.hash}.pdf"
        final_path = self.base_path / relative
        final_path.parent.mkdir(parents=True, exist_ok=True)
        stored.temp_path.replace(final_path)
        logger.info(f"Stored upload at {final_path} ({stored.size} bytes)")
        return relative.as_posix()

    def discard(self, stored: StoredFile) -> None:
        stored.temp_path.unlink(missing_ok=True)

    def absolute_path(self, relative_path: str) -> Path:
        """Resolve a stored relative path, refusing anything outside UPLOAD_DIR."""
        base = self.base_path.resolve()
        path = (base / relative_path).resolve()
        if not path.is_relative_to(base):
            raise ValueError("Path escapes upload directory")
        return path

    def delete(self, relative_path: str) -> None:
        try:
            self.absolute_path(relative_path).unlink(missing_ok=True)
        except Exception as e:
            logger.warning(f"Could not delete {relative_path}: {e}")
