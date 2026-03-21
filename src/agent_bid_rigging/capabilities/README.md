# Capabilities Layer

`capabilities/` stores atomic, reusable abilities that are not specific to bid-rigging judgment itself.

Examples:

- OCR for scanned PDFs and embedded images
- image classification and document-page description
- metadata extraction from PDF or Office files
- table extraction and normalization
- document or page-type classification

## Boundary

- `capabilities/` turns raw material into structured facts.
- `core/` turns structured facts into procurement-review judgments.
- `web/` and `cli.py` expose those workflows to humans and automation.

## Design rules

- Each capability should have a stable input contract and a structured output contract.
- Capabilities should be testable in isolation from the procurement review logic.
- Capabilities may use local models, remote APIs, or traditional libraries, but they should surface the backend used.
- Capability results should preserve evidence and warnings so the `core/` layer can decide how much to trust them.

## Initial planned modules

- `ocr/`: scanned PDF and image text extraction
- `vision/`: image description and image-level field extraction
- `metadata/`: file metadata and signature extraction
- `tables/`: table recognition and normalization
