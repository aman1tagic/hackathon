from typing import Any


def compact_page(page: dict[str, Any]) -> dict[str, Any]:
    return {
        "page_number": page["page_number"],
        "document_index": page.get("document_index"),
        "filename": page.get("filename"),
        "source_page_number": page.get("source_page_number"),
        "azure_page_number": page.get("azure_page_number"),
        "ocr_text": page.get("ocr_text", ""),
        "width": page.get("width"),
        "height": page.get("height"),
        "unit": page.get("unit"),
        "lines": [
            {
                "line_index": line_index,
                "text": line.get("content", ""),
            }
            for line_index, line in enumerate(page.get("lines", []))
        ],
    }


def compact_document(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "document_index": document.get("document_index"),
        "filename": document.get("filename"),
        "content_type": document.get("content_type"),
        "page_count": document.get("page_count"),
        "failed_pages": document.get("failed_pages", []),
    }


def shape_ocr_response(
    full_ocr_response: dict[str, Any],
    ocr_id: str | None,
    response_mode: str,
) -> dict[str, Any]:
    if response_mode == "full":
        response = dict(full_ocr_response)
        response["ocr_id"] = ocr_id
        response["response_mode"] = "full"
        response["documents"] = [
            compact_document(document) for document in full_ocr_response.get("documents", [])
        ]
        return response

    return {
        "ocr_id": ocr_id,
        "response_mode": "compact",
        "claim_id": full_ocr_response.get("claim_id"),
        "status": full_ocr_response.get("status"),
        "model": full_ocr_response.get("model"),
        "total_documents": full_ocr_response.get("total_documents"),
        "total_pages": full_ocr_response.get("total_pages"),
        "succeeded_pages": full_ocr_response.get("succeeded_pages"),
        "failed_pages": full_ocr_response.get("failed_pages"),
        "pages": [compact_page(page) for page in full_ocr_response.get("pages", [])],
        "documents": [
            compact_document(document) for document in full_ocr_response.get("documents", [])
        ],
        "combined_text": full_ocr_response.get("combined_text", ""),
    }

