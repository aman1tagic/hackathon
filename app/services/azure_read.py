from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from io import BytesIO
import time
from typing import Any

from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential
from azure.core.pipeline.transport import RequestsTransport
import certifi

from app.services.pdf_pages import PagePayload


@dataclass(frozen=True)
class OcrPageTask:
    document_index: int
    filename: str
    source_page_number: int
    payload: bytes
    content_type: str


def _polygon_to_list(polygon: Any) -> list[dict[str, float]]:
    if not polygon:
        return []

    points: list[dict[str, float]] = []
    for point in polygon:
        x = getattr(point, "x", None)
        y = getattr(point, "y", None)
        if x is None and isinstance(point, dict):
            x = point.get("x")
            y = point.get("y")
        if x is not None and y is not None:
            points.append({"x": float(x), "y": float(y)})
    return points


def _spans_to_list(spans: Any) -> list[dict[str, int]]:
    return [
        {"offset": int(span.offset), "length": int(span.length)}
        for span in spans or []
        if getattr(span, "offset", None) is not None and getattr(span, "length", None) is not None
    ]


def _page_content(full_content: str, page: Any) -> str:
    chunks: list[str] = []
    for span in getattr(page, "spans", []) or []:
        offset = getattr(span, "offset", None)
        length = getattr(span, "length", None)
        if offset is not None and length is not None:
            chunks.append(full_content[offset : offset + length])
    return "\n".join(chunk.strip() for chunk in chunks if chunk.strip()) or full_content


def _serialize_page(result: Any, task: OcrPageTask) -> dict[str, Any]:
    azure_page = result.pages[0] if getattr(result, "pages", None) else None
    full_content = getattr(result, "content", "") or ""

    if azure_page is None:
        return {
            "document_index": task.document_index,
            "filename": task.filename,
            "source_page_number": task.source_page_number,
            "ocr_text": full_content,
            "content": full_content,
            "width": None,
            "height": None,
            "unit": None,
            "lines": [],
            "words": [],
        }

    ocr_text = _page_content(full_content, azure_page)
    return {
        "document_index": task.document_index,
        "filename": task.filename,
        "source_page_number": task.source_page_number,
        "azure_page_number": getattr(azure_page, "page_number", None),
        "ocr_text": ocr_text,
        "content": ocr_text,
        "width": getattr(azure_page, "width", None),
        "height": getattr(azure_page, "height", None),
        "unit": getattr(azure_page, "unit", None),
        "lines": [
            {
                "content": line.content,
                "polygon": _polygon_to_list(getattr(line, "polygon", None)),
                "spans": _spans_to_list(getattr(line, "spans", None)),
            }
            for line in getattr(azure_page, "lines", []) or []
        ],
        "words": [
            {
                "content": word.content,
                "confidence": getattr(word, "confidence", None),
                "polygon": _polygon_to_list(getattr(word, "polygon", None)),
                "span": {
                    "offset": getattr(getattr(word, "span", None), "offset", None),
                    "length": getattr(getattr(word, "span", None), "length", None),
                },
            }
            for word in getattr(azure_page, "words", []) or []
        ],
    }


class AzureReadClient:
    def __init__(
        self,
        endpoint: str,
        key: str,
        model_id: str = "prebuilt-read",
        max_retries: int = 3,
        verify_ssl: bool | str = True,
    ) -> None:
        connection_verify = certifi.where() if verify_ssl is True else verify_ssl
        transport = RequestsTransport(connection_verify=connection_verify)
        self._client = DocumentAnalysisClient(
            endpoint,
            AzureKeyCredential(key),
            transport=transport,
        )
        self._model_id = model_id
        self._max_retries = max_retries

    def analyze_page(self, task: OcrPageTask) -> dict[str, Any]:
        for attempt in range(self._max_retries + 1):
            try:
                poller = self._client.begin_analyze_document(
                    self._model_id,
                    document=BytesIO(task.payload),
                )
                result = poller.result()
                return {
                    "status": "succeeded",
                    "page": _serialize_page(result, task),
                    "error": None,
                }
            except Exception as exc:
                if attempt >= self._max_retries:
                    return {
                        "status": "failed",
                        "page": {
                            "document_index": task.document_index,
                            "filename": task.filename,
                            "source_page_number": task.source_page_number,
                        },
                        "error": str(exc),
                    }
                time.sleep(2**attempt)

        raise RuntimeError("Unexpected Azure OCR retry state")


def build_page_tasks(
    document_index: int,
    filename: str,
    pages: list[PagePayload],
) -> list[OcrPageTask]:
    return [
        OcrPageTask(
            document_index=document_index,
            filename=filename,
            source_page_number=page.source_page_number,
            payload=page.content,
            content_type=page.content_type,
        )
        for page in pages
    ]


def analyze_pages_in_parallel(
    client: AzureReadClient,
    tasks: list[OcrPageTask],
    max_workers: int,
) -> list[dict[str, Any]]:
    if not tasks:
        return []

    results: list[dict[str, Any] | None] = [None] * len(tasks)
    worker_count = min(max_workers, len(tasks))

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_to_index = {
            executor.submit(client.analyze_page, task): index for index, task in enumerate(tasks)
        }
        for future in as_completed(future_to_index):
            results[future_to_index[future]] = future.result()

    return [result for result in results if result is not None]
