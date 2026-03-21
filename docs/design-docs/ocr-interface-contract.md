# OCR Interface Contract

## Positioning

`capabilities/ocr` is an atomic capability layer.
It does not decide bid rigging risk.
It only accepts OCR requests and returns structured OCR facts.

## Request Object

Main object: `OcrRequest`

Fields:

- `mode`
  - `generic`: return broadly useful OCR output
  - `targeted`: prioritize requested document types and fields
- `doc_types`
  - caller-expected document types such as `business_license`, `quotation`, `authorization_letter`
- `fields`
  - caller-expected fields such as `company_name`, `bid_total_amount`, `license_number`
- `page_hints`
  - optional page hints for future page-level routing
- `file_hints`
  - optional filename/path hints to narrow OCR scope
- `max_sources`
  - optional cap on discovered source files
- `max_images`
  - optional cap on extracted images
- `confidence_threshold`
  - reserved for downstream gating
- `include_raw_text`
  - whether caller expects extracted raw text
- `include_images`
  - whether caller expects image entries in response
- `include_debug_payload`
  - whether to keep extra debugging payload in future adapters
- `metadata`
  - free-form caller metadata

## Response Object

Main object: `OcrResponse`

Fields:

- `request`
- `source_path`
- `output_dir`
- `source_count`
- `image_count`
- `images`
- `image_results`
- `warnings`

This response is capability-level and reusable across multiple business modules.

## Modes

### generic

Used when caller has no narrow business ask.

Expected behavior:

- discover OCR-compatible inputs
- extract images
- classify image/doc type
- return broad structured fields
- preserve raw extracted text

### targeted

Used when caller knows what it needs.

Expected behavior:

- prioritize requested `doc_types`
- prioritize requested `fields`
- allow scope reduction via `file_hints`, `max_sources`, `max_images`
- still return honest `doc_type` and `summary` if image is not relevant

## Relationship To Review Flow

Main review flow is only a caller of OCR.

Recommended layering:

1. `capabilities/ocr`
   - accept `OcrRequest`
   - return `OcrResponse`
2. `fusion`
   - merge OCR facts with text-extracted facts
   - handle confidence, conflicts, preferred sources
3. `core`
   - score and assess pairwise bid-rigging risk from unified facts
4. `llm_review`
   - explain and write based on unified facts and scored evidence

This keeps OCR isolated and reusable for non-review modules.
