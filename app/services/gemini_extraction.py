from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from typing import Any

import requests

from app.schemas.claim_fields import DOCUMENT_CLASSIFICATION_TYPES, ClaimType, get_field_catalog


WINDOW_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "page_classifications": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "page_number": {"type": "integer"},
                    "document_type": {"type": "string"},
                    "confidence": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["page_number", "document_type", "confidence"],
            },
        },
        "extractions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "catalog_path": {"type": "string"},
                    "schema_path": {"type": "string"},
                    "value": {"type": "string"},
                    "confidence": {"type": "number"},
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "page_number": {"type": "integer"},
                                "line_indices": {
                                    "type": "array",
                                    "items": {"type": "integer"},
                                },
                                "matched_text": {"type": "string"},
                            },
                            "required": ["page_number", "line_indices"],
                        },
                    },
                    "notes": {"type": "string"},
                },
                "required": ["catalog_path", "schema_path", "value", "confidence", "evidence"],
            },
        },
    },
    "required": ["page_classifications", "extractions"],
}


ICD_CODING_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "input_diagnosis": {"type": "string"},
        "normalized_diagnosis": {"type": "string"},
        "icd_version": {"type": "string"},
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "description": {"type": "string"},
                    "confidence": {"type": "number"},
                    "reason": {"type": "string"},
                    "missing_details": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["code", "description", "confidence", "reason", "missing_details"],
            },
        },
        "final_recommendation": {"type": "string"},
        "line_of_treatment": {"type": "string"},
        "route_of_drug_administration": {"type": "string"},
        "requires_human_review": {"type": "boolean"},
    },
    "required": [
        "input_diagnosis",
        "normalized_diagnosis",
        "icd_version",
        "candidates",
        "final_recommendation",
        "requires_human_review",
    ],
}


TOKEN_USAGE_KEYS = {
    "promptTokenCount": "input_tokens",
    "candidatesTokenCount": "output_tokens",
    "totalTokenCount": "total_tokens",
    "cachedContentTokenCount": "cached_input_tokens",
    "thoughtsTokenCount": "thoughts_tokens",
    "toolUsePromptTokenCount": "tool_use_prompt_tokens",
}


def build_page_windows(
    pages: list[dict[str, Any]],
    window_size: int,
    overlap: int,
) -> list[list[dict[str, Any]]]:
    if not pages:
        return []

    safe_window_size = max(1, window_size)
    safe_overlap = min(max(0, overlap), safe_window_size - 1)
    step = safe_window_size - safe_overlap

    windows: list[list[dict[str, Any]]] = []
    start = 0
    while start < len(pages):
        windows.append(pages[start : start + safe_window_size])
        start += step
    return windows


def _compact_page_for_prompt(page: dict[str, Any]) -> dict[str, Any]:
    prompt_lines: list[dict[str, Any]] = []
    for line_index, line in enumerate(page.get("lines", [])):
        prompt_lines.append(
            {
                "line_index": line.get("line_index", line_index),
                "text": line.get("text", line.get("content", "")),
            }
        )

    return {
        "page_number": page["page_number"],
        "document_index": page.get("document_index"),
        "source_page_number": page.get("source_page_number"),
        "filename": page.get("filename"),
        "lines": prompt_lines,
    }


def _build_prompt(claim_type: ClaimType, pages: list[dict[str, Any]]) -> str:
    field_catalog = get_field_catalog(claim_type)
    compact_pages = [_compact_page_for_prompt(page) for page in pages]

    return f"""
You are a health insurance claim document understanding engine.

Task:
1. Classify every page into exactly one allowed document type.
2. Extract all available fields for the {claim_type} schema from the same pages.
3. Return only JSON matching the requested shape.

Allowed document types:
{json.dumps(DOCUMENT_CLASSIFICATION_TYPES, ensure_ascii=False)}

Field catalog:
{json.dumps(field_catalog, ensure_ascii=False)}

Rules:
- Do classification and extraction together in this single pass.
- Extract only values explicitly supported by OCR text in the provided pages.
- Do not infer missing values.
- Do not generate ICD/PCS codes if codes are not explicitly present.
- Dates should be normalized to YYYY-MM-DD when the source date is clear.
- For every extraction, set schema_path to exactly one path from the field catalog.
- For invoice/service rows, return one extraction per available leaf field using the matching [] path.
- Evidence must refer to page_number and line_indices from the provided OCR lines.
- Confidence must be from 0 to 1.
- If a field is unavailable in this window, omit it.
- If the same field/value is repeated across pages, return the strongest evidence in this window.
- Do not return coordinates. The backend will resolve line_indices to OCR coordinates.
- For catalog_path, use exactly one path from the field catalog.
- For schema_path, use a concrete final-output path. Replace [] arrays with zero-based indexes.
  Example: invoiceDetails[].services[].grossAmount becomes invoiceDetails[0].services[2].grossAmount.
- Keep related array fields aligned by index within the same window whenever the source document clearly shows rows/records.
- For invoiceDetails indexes, use the source page_number as the stable invoice index.
  Example: if an invoice is on page 12, use invoiceDetails[12].invoiceNumber.
  This prevents different sliding windows from reusing invoiceDetails[0] for different invoices.
- For invoiceDetails[].services[] indexes, use the line item row order within that invoice page, starting at 0.
- For invoices/bills, return every visible service/medicine/consumable/investigation/room/professional-fee line item.
- If a service line item is visible but one of its columns is unavailable, return the available columns only. The backend will fill missing line-item columns with "-".
- If multiple invoice numbers are on the same page, increment from the page_number for the second invoice.
  Example: first invoice on page 14 uses invoiceDetails[14], second invoice on page 14 uses invoiceDetails[15].

Pages:
{json.dumps(compact_pages, ensure_ascii=False)}
""".strip()


def _build_icd_coding_prompt(diagnosis: str, treatment_context: str | None = None) -> str:
    return f"""
You are a medical coding assistant for health insurance claims.

Task:
Identify the most appropriate ICD-10 code candidates for the disease/diagnosis mentioned by the user.

Input diagnosis:
{diagnosis}

Additional claim/treatment context:
{treatment_context or ""}

Instructions:
1. Do not guess blindly.
2. Normalize the diagnosis into standard medical terminology.
3. If the diagnosis is vague, return possible ICD-10 code candidates instead of one final code.
4. Prefer WHO ICD-10 coding logic unless another code system is specified.
5. Do not over-specify laterality, severity, complication, acute/chronic status, or anatomical site unless clearly mentioned.
6. If required clinical details are missing, list them in missing_details.
7. Return confidence score and reason for each candidate.
8. Mention that final ICD coding must be validated by a certified medical coder or adjudicator.
9. Also return broad line_of_treatment as Medical, Surgical, or blank when not supportable.
10. Also return route_of_drug_administration as Oral, IV, IM, All, or blank when not supportable.

Output format:
Return JSON only.
""".strip()


class GeminiExtractionClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_seconds: int = 120,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds

    def extract_window(self, claim_type: ClaimType, pages: list[dict[str, Any]]) -> dict[str, Any]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self._model}:generateContent"
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": _build_prompt(claim_type, pages)}],
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
                "responseSchema": WINDOW_RESPONSE_SCHEMA,
            },
        }
        response = requests.post(
            url,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self._api_key,
            },
            json=payload,
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        text = self._extract_text(data)
        window_output = json.loads(text)
        window_output["token_consumption"] = normalize_gemini_usage(data.get("usageMetadata"))
        return window_output

    def code_diagnosis(self, diagnosis: str, treatment_context: str | None = None) -> dict[str, Any]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self._model}:generateContent"
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": _build_icd_coding_prompt(diagnosis, treatment_context)}],
                }
            ],
            "generationConfig": {
                "temperature": 0.0,
                "responseMimeType": "application/json",
                "responseSchema": ICD_CODING_RESPONSE_SCHEMA,
            },
        }
        response = requests.post(
            url,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self._api_key,
            },
            json=payload,
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        text = self._extract_text(data)
        coding_output = json.loads(text)
        coding_output["token_consumption"] = normalize_gemini_usage(data.get("usageMetadata"))
        return coding_output

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str:
        candidates = data.get("candidates") or []
        if not candidates:
            raise ValueError("Gemini response did not include candidates")

        parts = candidates[0].get("content", {}).get("parts") or []
        text_parts = [part.get("text", "") for part in parts if part.get("text")]
        if not text_parts:
            raise ValueError("Gemini response did not include text")
        return "".join(text_parts)


def normalize_gemini_usage(usage_metadata: dict[str, Any] | None) -> dict[str, Any]:
    metadata = usage_metadata or {}
    usage: dict[str, Any] = {}
    for gemini_key, response_key in TOKEN_USAGE_KEYS.items():
        usage[response_key] = _integer_or_zero(metadata.get(gemini_key))

    detail_mappings = {
        "promptTokensDetails": "input_token_details",
        "candidatesTokensDetails": "output_token_details",
        "cacheTokensDetails": "cached_input_token_details",
        "toolUsePromptTokensDetails": "tool_use_prompt_token_details",
    }
    for gemini_key, response_key in detail_mappings.items():
        details = _normalize_token_details(metadata.get(gemini_key))
        if details:
            usage[response_key] = details

    return usage


def build_token_consumption_summary(
    window_outputs: list[dict[str, Any]],
    model: str,
) -> dict[str, Any]:
    calls: list[dict[str, Any]] = []
    cumulative = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cached_input_tokens": 0,
        "thoughts_tokens": 0,
        "tool_use_prompt_tokens": 0,
        "call_count": len(window_outputs),
        "successful_call_count": 0,
        "failed_call_count": 0,
    }

    for window_output in window_outputs:
        usage = window_output.get("token_consumption") or {}
        call = {
            "call_index": window_output.get("window_index"),
            "call_name": f"gemini_extract_window_{window_output.get('window_index')}",
            "model": model,
            "page_numbers": window_output.get("page_numbers", []),
            "status": "failed" if window_output.get("error") else "succeeded",
            "input_tokens": _integer_or_zero(usage.get("input_tokens")),
            "output_tokens": _integer_or_zero(usage.get("output_tokens")),
            "total_tokens": _integer_or_zero(usage.get("total_tokens")),
            "cached_input_tokens": _integer_or_zero(usage.get("cached_input_tokens")),
            "thoughts_tokens": _integer_or_zero(usage.get("thoughts_tokens")),
            "tool_use_prompt_tokens": _integer_or_zero(usage.get("tool_use_prompt_tokens")),
        }

        for detail_key in (
            "input_token_details",
            "output_token_details",
            "cached_input_token_details",
            "tool_use_prompt_token_details",
        ):
            if usage.get(detail_key):
                call[detail_key] = usage[detail_key]

        if window_output.get("error"):
            cumulative["failed_call_count"] += 1
            call["error"] = window_output.get("error")
        else:
            cumulative["successful_call_count"] += 1

        for token_key in (
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "cached_input_tokens",
            "thoughts_tokens",
            "tool_use_prompt_tokens",
        ):
            cumulative[token_key] += call[token_key]

        calls.append(call)

    return {
        "cumulative": cumulative,
        "calls": calls,
    }


def _normalize_token_details(details: Any) -> list[dict[str, Any]]:
    if not isinstance(details, list):
        return []

    normalized_details = []
    for detail in details:
        if not isinstance(detail, dict):
            continue

        normalized_details.append(
            {
                "modality": detail.get("modality"),
                "tokens": _integer_or_zero(detail.get("tokenCount")),
            }
        )
    return normalized_details


def _integer_or_zero(value: Any) -> int:
    return value if isinstance(value, int) else 0


def extract_windows_in_parallel(
    client: GeminiExtractionClient,
    claim_type: ClaimType,
    windows: list[list[dict[str, Any]]],
    max_workers: int,
) -> list[dict[str, Any]]:
    if not windows:
        return []

    results: list[dict[str, Any] | None] = [None] * len(windows)
    worker_count = min(max(1, max_workers), len(windows))

    def run_window(window_index: int, window_pages: list[dict[str, Any]]) -> dict[str, Any]:
        page_numbers = [page["page_number"] for page in window_pages]
        try:
            window_result = client.extract_window(claim_type=claim_type, pages=window_pages)
            return {
                "window_index": window_index,
                "page_numbers": page_numbers,
                **window_result,
            }
        except Exception as exc:
            return {
                "window_index": window_index,
                "page_numbers": page_numbers,
                "page_classifications": [],
                "extractions": [],
                "error": str(exc),
            }

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_to_index = {
            executor.submit(run_window, window_index, window_pages): window_index
            for window_index, window_pages in enumerate(windows)
        }
        for future in as_completed(future_to_index):
            results[future_to_index[future]] = future.result()

    return [result for result in results if result is not None]
