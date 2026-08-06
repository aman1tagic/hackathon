from dataclasses import dataclass
from io import BytesIO

from pypdf import PdfReader, PdfWriter


@dataclass(frozen=True)
class PagePayload:
    source_page_number: int
    content: bytes
    content_type: str


def is_pdf(filename: str | None, content_type: str | None, content: bytes) -> bool:
    if content.startswith(b"%PDF"):
        return True
    if content_type == "application/pdf":
        return True
    return bool(filename and filename.lower().endswith(".pdf"))


def split_pdf_into_pages(content: bytes) -> list[PagePayload]:
    reader = PdfReader(BytesIO(content))
    pages: list[PagePayload] = []

    for index, page in enumerate(reader.pages, start=1):
        writer = PdfWriter()
        writer.add_page(page)

        output = BytesIO()
        writer.write(output)
        pages.append(
            PagePayload(
                source_page_number=index,
                content=output.getvalue(),
                content_type="application/pdf",
            )
        )

    return pages


def single_image_page(content: bytes, content_type: str | None) -> PagePayload:
    return PagePayload(
        source_page_number=1,
        content=content,
        content_type=content_type or "application/octet-stream",
    )

