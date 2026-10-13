import io

import pytest
from pypdf import PdfWriter

from documents import MAX_PDF_PAGES, extract_pdf_text


def make_text_pdf(pages: list[str]) -> bytes:
    """Build a small, valid PDF with one line of text per page."""
    objects: list[bytes] = []
    page_ids = [3 + 2 * i for i in range(len(pages))]
    font_id = 3 + 2 * len(pages)

    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{pid} 0 R" for pid in page_ids).encode()
    objects.append(b"<< /Type /Pages /Kids [" + kids + b"] /Count " + str(len(pages)).encode() + b" >>")
    for i, text in enumerate(pages):
        content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> "
            f"/Contents {page_ids[i] + 1} 0 R >>".encode()
        )
        objects.append(b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def make_blank_pdf(page_count: int) -> bytes:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=612, height=792)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def test_extracts_text_from_every_page():
    pdf = make_text_pdf(["Give Carprofen twice daily with food.", "Recheck in 14 days."])

    text = extract_pdf_text(pdf)

    assert "Carprofen twice daily" in text
    assert "Recheck in 14 days" in text


def test_scanned_pdf_with_no_text_asks_to_paste_instead():
    with pytest.raises(ValueError, match="may be a scan"):
        extract_pdf_text(make_blank_pdf(1))


def test_too_many_pages_is_rejected():
    with pytest.raises(ValueError, match="pages or fewer"):
        extract_pdf_text(make_blank_pdf(MAX_PDF_PAGES + 1))


def test_too_large_is_rejected_before_reading():
    with pytest.raises(ValueError, match="under 2 MB"):
        extract_pdf_text(b"%PDF-1.4" + b"0" * (2 * 1024 * 1024))


def test_non_pdf_file_gets_a_readable_error():
    with pytest.raises(ValueError, match="couldn't be read as a PDF"):
        extract_pdf_text(b"this is just a text file pretending to be a PDF")


def test_password_protected_pdf_asks_to_paste_instead():
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.encrypt("secret")
    out = io.BytesIO()
    writer.write(out)

    with pytest.raises(ValueError, match="password-protected"):
        extract_pdf_text(out.getvalue())
