# PDF Long-Document Format Plan

## Objective

Support tender and bid materials delivered as single long PDFs with chaptered structure.

## Scope

In scope:

- chapter-aware PDF parsing
- key table extraction
- section-level fact fusion
- section-aware scoring inputs
- report evidence upgraded to section/page/snippet references

Out of scope for the first pass:

- full OCR-first document understanding
- scanned-only corpus support
- advanced layout/vision benchmarking

## Deliverables

### Phase 1: Section Parsing

- `capabilities/pdf_sectioning`
- extracted section list for each PDF
- section title, start page, end page, section text

### Phase 2: Table Extraction

- opening table extraction
- quotation table extraction
- deviation table extraction
- experience table extraction

### Phase 3: Fact Fusion

- `ReviewFacts` extended for section-aware and table-aware facts
- source metadata includes section and page

### Phase 4: Scoring

- structure similarity updated for long-PDF format
- technical/implementation/deviation comparison rules
- template downweighting for generic commitment/training text

### Phase 5: Reporting

- `formal_report.md` cites section/page/snippet
- appendix rows cite section/page/snippet
- `opinion.md` uses the same section-aware evidence summary

## Implementation Steps

1. Add a PDF section parser under `capabilities`
2. Emit per-document section catalog
3. Add table extraction helpers for opening/quotation/deviation/experience sections
4. Extend fusion to map section and table output into `ReviewFacts`
5. Update scoring to consume new facts
6. Update report generators to cite section/page/snippet
7. Add sample-based tests for the new PDF set

## Acceptance Criteria

- the new tender PDF can be parsed into usable sections
- each bidder PDF yields at least:
  - bid letter section
  - qualification-related section
  - pricing/opening section when present
  - technical/implementation/training sections when present
- bid amount extraction works from opening/quotation sections
- long-document section similarity can be analyzed without relying on OCR as the main path
- reports stay readable and evidence references are traceable

## Risks

- bidder PDFs may use inconsistent heading styles
- some tables may flatten badly in plain text extraction
- some “technical similarity” is legitimate template reuse and needs downweighting
- OCR fallback may still be needed for scanned qualifications

## Notes

This plan reuses the current architecture.
It does not replace `ReviewFacts`, `strategy`, `scoring`, or `llm_review`.
It adds a new format-specific capability layer and feeds the existing review chain through better structured facts.
