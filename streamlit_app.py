from __future__ import annotations

from io import BytesIO
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

    return [
        best_by_page.get(page_number)
        or {
            "page_number": page_number,
            "document_type": "Unclassified",
            "confidence": 0,
            "reason": "No classification was returned for this OCR page.",
        }
        for page_number in page_numbers
    ]


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
        current_group = groups[-1] if groups else None

        if (
            current_group
            and current_group["document_type"] == document_type
            and current_group["end_page"] == page_number - 1
        ):
            current_group["pages"].append(page_number)
            current_group["end_page"] = page_number
            current_group["confidence"] = min(
                current_group["confidence"],
                normalized_confidence,
            )
            continue

        groups.append(
            {
                "document_type": document_type,
                "start_page": page_number,
                "end_page": page_number,
                "pages": [page_number],
                "confidence": normalized_confidence,
            }
        )

    return groups


def truncate(value: Any, max_length: int = 110) -> str:
    text = str(value)
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def render_pdf_page(
    pdf_bytes: bytes,
    page_number: int,
    citations: list[dict[str, Any]],
    zoom: float,
) -> Image.Image:
    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    page_index = max(0, min(page_number - 1, document.page_count - 1))
    page = document.load_page(page_index)
    pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    image = Image.open(BytesIO(pixmap.tobytes("png"))).convert("RGBA")

    overlay = Image.new("RGBA", image.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)

    for citation in citations:
        if citation.get("page_number") != page_number:
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
    uploaded_filename: str,
    uploaded_file_type: str,
    pdf_bytes: bytes,
) -> dict[str, Any]:
    response = requests.post(
        f"{api_base_url.rstrip('/')}/api/v1/claims/extract",
        data={"claim_type": claim_type, "claim_id": claim_id},
        files=[
            (
                "documents",
                (
                    uploaded_filename,
                    pdf_bytes,
                    uploaded_file_type or "application/pdf",
                ),
            )
        ],
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


st.title("Claims Medical Adjudication Review")

with st.sidebar:
    st.header("Input")
    api_base_url = st.text_input("API base URL", value=DEFAULT_API_BASE_URL)
    claim_type = st.selectbox("Claim type", ["reimbursement", "cashless"])
    claim_id = st.text_input("Claim ID", value="4000869819A")
    uploaded_file = st.file_uploader("Upload claim PDF", type=["pdf"])
    run_clicked = st.button("Run OCR + Extraction", type="primary", use_container_width=True)

    st.divider()
    st.caption("Backend should be running with `.env` loaded.")
    st.code(
        "export AZURE_DISABLE_SSL_VERIFY=1\n"
        ".venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload --env-file .env",
        language="bash",
    )

if run_clicked:
    if uploaded_file is None:
        st.error("Upload a PDF before running extraction.")
    else:
        pdf_bytes = uploaded_file.getvalue()
        st.session_state["pdf_bytes"] = pdf_bytes
        st.session_state["selected_field"] = None
        st.session_state["page_number"] = 1

        with st.spinner("Running OCR and Gemini extraction. This can take a few minutes."):
            try:
                st.session_state["result"] = call_extract_api(
                    api_base_url=api_base_url,
                    claim_type=claim_type,
                    claim_id=claim_id,
                    uploaded_filename=uploaded_file.name,
                    uploaded_file_type=uploaded_file.type or "application/pdf",
                    pdf_bytes=pdf_bytes,
                )
                st.success("Extraction completed.")
            except requests.HTTPError as exc:
                body = exc.response.text[:2000] if exc.response is not None else ""
                st.error(f"API returned an error: {exc}\n\n{body}")
            except requests.RequestException as exc:
                st.error(f"Could not call extraction API: {exc}")

result = st.session_state.get("result")
pdf_bytes = st.session_state.get("pdf_bytes")

if not result:
    st.info("Upload a PDF and run extraction to see document classification and extracted values.")
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
                    "Document Type": group.get("document_type"),
                    "Start": group.get("start_page"),
                    "End": group.get("end_page"),
                    "Pages": ", ".join(str(page) for page in group.get("pages", [])),
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
    st.subheader("PDF Citation Viewer")
    if not pdf_bytes:
        st.warning("PDF bytes are not available. Re-upload and rerun extraction.")
        st.stop()

    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    total_pdf_pages = document.page_count

    citations = selected_citations()
    default_page = selected_page()
    page_number = st.number_input(
        "Page",
        min_value=1,
        max_value=max(total_pdf_pages, 1),
        value=max(1, min(default_page, total_pdf_pages)),
        step=1,
    )
    st.session_state["page_number"] = page_number
    zoom = st.slider("Zoom", min_value=1.0, max_value=3.0, value=1.6, step=0.1)

    selected = st.session_state.get("selected_field")
    if selected:
        st.markdown(f"**Selected field:** `{selected['path']}`")
        st.write(truncate(selected["value"], 180))
        if citations:
            st.caption(
                "Highlighting "
                f"{sum(1 for citation in citations if citation.get('page_number') == page_number)} "
                f"citation(s) on page {page_number}."
            )
            with st.expander("Citation text"):
                for citation in citations:
                    if citation.get("page_number") == page_number:
                        st.write(
                            f"Line {citation.get('line_index')}: "
                            f"{citation.get('text', '')}"
                        )
        else:
            st.info("The selected field does not have citation coordinates.")
    else:
        st.info("Click `View` beside an extracted value to jump to its citation.")

    rendered_page = render_pdf_page(
        pdf_bytes=pdf_bytes,
        page_number=page_number,
        citations=citations,
        zoom=zoom,
    )
    st.image(rendered_page, use_container_width=True)
