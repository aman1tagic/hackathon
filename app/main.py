from typing import Annotated, Any

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.services.azure_read import (
    AzureReadClient,
    analyze_pages_in_parallel,
    build_page_tasks,
)
from app.services.citations import build_line_lookup
from app.services.classification_groups import group_page_classifications
from app.services.dpc_enrichment import enrich_dpc_details
from app.services.extraction_merge import merge_window_outputs
from app.services.gemini_extraction import (
    GeminiExtractionClient,
    build_page_windows,
    build_token_consumption_summary,
    extract_windows_in_parallel,
)
from app.services.ocr_response import shape_ocr_response
from app.services.ocr_store import ocr_store
from app.services.pdf_pages import is_pdf, single_image_page, split_pdf_into_pages

app = FastAPI(
    title="Claims Hackathon API",
    description="Medical adjudication OCR pipeline prototype",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/claims/ocr")
async def run_claim_ocr(
    claim_id: Annotated[str | None, Form()] = None,
    documents: Annotated[list[UploadFile] | None, File()] = None,
    document: Annotated[list[UploadFile] | None, File()] = None,
    response_mode: Annotated[str, Query(pattern="^(compact|full)$")] = "compact",
) -> dict[str, Any]:
    full_ocr_response = await _run_azure_ocr(
        claim_id=claim_id, documents=documents, document=document
    )
    ocr_id = ocr_store.put(full_ocr_response)
    return shape_ocr_response(full_ocr_response, ocr_id, response_mode)


@app.get("/api/v1/claims/ocr/{ocr_id}")
async def get_stored_ocr(
    ocr_id: str,
    response_mode: Annotated[str, Query(pattern="^(compact|full)$")] = "compact",
) -> dict[str, Any]:
    full_ocr_response = ocr_store.get(ocr_id)
    if full_ocr_response is None:
        raise HTTPException(status_code=404, detail="OCR result not found or expired.")
    return shape_ocr_response(full_ocr_response, ocr_id, response_mode)


@app.post("/api/v1/claims/extract")
async def run_claim_extraction(
    claim_type: Annotated[str, Form()],
    claim_id: Annotated[str | None, Form()] = None,
    documents: Annotated[list[UploadFile] | None, File()] = None,
    document: Annotated[list[UploadFile] | None, File()] = None,
) -> dict[str, Any]:
    normalized_claim_type = claim_type.lower().strip()
    if normalized_claim_type not in {"cashless", "reimbursement"}:
        raise HTTPException(
            status_code=400,
            detail="claim_type must be either 'cashless' or 'reimbursement'.",
        )

    settings = get_settings()
    if not settings.gemini_api_key:
        raise HTTPException(
            status_code=500,
            detail="Gemini is not configured. Set GEMINI_API_KEY in the environment.",
        )

    full_ocr_response = await _run_azure_ocr(
        claim_id=claim_id,
        documents=documents,
        document=document,
    )
    ocr_id = ocr_store.put(full_ocr_response)
    pages = full_ocr_response["pages"]
    windows = build_page_windows(
        pages,
        window_size=settings.extraction_window_size,
        overlap=settings.extraction_window_overlap,
    )

    gemini_client = GeminiExtractionClient(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
    )

    window_outputs = await run_in_threadpool(
        extract_windows_in_parallel,
        gemini_client,
        normalized_claim_type,  # type: ignore[arg-type]
        windows,
        settings.extraction_max_workers,
    )

    merged = merge_window_outputs(window_outputs, build_line_lookup(full_ocr_response["pages"]))
    dpc_result = await run_in_threadpool(
        enrich_dpc_details,
        merged,
        normalized_claim_type,
        gemini_client,
    )
    merged = dpc_result["merged"]
    page_classifications = _complete_page_classifications(
        pages=pages,
        page_classifications=merged["page_classifications"]
        or _collect_page_classifications(window_outputs),
    )
    document_groups = group_page_classifications(page_classifications)
    token_consumption = build_token_consumption_summary(
        window_outputs=window_outputs,
        model=settings.gemini_model,
    )
    response_windows = [
        {
            key: value
            for key, value in window_output.items()
            if key != "token_consumption"
        }
        for window_output in window_outputs
    ]

    return {
        "claim_id": claim_id,
        "claim_type": normalized_claim_type,
        "status": "extraction_completed",
        "ocr": shape_ocr_response(full_ocr_response, ocr_id, "compact"),
        "extraction": {
            "model": settings.gemini_model,
            "window_size": settings.extraction_window_size,
            "window_overlap": settings.extraction_window_overlap,
            "max_workers": settings.extraction_max_workers,
            "window_count": len(windows),
            "token_consumption": token_consumption,
            "dpc_enrichment": dpc_result["dpc_enrichment"],
            "document_groups": document_groups,
            "windows": response_windows,
            **merged,
            "page_classifications": page_classifications,
        },
    }


def _collect_page_classifications(window_outputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_page: dict[int, dict[str, Any]] = {}
    for window_output in window_outputs:
        for classification in window_output.get("page_classifications", []):
            page_number = classification.get("page_number")
            if not isinstance(page_number, int):
                continue

            confidence = classification.get("confidence") or 0
            existing = best_by_page.get(page_number)
            if existing is None or confidence > (existing.get("confidence") or 0):
                best_by_page[page_number] = classification

    return [best_by_page[page_number] for page_number in sorted(best_by_page)]


def _complete_page_classifications(
    pages: list[dict[str, Any]],
    page_classifications: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    best_by_page: dict[int, dict[str, Any]] = {}
    for classification in page_classifications:
        page_number = classification.get("page_number")
        confidence = classification.get("confidence") or 0
        if not isinstance(page_number, int):
            continue

        existing = best_by_page.get(page_number)
        if existing is None or confidence > (existing.get("confidence") or 0):
            best_by_page[page_number] = classification

    completed = []
    for page in pages:
        page_number = page.get("page_number")
        if not isinstance(page_number, int):
            continue

        completed.append(
            best_by_page.get(page_number)
            or {
                "page_number": page_number,
                "document_type": "Unclassified",
                "confidence": 0,
                "reason": "No classification was returned for this OCR page.",
            }
        )

    return completed


async def _run_azure_ocr(
    claim_id: str | None,
    documents: list[UploadFile] | None,
    document: list[UploadFile] | None,
) -> dict[str, Any]:
    upload_files = documents or document or []
    if not upload_files:
        raise HTTPException(
            status_code=400,
            detail="Upload at least one file using multipart field 'documents'.",
        )

    settings = get_settings()
    if not settings.azure_read_endpoint or not settings.azure_read_key:
        raise HTTPException(
            status_code=500,
            detail=(
                "Azure OCR is not configured. Set AZURE_READ_SERVICE_ENDPOINT and "
                "AZURE_READ_SERVICE_KEY."
            ),
        )

    document_records: list[dict[str, Any]] = []
    all_tasks = []

    for document_index, upload in enumerate(upload_files):
        content = await upload.read()
        if not content:
            raise HTTPException(
                status_code=400, detail=f"Uploaded file is empty: {upload.filename}"
            )

        try:
            if is_pdf(upload.filename, upload.content_type, content):
                page_payloads = split_pdf_into_pages(content)
            else:
                page_payloads = [single_image_page(content, upload.content_type)]
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Unable to prepare {upload.filename or 'uploaded file'} for OCR: {exc}",
            ) from exc

        filename = upload.filename or f"document-{document_index + 1}"
        document_records.append(
            {
                "document_index": document_index,
                "filename": filename,
                "content_type": upload.content_type,
                "page_count": len(page_payloads),
                "pages": [],
                "failed_pages": [],
            }
        )
        all_tasks.extend(build_page_tasks(document_index, filename, page_payloads))

    azure_client = AzureReadClient(
        endpoint=settings.azure_read_endpoint,
        key=settings.azure_read_key,
        model_id=settings.azure_read_model,
        max_retries=settings.azure_ocr_max_retries,
        verify_ssl=settings.azure_read_verify_ssl,
    )
    ocr_results = await run_in_threadpool(
        analyze_pages_in_parallel,
        azure_client,
        all_tasks,
        settings.azure_ocr_max_workers,
    )

    succeeded_pages = 0
    for result in ocr_results:
        page = result["page"]
        target_document = document_records[page["document_index"]]
        if result["status"] == "succeeded":
            succeeded_pages += 1
            target_document["pages"].append(page)
        else:
            target_document["failed_pages"].append(
                {
                    "source_page_number": page["source_page_number"],
                    "error": result["error"],
                }
            )

    for record in document_records:
        record["pages"].sort(key=lambda page: page["source_page_number"])
        record["failed_pages"].sort(key=lambda page: page["source_page_number"])

    total_pages = len(all_tasks)
    pages = [page for record in document_records for page in record["pages"]]
    pages.sort(key=lambda page: (page["document_index"], page["source_page_number"]))

    for page_number, page in enumerate(pages, start=1):
        page["page_number"] = page_number

    combined_text = "\n\n".join(
        page["ocr_text"] for page in pages if page.get("ocr_text")
    )

    return {
        "claim_id": claim_id,
        "status": (
            "ocr_completed"
            if succeeded_pages == total_pages
            else "ocr_partially_completed"
        ),
        "model": settings.azure_read_model,
        "total_documents": len(document_records),
        "total_pages": total_pages,
        "succeeded_pages": succeeded_pages,
        "failed_pages": total_pages - succeeded_pages,
        "pages": pages,
        "documents": document_records,
        "combined_text": combined_text,
    }
