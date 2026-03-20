# SOP Phase 1 Plan

## Objective

Implement the first SOP-aligned milestone: auditable intermediate artifacts and structured review outputs.

## Deliverables

- source file registration with hashes
- extracted component index for archive and directory inputs
- basic document catalog
- structured entity field table
- structured price analysis table
- review conclusion table that separates facts, suspicious clues, exclusions, and recommendations

## Non-goals

- OCR
- authorization chain analysis
- timeline extraction
- evidence A/B/C/D grading

## Exit Criteria

- `analyze` produces Phase 1 artifact tables in every run directory
- tests cover the new outputs
- existing example and archive workflows still pass
