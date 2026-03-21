# PDF Long-Document Review Format

## Background

New sample set:

- tender as a single text-heavy PDF
- each bid as a single long PDF
- technical, business, qualification, and pricing content are mixed into chaptered documents

This differs from the previous archive-oriented format where evidence came from many separate files inside one package.

## Key Observations

From the new sample set:

- the tender PDF is text-extractable and contains project number, qualification rules, submission requirements, and contact instructions
- bidder A uses a qualification-first structure with response letter, legal representative, authorization, licenses, audit, tax, social insurance, and commitment materials
- bidder B uses a solution-first structure with project overview, architecture, functional design, deployment, and technical sections
- bidder C uses a standard bid structure with bid letter, opening table, qualification section, deviation tables, experience list, technical plan, implementation plan, operation plan, and training plan

This means the main challenge is no longer archive aggregation.
The main challenge becomes chapter-aware PDF understanding.

## Architectural Position

The existing layered architecture still works:

1. `capabilities`
2. `fusion`
3. `ReviewFacts`
4. `scoring`
5. `artifacts`
6. `llm_review`

We should not redesign the whole system.
We should shift capability focus from:

- multi-file package aggregation
- OCR-first supplementation

to:

- PDF chapter segmentation
- table extraction
- section-level comparison
- OCR as a fallback for scans and embedded images

## Required Capability Changes

### 1. PDF Sectioning Capability

New capability goal:

- split a long PDF into logical sections
- identify section title
- estimate start page and end page
- extract per-section text

Expected section families:

- bid letter / response letter
- opening table / quotation table
- qualification review section
- legal representative / authorization section
- business deviation section
- technical deviation section
- technical proposal
- implementation plan
- operation plan
- training plan
- experience list

This should live under `capabilities`, not `core`.

### 2. Table Extraction Capability

Critical tables in the new format:

- opening table
- quotation table
- technical deviation table
- business deviation table
- experience table

The system needs structured extraction, not only raw text OCR.

### 3. OCR As Secondary Path

OCR is still useful, but no longer the main entry path for this format.

Recommended use:

- scanned qualification pages
- embedded certificates
- screenshots
- image-heavy appendices

Main flow should prefer text extraction first.

## ReviewFacts Impact

`ReviewFacts` remains the correct integration point.

New fact families to emphasize:

- `bid_total_amount`
- `quotation_items`
- `company_name`
- `legal_representative`
- `authorized_representative`
- `phone`
- `email`
- `address`
- `bank_account`
- `license_number`
- `registration_number`
- `experience_projects`
- `technical_sections`
- `implementation_sections`
- `training_sections`
- `deviation_rows`

Facts should keep:

- source document
- source page
- source section
- source type (`text`, `table`, `ocr`)
- confidence

## Scoring Impact

The scoring layer should continue to consume `ReviewFacts`, but new section-aware rules are needed.

### Rules To Add Or Strengthen

- chapter structure similarity
- opening table / quotation similarity
- business deviation similarity
- technical deviation similarity
- experience overlap
- section-level technical proposal similarity
- implementation plan similarity
- training/operation plan similarity with template downweighting

### Rules To Keep Downweighted

Do not over-score common:

- response letters
- commitment letters
- standard business promises
- generic training and after-sales text
- platform template sections

## Strategy Impact

For this format, strategy should become:

1. text extraction first
2. chapter identification
3. key table extraction
4. OCR only for gaps or scans
5. LLM only after structured facts are complete

This is more efficient than sending the full PDF corpus into OCR.

## Recommended Implementation Direction

### Phase A

Add chapter-aware PDF parsing:

- section title discovery
- section-to-page mapping
- section text extraction

### Phase B

Add structured table extraction:

- opening table
- quotation
- deviation tables
- experience table

### Phase C

Extend `ReviewFacts` and `scoring` for section-aware facts and comparisons.

### Phase D

Update `formal_report` and `opinion` so findings cite:

- section name
- page
- snippet

instead of only generic document-level text.

## Success Criteria

The new format is considered supported when:

- one tender PDF and multiple bidder PDFs can run end-to-end
- opening table fields are extracted reliably
- bidder qualification fields are extracted from long PDFs
- section-level technical similarity can be assessed
- reports cite section/page/snippet level evidence
- OCR is only used when text/table parsing is insufficient
