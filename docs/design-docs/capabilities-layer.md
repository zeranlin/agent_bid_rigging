# Capabilities Layer

## Purpose

As the repository grows beyond plain-text document parsing, we need a place for reusable atomic abilities that are not themselves procurement-review logic.

`capabilities/` is that layer.

## What belongs here

- OCR
- image understanding
- table extraction
- PDF and Office metadata extraction
- signature and stamp parsing
- page-type and document-type classification

## What does not belong here

- supplier pair scoring
- anti-collusion evidence grading
- procurement-domain report writing
- risk conclusion logic

Those remain in `core/`.

## Contract with core

`capabilities/` produces structured facts plus evidence and warnings.
`core/` consumes those facts, weighs them against procurement-domain rules, and decides what matters.

This keeps the repository extensible:

- we can swap OCR backends without rewriting the scoring engine
- we can test vision capabilities without touching reporting logic
- we can reuse atomic abilities in future review products beyond bid-rigging

## Layer map

1. `ingest` or loader code obtains source files and extracted pages.
2. `capabilities/` turns those sources into structured technical outputs.
3. `core/` turns technical outputs into business judgments.
4. `cli.py` and `web/` present the results to users.

## First practical use

The first major consumer of this layer is expected to be OCR for scanned procurement packages and embedded images, likely backed by the local multimodal model already used in the environment.
