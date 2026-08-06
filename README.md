# Claims Hackathon

FastAPI prototype for the health claims medical adjudication pipeline.

The first implemented phase accepts claim documents, splits PDFs into pages, calls Azure Document Intelligence `prebuilt-read` for each page in parallel, and returns page-wise OCR with coordinates.

Pipeline shape:

```text
PDF/images
  -> split into pages
  -> Azure OCR per page in parallel
  -> preserve page-wise OCR as source of truth
```

Classification and grouping are intentionally not done in this endpoint. The next pipeline step should pass `pages[]` to the LLM and let that stage classify pages and group document ranges.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Set Azure credentials. The names match the Quick Vision server config, with Azure SDK aliases also supported.

```bash
export AZURE_READ_SERVICE_ENDPOINT="https://<resource>.cognitiveservices.azure.com/"
export AZURE_READ_SERVICE_KEY="<key>"
```

Optional tuning:

```bash
export AZURE_OCR_MAX_WORKERS=6
export AZURE_OCR_MAX_RETRIES=3
export AZURE_READ_MODEL=prebuilt-read
```

## Run

```bash
uvicorn app.main:app --reload
```

## OCR Endpoint

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/claims/ocr" \
  -F "claim_id=CLAIM-001" \
  -F "documents=@/path/to/claim-bundle.pdf"
```

The default response is compact. It stores full OCR geometry server-side and returns an `ocr_id`.

Response shape:

```json
{
  "ocr_id": "...",
  "response_mode": "compact",
  "claim_id": "CLAIM-001",
  "status": "ocr_completed",
  "model": "prebuilt-read",
  "total_documents": 1,
  "total_pages": 3,
  "succeeded_pages": 3,
  "failed_pages": 0,
  "pages": [
    {
      "page_number": 1,
      "document_index": 0,
      "filename": "claim-bundle.pdf",
      "source_page_number": 1,
      "ocr_text": "...",
      "width": 8.5,
      "height": 11,
      "unit": "inch",
      "lines": [
        {
          "line_index": 0,
          "text": "Patient Name: ..."
        }
      ]
    }
  ],
  "documents": [
    {
      "document_index": 0,
      "filename": "claim-bundle.pdf",
      "page_count": 3,
      "failed_pages": []
    }
  ],
  "combined_text": "..."
}
```

Use top-level `pages` for the next LLM pipeline phase. `documents` is retained only for tracing uploaded files, and `combined_text` is a convenience/debug field without coordinates.

To retrieve stored full OCR with line/word polygons:

```bash
curl "http://127.0.0.1:8000/api/v1/claims/ocr/<ocr_id>?response_mode=full"
```

You can also request full OCR directly:

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/claims/ocr?response_mode=full" \
  -F "claim_id=CLAIM-001" \
  -F "documents=@/path/to/claim-bundle.pdf"
```

## OCR + Extraction Endpoint

This endpoint runs Azure OCR first, then sends overlapping page windows to Gemini. Gemini classifies pages and extracts fields in the same pass. The backend resolves Gemini's page/line evidence to Azure OCR coordinates.

Gemini receives compact OCR only:

```json
{
  "page_number": 1,
  "lines": [
    {"line_index": 0, "text": "Patient Name: ..."}
  ]
}
```

The backend keeps full OCR geometry in memory and resolves the model's `page_number` + `line_indices` evidence into citation polygons. The extraction response includes only cited coordinates, not all OCR coordinates.

Required environment:

```bash
export GEMINI_API_KEY="<key>"
export GEMINI_MODEL="gemini-2.5-flash"
```

Optional window tuning:

```bash
export EXTRACTION_WINDOW_SIZE=6
export EXTRACTION_WINDOW_OVERLAP=1
```

Cashless:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/claims/extract \
  -F "claim_type=cashless" \
  -F "claim_id=CLAIM-001" \
  -F "documents=@/path/to/claim-bundle.pdf"
```

Reimbursement:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/claims/extract \
  -F "claim_type=reimbursement" \
  -F "claim_id=CLAIM-001" \
  -F "documents=@/path/to/claim-bundle.pdf"
```

Extraction response shape:

```json
{
  "claim_id": "CLAIM-001",
  "claim_type": "cashless",
  "ocr": {
    "pages": []
  },
  "extraction": {
    "token_consumption": {
      "cumulative": {
        "input_tokens": 12150,
        "output_tokens": 1840,
        "total_tokens": 13990,
        "cached_input_tokens": 0,
        "thoughts_tokens": 0,
        "tool_use_prompt_tokens": 0,
        "call_count": 3,
        "successful_call_count": 3,
        "failed_call_count": 0
      },
      "calls": [
        {
          "call_index": 0,
          "call_name": "gemini_extract_window_0",
          "model": "gemini-2.5-flash",
          "page_numbers": [1, 2, 3, 4],
          "status": "succeeded",
          "input_tokens": 4050,
          "output_tokens": 620,
          "total_tokens": 4670,
          "cached_input_tokens": 0,
          "thoughts_tokens": 0,
          "tool_use_prompt_tokens": 0
        }
      ]
    },
    "page_classifications": [
      {
        "page_number": 1,
        "document_type": "Pre Auth Form",
        "confidence": 0.94,
        "reason": "Contains cashless pre-auth fields and hospital estimate details"
      }
    ],
    "extracted_fields": [
      {
        "catalog_path": "patientAdmissionDetails.expectedCostOfHospitalization",
        "schema_path": "patientAdmissionDetails.expectedCostOfHospitalization",
        "value": "185000",
        "confidence": 0.91,
        "citations": [
          {
            "page_number": 1,
            "line_index": 42,
            "text": "Expected cost of hospitalization: Rs. 1,85,000",
            "polygon": [{"x": 1.0, "y": 4.2}],
            "page_unit": "inch"
          }
        ]
      }
    ],
    "final_output": {
      "patientAdmissionDetails": {
        "expectedCostOfHospitalization": {
          "value": "185000",
          "confidence": 0.91,
          "citations": []
        }
      }
    }
  }
}
```

For array fields, Gemini returns concrete paths such as `invoiceDetails[0].services[2].grossAmount`, and the backend assembles that into nested arrays in `final_output`.
