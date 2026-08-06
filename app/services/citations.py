from typing import Any


def build_line_lookup(pages: list[dict[str, Any]]) -> dict[int, dict[int, dict[str, Any]]]:
    lookup: dict[int, dict[int, dict[str, Any]]] = {}
    for page in pages:
        page_number = page["page_number"]
        lookup[page_number] = {}
        for line_index, line in enumerate(page.get("lines", [])):
            lookup[page_number][line_index] = {
                "text": line.get("content"),
                "polygon": line.get("polygon", []),
                "spans": line.get("spans", []),
                "page_number": page_number,
                "document_index": page.get("document_index"),
                "source_page_number": page.get("source_page_number"),
                "filename": page.get("filename"),
                "width": page.get("width"),
                "height": page.get("height"),
                "unit": page.get("unit"),
            }
    return lookup


def resolve_citations(
    evidence_items: list[dict[str, Any]],
    line_lookup: dict[int, dict[int, dict[str, Any]]],
) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []

    for evidence in evidence_items or []:
        page_number = evidence.get("page_number")
        line_indices = evidence.get("line_indices") or []
        if not isinstance(page_number, int):
            continue

        for line_index in line_indices:
            if not isinstance(line_index, int):
                continue
            line = line_lookup.get(page_number, {}).get(line_index)
            if not line:
                continue
            citations.append(
                {
                    "page_number": page_number,
                    "line_index": line_index,
                    "text": line["text"],
                    "polygon": line["polygon"],
                    "spans": line["spans"],
                    "document_index": line["document_index"],
                    "source_page_number": line["source_page_number"],
                    "filename": line["filename"],
                    "page_width": line["width"],
                    "page_height": line["height"],
                    "page_unit": line["unit"],
                }
            )

    return citations

