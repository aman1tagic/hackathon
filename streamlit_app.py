from __future__ import annotations

from io import BytesIO
import json
import os
from typing import Any

import fitz
from PIL import Image, ImageDraw
import requests
import streamlit as st


DEFAULT_API_BASE_URL = os.getenv("CLAIMS_API_BASE_URL", "http://127.0.0.1:8001")


st.set_page_config(page_title="Claims MA Review", layout="wide")


def is_leaf_value(value: Any) -> bool:
    return isinstance(value, dict) and "value" in value and "citations" in value


def flatten_final_output(value: Any, path: str = "") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    if is_leaf_value(value):
        rows.append(
            {
                "path": path,
                "value": value.get("value"),
                "confidence": value.get("confidence"),
                "citations": value.get("citations") or [],
            }
        )
        return rows

    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            rows.extend(flatten_final_output(child, child_path))
        return rows

    if isinstance(value, list):
        for index, child in enumerate(value):
            rows.extend(flatten_final_output(child, f"{path}[{index}]"))
        return rows

    if path and value not in (None, "", [], {}):
        rows.append({"path": path, "value": value, "confidence": None, "citations": []})

    return rows


def direct_values(value: Any) -> Any:
    if is_leaf_value(value):
        return value.get("value")

    if isinstance(value, dict):
        return {key: direct_values(child) for key, child in value.items()}

    if isinstance(value, list):
        return [direct_values(child) for child in value]

    return value


def collect_page_classifications(
    extraction: dict[str, Any],
    ocr: dict[str, Any],
) -> list[dict[str, Any]]:
    direct_classifications = extraction.get("page_classifications")
    if isinstance(direct_classifications, list) and direct_classifications:
        return complete_page_classifications(direct_classifications, ocr)

    best_by_page: dict[int, dict[str, Any]] = {}
    for window in extraction.get("windows", []) or []:
        for classification in window.get("page_classifications", []) or []:
            page_number = classification.get("page_number")
            if not isinstance(page_number, int):
                continue

            confidence = classification.get("confidence") or 0
            existing = best_by_page.get(page_number)
            if existing is None or confidence > (existing.get("confidence") or 0):
                best_by_page[page_number] = classification

    classifications = [best_by_page[page_number] for page_number in sorted(best_by_page)]
    return complete_page_classifications(classifications, ocr)


def complete_page_classifications(
    page_classifications: list[dict[str, Any]],
    ocr: dict[str, Any],
) -> list[dict[str, Any]]:
    best_by_page = {
        classification["page_number"]: classification
        for classification in page_classifications
        if isinstance(classification.get("page_number"), int)
    }
    ocr_pages = ocr.get("pages") or []
    page_numbers = [
        page.get("page_number")
        for page in ocr_pages
        if isinstance(page.get("page_number"), int)
    ]
    if not page_numbers:
        total_pages = ocr.get("total_pages") or 0
        page_numbers = list(range(1, total_pages + 1))

    page_metadata_by_number = {
        page.get("page_number"): {
            "page_number": page.get("page_number"),
            "document_index": page.get("document_index"),
            "filename": page.get("filename"),
            "source_page_number": page.get("source_page_number"),
        }
        for page in ocr_pages
        if isinstance(page.get("page_number"), int)
    }

    completed = []
    for page_number in page_numbers:
        metadata = page_metadata_by_number.get(page_number, {"page_number": page_number})
        classification = best_by_page.get(page_number)
        if classification:
            completed.append({**classification, **metadata})
        else:
            completed.append(
                {
                    **metadata,
                    "document_type": "Unclassified",
                    "confidence": 0,
                    "reason": "No classification was returned for this OCR page.",
                }
            )
    return completed


def group_page_classifications(
    page_classifications: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    ordered = sorted(page_classifications, key=lambda item: item.get("page_number") or 0)

    for classification in ordered:
        page_number = classification.get("page_number")
        document_type = classification.get("document_type")
        if not isinstance(page_number, int) or not document_type:
            continue

        confidence = classification.get("confidence")
        normalized_confidence = confidence if isinstance(confidence, (int, float)) else 0
        document_index = classification.get("document_index")
        source_page_number = classification.get("source_page_number")
        filename = classification.get("filename")
        current_group = groups[-1] if groups else None

        if (
            current_group
            and current_group["document_type"] == document_type
            and current_group.get("document_index") == document_index
            and current_group["end_page"] == page_number - 1
            and (
                not isinstance(source_page_number, int)
                or current_group.get("end_source_page") == source_page_number - 1
            )
        ):
            current_group["pages"].append(page_number)
            if isinstance(source_page_number, int):
                current_group["source_pages"].append(source_page_number)
                current_group["end_source_page"] = source_page_number
            current_group["end_page"] = page_number
            current_group["confidence"] = min(
                current_group["confidence"],
                normalized_confidence,
            )
            continue

        groups.append(
            {
                "document_type": document_type,
                "document_index": document_index,
                "filename": filename,
                "start_page": page_number,
                "end_page": page_number,
                "start_source_page": source_page_number,
                "end_source_page": source_page_number,
                "pages": [page_number],
                "source_pages": [source_page_number] if isinstance(source_page_number, int) else [],
                "confidence": normalized_confidence,
            }
        )

    return groups


def truncate(value: Any, max_length: int = 110) -> str:
    text = str(value)
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def is_pdf_file(filename: str | None, content_type: str | None) -> bool:
    return content_type == "application/pdf" or bool(
        filename and filename.lower().endswith(".pdf")
    )


def render_document_page(
    document_bytes: bytes,
    filename: str | None,
    content_type: str | None,
    source_page_number: int,
    citations: list[dict[str, Any]],
    zoom: float,
) -> Image.Image:
    if is_pdf_file(filename, content_type):
        document = fitz.open(stream=document_bytes, filetype="pdf")
        page_index = max(0, min(source_page_number - 1, document.page_count - 1))
        page = document.load_page(page_index)
        pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        image = Image.open(BytesIO(pixmap.tobytes("png"))).convert("RGBA")
    else:
        image = Image.open(BytesIO(document_bytes)).convert("RGBA")
        if zoom != 1:
            image = image.resize(
                (int(image.width * zoom), int(image.height * zoom)),
                Image.Resampling.LANCZOS,
            )

    overlay = Image.new("RGBA", image.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)

    for citation in citations:
        if citation.get("source_page_number") != source_page_number:
            continue

        polygon = citation.get("polygon") or []
        page_width = citation.get("page_width")
        page_height = citation.get("page_height")
        if not polygon or not page_width or not page_height:
            continue

        points = [
            (
                float(point["x"]) / float(page_width) * image.width,
                float(point["y"]) / float(page_height) * image.height,
            )
            for point in polygon
            if "x" in point and "y" in point
        ]
        if len(points) < 3:
            continue

        draw.polygon(points, fill=(255, 235, 59, 95))
        draw.line([*points, points[0]], fill=(245, 124, 0, 255), width=3)

    return Image.alpha_composite(image, overlay).convert("RGB")


def call_extract_api(
    api_base_url: str,
    claim_type: str,
    claim_id: str,
    uploaded_documents: list[dict[str, Any]],
) -> dict[str, Any]:
    files = [
        (
            "documents",
            (
                document["filename"],
                document["bytes"],
                document.get("content_type") or "application/octet-stream",
            ),
        )
        for document in uploaded_documents
    ]
    response = requests.post(
        f"{api_base_url.rstrip('/')}/api/v1/claims/extract",
        data={"claim_type": claim_type, "claim_id": claim_id},
        files=files,
        timeout=900,
    )
    response.raise_for_status()
    return response.json()


def selected_citations() -> list[dict[str, Any]]:
    selected = st.session_state.get("selected_field")
    if not selected:
        return []
    return selected.get("citations") or []


def selected_page(default_page: int = 1) -> int:
    citations = selected_citations()
    if citations:
        page_number = citations[0].get("page_number")
        if isinstance(page_number, int):
            return page_number
    return st.session_state.get("page_number", default_page)


def selected_source_location() -> dict[str, Any] | None:
    citations = selected_citations()
    if citations:
        citation = citations[0]
        return {
            "document_index": citation.get("document_index"),
            "filename": citation.get("filename"),
            "source_page_number": citation.get("source_page_number") or 1,
            "global_page_number": citation.get("page_number"),
        }

    page_number = st.session_state.get("page_number", 1)
    for page in st.session_state.get("ocr_pages", []) or []:
        if page.get("page_number") == page_number:
            return {
                "document_index": page.get("document_index"),
                "filename": page.get("filename"),
                "source_page_number": page.get("source_page_number") or 1,
                "global_page_number": page_number,
            }
    return None


def get_uploaded_document(document_index: Any) -> dict[str, Any] | None:
    if not isinstance(document_index, int):
        return None
    documents = st.session_state.get("uploaded_documents", []) or []
    if document_index < 0 or document_index >= len(documents):
        return None
    return documents[document_index]


def page_count_for_document(document: dict[str, Any]) -> int:
    if is_pdf_file(document.get("filename"), document.get("content_type")):
        pdf_document = fitz.open(stream=document["bytes"], filetype="pdf")
        return pdf_document.page_count
    return 1


def citations_for_source_page(
    citations: list[dict[str, Any]],
    document_index: int | None,
    source_page_number: int,
) -> list[dict[str, Any]]:
    return [
        citation
        for citation in citations
        if citation.get("document_index") == document_index
        and citation.get("source_page_number") == source_page_number
    ]


st.title("Claims Medical Adjudication Review")

with st.sidebar:
    st.header("Input")
    api_base_url = st.text_input("API base URL", value=DEFAULT_API_BASE_URL)
    claim_type = st.selectbox("Claim type", ["reimbursement", "cashless"])
    claim_id = st.text_input("Claim ID", value="4000869819A")
    uploaded_files = st.file_uploader(
        "Upload claim documents",
        type=["pdf", "png", "jpg", "jpeg"],
        accept_multiple_files=True,
    )
    run_clicked = st.button("Run OCR + Extraction", type="primary", use_container_width=True)

    st.divider()
    st.caption("Backend should be running with `.env` loaded.")
    st.code(
        "export AZURE_DISABLE_SSL_VERIFY=1\n"
        ".venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload --env-file .env",
        language="bash",
    )

if run_clicked:
    if not uploaded_files:
        st.error("Upload at least one PDF/image before running extraction.")
    else:
        uploaded_documents = [
            {
                "document_index": index,
                "filename": uploaded_file.name,
                "content_type": uploaded_file.type or "application/octet-stream",
                "bytes": uploaded_file.getvalue(),
            }
            for index, uploaded_file in enumerate(uploaded_files)
        ]
        st.session_state["uploaded_documents"] = uploaded_documents
        st.session_state["selected_field"] = None
        st.session_state["page_number"] = 1

        with st.spinner("Running OCR and Gemini extraction. This can take a few minutes."):
            try:
                st.session_state["result"] = call_extract_api(
                    api_base_url=api_base_url,
                    claim_type=claim_type,
                    claim_id=claim_id,
                    uploaded_documents=uploaded_documents,
                )
                st.session_state["ocr_pages"] = (
                    st.session_state["result"].get("ocr", {}).get("pages", [])
                )
                st.success("Extraction completed.")
            except requests.HTTPError as exc:
                body = exc.response.text[:2000] if exc.response is not None else ""
                st.error(f"API returned an error: {exc}\n\n{body}")
            except requests.RequestException as exc:
                st.error(f"Could not call extraction API: {exc}")

result = st.session_state.get("result")
uploaded_documents = st.session_state.get("uploaded_documents", []) or []

if not result:
    st.info("Upload PDFs/images and run extraction to see document classification and extracted values.")
    st.stop()

extraction = result.get("extraction", {})
ocr = result.get("ocr", {})
page_classifications = collect_page_classifications(extraction, ocr)
document_groups = extraction.get("document_groups") or group_page_classifications(page_classifications)
field_rows = flatten_final_output(extraction.get("final_output", {}))

summary_cols = st.columns(4)
summary_cols[0].metric("OCR pages", f"{ocr.get('succeeded_pages', 0)}/{ocr.get('total_pages', 0)}")
summary_cols[1].metric("Document groups", len(document_groups))
summary_cols[2].metric("Fields", len(field_rows))
summary_cols[3].metric("Windows", extraction.get("window_count", 0))

left, right = st.columns([0.48, 0.52], gap="large")

with left:
    st.subheader("Page Classification")
    if document_groups:
        st.dataframe(
            [
                {
                    "File": group.get("filename"),
                    "File Page Start": group.get("start_source_page"),
                    "File Page End": group.get("end_source_page"),
                    "Document Type": group.get("document_type"),
                    "Global Start": group.get("start_page"),
                    "Global End": group.get("end_page"),
                    "Global Pages": ", ".join(str(page) for page in group.get("pages", [])),
                    "Confidence": round(group.get("confidence", 0), 3),
                }
                for group in document_groups
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.warning("No page classifications returned.")

    st.subheader("Final Structured Values")
    search = st.text_input("Filter fields", placeholder="invoice, diagnosis, account...")
    normalized_search = search.lower().strip()
    filtered_rows = [
        row
        for row in field_rows
        if not normalized_search
        or normalized_search in row["path"].lower()
        or normalized_search in str(row["value"]).lower()
    ]

    st.caption(f"Showing {len(filtered_rows)} of {len(field_rows)} extracted values.")
    for index, row in enumerate(filtered_rows):
        citations = row.get("citations") or []
        cols = st.columns([0.48, 0.28, 0.09, 0.15])
        cols[0].markdown(f"**{row['path']}**")
        cols[1].write(truncate(row["value"]))
        confidence = row.get("confidence")
        cols[2].write("" if confidence is None else f"{confidence:.2f}")
        if cols[3].button(
            "Go",
            key=f"field-{index}-{row['path']}",
            disabled=not citations,
            use_container_width=True,
        ):
            st.session_state["selected_field"] = row
            first_page = citations[0].get("page_number", 1)
            st.session_state["page_number"] = first_page
            st.rerun()

    with st.expander("Full API response JSON"):
        st.json(result)

with right:
    st.subheader("Document Citation Viewer")
    if not uploaded_documents:
        st.warning("Uploaded document bytes are not available. Re-upload and rerun extraction.")
        st.stop()

    citations = selected_citations()
    source_location = selected_source_location()
    if source_location is None:
        source_location = {
            "document_index": 0,
            "filename": uploaded_documents[0]["filename"],
            "source_page_number": 1,
            "global_page_number": 1,
        }

    document_index = source_location.get("document_index")
    document = get_uploaded_document(document_index)
    if document is None:
        st.warning("The cited source document is not available. Re-upload and rerun extraction.")
        st.stop()

    total_document_pages = page_count_for_document(document)
    source_page_number = st.number_input(
        "Original file page",
        min_value=1,
        max_value=max(total_document_pages, 1),
        value=max(1, min(int(source_location.get("source_page_number") or 1), total_document_pages)),
        step=1,
    )
    st.session_state["page_number"] = source_location.get("global_page_number") or selected_page()
    zoom = st.slider("Zoom", min_value=1.0, max_value=3.0, value=1.6, step=0.1)
    visible_citations = citations_for_source_page(citations, document_index, source_page_number)

    selected = st.session_state.get("selected_field")
    if selected:
        st.markdown(f"**Selected field:** `{selected['path']}`")
        st.write(truncate(selected["value"], 180))
        st.caption(
            f"Source: `{document.get('filename')}`"
            f", file page {source_page_number}"
            f", global page {source_location.get('global_page_number') or '-'}"
        )
        if citations:
            st.caption(
                "Highlighting "
                f"{len(visible_citations)} citation(s) on this original file page."
            )
            with st.expander("Citation text"):
                for citation in visible_citations:
                    st.write(
                        f"Global page {citation.get('page_number')}, "
                        f"line {citation.get('line_index')}: "
                        f"{citation.get('text', '')}"
                    )
        else:
            st.info("The selected field does not have citation coordinates.")
    else:
        st.info("Click `Go` beside an extracted value to jump to its citation.")

    rendered_page = render_document_page(
        document_bytes=document["bytes"],
        filename=document.get("filename"),
        content_type=document.get("content_type"),
        source_page_number=source_page_number,
        citations=visible_citations,
        zoom=zoom,
    )
    st.image(rendered_page, use_container_width=True)

st.divider()
st.subheader("Final Extraction Results")
st.caption("Direct schema values only. Coordinates, confidence, and citations are excluded.")
st.code(
    json.dumps(
        extraction.get("final_extraction") or direct_values(extraction.get("final_output", {})),
        indent=2,
        ensure_ascii=False,
    ),
    language="json",
)
