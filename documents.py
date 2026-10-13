"""Getting text out of files people upload, such as a vet's discharge PDF.

The app keeps only the extracted text, never the file itself: a discharge
sheet often includes the owner's name, address, and phone number in its
letterhead, and there's no reason to store more than the instructions.
"""

from __future__ import annotations

import io

MAX_PDF_BYTES = 2 * 1024 * 1024  # 2 MB
MAX_PDF_PAGES = 10


def extract_pdf_text(data: bytes) -> str:
    """Return the text in a PDF, or raise ValueError with a readable reason."""
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    if len(data) > MAX_PDF_BYTES:
        raise ValueError("That PDF is too large. Please use a file under 2 MB.")

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ValueError(
                "That PDF is password-protected. Please paste the text instead."
            )
        if len(reader.pages) > MAX_PDF_PAGES:
            raise ValueError(
                f"That PDF has {len(reader.pages)} pages. Please use one with "
                f"{MAX_PDF_PAGES} pages or fewer, or paste just the aftercare part."
            )
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
    except ValueError:
        raise
    except (PdfReadError, Exception) as exc:  # damaged or not really a PDF
        raise ValueError("That file couldn't be read as a PDF.") from exc

    text = "\n\n".join(page for page in pages if page)
    if not text.strip():
        raise ValueError(
            "No text was found in that PDF. It may be a scan or a photo. "
            "Please type or paste the instructions instead."
        )
    return text
