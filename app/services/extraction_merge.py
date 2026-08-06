import re
from typing import Any

from app.services.citations import resolve_citations


def _candidate_key(candidate: dict[str, Any]) -> tuple[str, str]:
    value = candidate.get("value")
    normalized_value = value.strip().lower() if isinstance(value, str) else str(value)
    return candidate.get("schema_path", ""), normalized_value


PATH_SEGMENT_PATTERN = re.compile(r"^(?P<name>[^\[\]]+)(?:\[(?P<index>\d+)\])?$")

INVOICE_SERVICE_FIELDS = (
    "itemDescription",
    "categoryLevel4",
    "categoryLevel1",
    "roomType",
    "units",
    "grossAmount",
    "isNonPayable",
    "nonPayableReason",
)


def merge_window_outputs(
    window_outputs: list[dict[str, Any]],
    line_lookup: dict[int, dict[int, dict[str, Any]]],
) -> dict[str, Any]:
    best_by_field_value: dict[tuple[str, str], dict[str, Any]] = {}
    page_classifications: dict[int, dict[str, Any]] = {}

    for window_output in window_outputs:
        for classification in window_output.get("page_classifications", []):
            page_number = classification.get("page_number")
            confidence = classification.get("confidence") or 0
            if not isinstance(page_number, int):
                continue
            existing = page_classifications.get(page_number)
            if existing is None or confidence > (existing.get("confidence") or 0):
                page_classifications[page_number] = classification

        for extraction in window_output.get("extractions", []):
            schema_path = extraction.get("schema_path")
            value = extraction.get("value")
            if not schema_path or value in (None, ""):
                continue

            confidence = extraction.get("confidence") or 0
            enriched = {
                "catalog_path": extraction.get("catalog_path"),
                "schema_path": schema_path,
                "value": value,
                "confidence": confidence,
                "citations": resolve_citations(extraction.get("evidence", []), line_lookup),
                "evidence": extraction.get("evidence", []),
                "notes": extraction.get("notes"),
            }

            key = _candidate_key(enriched)
            existing = best_by_field_value.get(key)
            if existing is None or confidence > (existing.get("confidence") or 0):
                best_by_field_value[key] = enriched

    extracted_fields = sorted(
        best_by_field_value.values(),
        key=lambda item: (item["schema_path"], -(item.get("confidence") or 0)),
    )

    return {
        "page_classifications": [
            page_classifications[page_number] for page_number in sorted(page_classifications)
        ],
        "extracted_fields": extracted_fields,
        "final_output": build_final_output(extracted_fields),
    }


def build_final_output(extracted_fields: list[dict[str, Any]]) -> dict[str, Any]:
    final_output: dict[str, Any] = {}
    for field in extracted_fields:
        _set_nested_evidence(final_output, field["schema_path"], _evidence_value(field))
    compacted_output = _compact_sparse_arrays(final_output)
    _normalize_invoice_line_items(compacted_output)
    return compacted_output


def _evidence_value(field: dict[str, Any]) -> dict[str, Any]:
    return {
        "value": field["value"],
        "confidence": field["confidence"],
        "citations": field["citations"],
    }


def _set_nested_evidence(target: dict[str, Any], path: str, value: dict[str, Any]) -> None:
    current: Any = target
    segments = path.split(".")

    for index, segment in enumerate(segments):
        match = PATH_SEGMENT_PATTERN.match(segment)
        if not match:
            target.setdefault("_unmapped", []).append({"schema_path": path, **value})
            return

        key = match.group("name")
        array_index = match.group("index")
        is_last = index == len(segments) - 1

        if array_index is None:
            if is_last:
                existing = current.get(key)
                if existing is None:
                    current[key] = value
                elif isinstance(existing, list):
                    existing.append(value)
                else:
                    current[key] = [existing, value]
                return

            current = current.setdefault(key, {})
            continue

        item_index = int(array_index)
        items = current.setdefault(key, [])
        while len(items) <= item_index:
            items.append({})

        if is_last:
            existing = items[item_index]
            if existing:
                items[item_index] = [existing, value] if not isinstance(existing, list) else [*existing, value]
            else:
                items[item_index] = value
            return

        current = items[item_index]


def _compact_sparse_arrays(value: Any) -> Any:
    if isinstance(value, list):
        compacted = [_compact_sparse_arrays(item) for item in value]
        return [
            item
            for item in compacted
            if item not in ({}, [], None)
        ]

    if isinstance(value, dict):
        return {key: _compact_sparse_arrays(item) for key, item in value.items()}

    return value


def _normalize_invoice_line_items(final_output: dict[str, Any]) -> None:
    invoice_details = final_output.get("invoiceDetails")
    if not isinstance(invoice_details, list):
        return

    for invoice in invoice_details:
        if not isinstance(invoice, dict):
            continue

        services = invoice.get("services")
        if services is None:
            invoice["services"] = []
            continue
        if not isinstance(services, list):
            continue

        for service in services:
            if not isinstance(service, dict):
                continue

            for field_name in INVOICE_SERVICE_FIELDS:
                service.setdefault(field_name, _empty_evidence_value())


def _empty_evidence_value() -> dict[str, Any]:
    return {
        "value": "-",
        "confidence": 0,
        "citations": [],
    }
