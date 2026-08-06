from __future__ import annotations

from typing import Any

from app.schemas.claim_fields import ClaimType
from app.services.extraction_merge import build_final_output
from app.services.gemini_extraction import GeminiExtractionClient


SOURCE_DIAGNOSIS_PATHS = (
    "dpcDetails.ailment",
    "dpcDetails.diagnosis",
    "patientDetailsFromHospital.patientHospitalDetails",
)


def enrich_dpc_details(
    merged: dict[str, Any],
    claim_type: ClaimType,
    gemini_client: GeminiExtractionClient,
) -> dict[str, Any]:
    source_field = _select_source_diagnosis_field(merged.get("extracted_fields", []))
    if source_field is None:
        return {
            "merged": merged,
            "dpc_enrichment": {
                "status": "skipped",
                "reason": "No diagnosis or ailment field was available after extraction merge.",
            },
        }

    diagnosis = str(source_field["value"]).strip()
    treatment_context = _build_treatment_context(merged.get("extracted_fields", []))

    try:
        coding_output = gemini_client.code_diagnosis(
            diagnosis=diagnosis,
            treatment_context=treatment_context,
        )
    except Exception as exc:
        return {
            "merged": merged,
            "dpc_enrichment": {
                "status": "failed",
                "source_diagnosis": diagnosis,
                "source_schema_path": source_field.get("schema_path"),
                "error": str(exc),
            },
        }

    extracted_fields = merged.get("extracted_fields", [])
    enriched_fields = [
        *extracted_fields,
        *_filter_new_schema_paths(
            generated_fields=_build_dpc_fields(
                claim_type=claim_type,
                source_field=source_field,
                coding_output=coding_output,
            ),
            existing_fields=extracted_fields,
        ),
    ]

    enriched_merged = {
        **merged,
        "extracted_fields": enriched_fields,
        "final_output": build_final_output(enriched_fields),
    }
    return {
        "merged": enriched_merged,
        "dpc_enrichment": {
            "status": "completed",
            "source_diagnosis": diagnosis,
            "source_schema_path": source_field.get("schema_path"),
            "icd_coding": coding_output,
        },
    }


def _select_source_diagnosis_field(
    extracted_fields: list[dict[str, Any]],
) -> dict[str, Any] | None:
    ranked_fields = sorted(
        extracted_fields,
        key=lambda field: (
            _source_rank(str(field.get("schema_path", ""))),
            -(field.get("confidence") or 0),
        ),
    )
    for field in ranked_fields:
        schema_path = str(field.get("schema_path", ""))
        value = field.get("value")
        if not isinstance(value, str) or not value.strip():
            continue
        if _source_rank(schema_path) < 100:
            return field
    return None


def _source_rank(schema_path: str) -> int:
    if schema_path == "dpcDetails.ailment":
        return 0
    if schema_path.startswith("dpcDetails.diagnosis") and schema_path.endswith(".diagnosisName"):
        return 1
    if "natureOfIllness" in schema_path:
        return 2
    return 100


def _build_treatment_context(extracted_fields: list[dict[str, Any]]) -> str:
    context_paths = (
        "dpcDetails.diagnosis",
        "hospitalisationDetails.typeOfAdmission",
        "hospitalisationDetails.statusOfDischarge",
        "patientAdmissionDetails.emergencyOrPlannedHospitalizationEvent",
        "patientDetailsFromHospital.patientHospitalDetails",
    )
    context_values = []
    for field in extracted_fields:
        schema_path = str(field.get("schema_path", ""))
        if any(schema_path.startswith(path) for path in context_paths):
            value = field.get("value")
            if isinstance(value, str) and value.strip():
                context_values.append(f"{schema_path}: {value.strip()}")
    return "\n".join(context_values[:20])


def _build_dpc_fields(
    claim_type: ClaimType,
    source_field: dict[str, Any],
    coding_output: dict[str, Any],
) -> list[dict[str, Any]]:
    candidates = [
        candidate
        for candidate in coding_output.get("candidates", [])
        if isinstance(candidate, dict) and candidate.get("code")
    ]
    if not candidates:
        return []

    source_citations = source_field.get("citations") or []
    source_evidence = source_field.get("evidence") or []
    normalized_diagnosis = str(coding_output.get("normalized_diagnosis") or "").strip()
    primary = candidates[0]
    fields: list[dict[str, Any]] = []

    if claim_type == "reimbursement":
        fields.extend(
            [
                _field("dpcDetails.ailment", normalized_diagnosis or source_field["value"], 0.85, source_citations, source_evidence),
                _field("dpcDetails.dischargeICDCode", primary.get("code"), primary.get("confidence"), source_citations, source_evidence),
                _field("dpcDetails.dischargeShortDescription", primary.get("description"), primary.get("confidence"), source_citations, source_evidence),
                _field("dpcDetails.dischargeLongDescription", primary.get("description"), primary.get("confidence"), source_citations, source_evidence),
            ]
        )

    for index, candidate in enumerate(candidates[:3]):
        confidence = candidate.get("confidence")
        diagnosis_name = normalized_diagnosis if index == 0 and normalized_diagnosis else candidate.get("description")
        fields.extend(
            [
                _field(f"dpcDetails.diagnosis[{index}].diagnosisName", diagnosis_name, confidence, source_citations, source_evidence),
                _field(f"dpcDetails.diagnosis[{index}].icdCode", candidate.get("code"), confidence, source_citations, source_evidence),
                _field(f"dpcDetails.diagnosis[{index}].shortDescription", candidate.get("description"), confidence, source_citations, source_evidence),
                _field(f"dpcDetails.diagnosis[{index}].longDescription", candidate.get("description"), confidence, source_citations, source_evidence),
            ]
        )

        line_of_treatment = coding_output.get("line_of_treatment")
        if index == 0 and line_of_treatment:
            fields.append(
                _field(
                    "dpcDetails.diagnosis[0].lineOfTreatment",
                    line_of_treatment,
                    0.75,
                    source_citations,
                    source_evidence,
                )
            )

        route = coding_output.get("route_of_drug_administration")
        if index == 0 and route:
            fields.append(
                _field(
                    "dpcDetails.diagnosis[0].routeOfDrugAdministration",
                    route,
                    0.75,
                    source_citations,
                    source_evidence,
                )
            )

    return [field for field in fields if field.get("value") not in (None, "")]


def _field(
    schema_path: str,
    value: Any,
    confidence: Any,
    citations: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "catalog_path": _catalog_path(schema_path),
        "schema_path": schema_path,
        "value": str(value).strip() if value is not None else value,
        "confidence": confidence if isinstance(confidence, (int, float)) else 0.7,
        "citations": citations,
        "evidence": evidence,
        "notes": "Generated by post-merge ICD-10 DPC enrichment. Validate with a certified medical coder/adjudicator.",
    }


def _catalog_path(schema_path: str) -> str:
    return schema_path.replace("[0]", "[]").replace("[1]", "[]").replace("[2]", "[]")


def _filter_new_schema_paths(
    generated_fields: list[dict[str, Any]],
    existing_fields: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    existing_paths = {field.get("schema_path") for field in existing_fields}
    return [
        field
        for field in generated_fields
        if field.get("schema_path") and field.get("schema_path") not in existing_paths
    ]
