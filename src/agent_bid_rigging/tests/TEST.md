# Test Plan

## Test Inventory Plan

- `test_core.py`: 9 unit tests planned
- `test_full_e2e.py`: 3 end-to-end tests planned

## Unit Test Plan

- `utils/file_loader.py`
  - test plain text loading and normalization
  - test zip archive ingestion and aggregation
  - edge cases: unsupported suffix
  - expected tests: 3
- `core/extractor.py`
  - extract phone, email, price, and template-filtered lines
  - edge cases: no price present
  - expected tests: 2
- `core/scoring.py`
  - score supplier pair from overlapping identifiers and text
  - edge cases: low-risk pair with no overlap and signature-page noise
  - expected tests: 2
- `core/opinion.py`
  - generate deterministic review opinion from structured report
  - edge cases: high-risk pair should be called out in the conclusion
  - expected tests: 1
- `core/artifacts.py`
  - classify known document types and support structured artifact generation
  - edge cases: unknown vs known document labels
  - expected tests: 1

## E2E Test Plan

- run the installed or module CLI on sample tender and bid files
- run the CLI on zip archives directly
- verify JSON or report output structure
- verify that the run directory contains generated artifacts

## Realistic Workflow Scenarios

- Workflow name: basic collusion screen
  - Simulates: one tender with three bids where two suppliers share suspicious identifiers
  - Operations chained: load tender, load bids, extract, compare, score, write artifacts
  - Verified: pairwise risk order and run artifact files

- Workflow name: clean comparison
  - Simulates: two suppliers with distinct data and limited overlap
  - Operations chained: same as above
  - Verified: low or medium risk without false critical classification

- Workflow name: archive review
  - Simulates: one tender zip and multiple bid zips with nested text components
  - Operations chained: unzip, aggregate, extract, compare, write artifacts
  - Verified: zip input support and artifact generation

## Test Results

```text
============================= test session starts ==============================
platform darwin -- Python 3.11.9, pytest-9.0.2, pluggy-1.6.0 -- /Library/Frameworks/Python.framework/Versions/3.11/bin/python3
cachedir: .pytest_cache
rootdir: /Users/linzeran/code/2026-zn/agent_bid_rigging
configfile: pyproject.toml
testpaths: src/agent_bid_rigging/tests
plugins: anyio-4.8.0
collecting ... collected 11 items

src/agent_bid_rigging/tests/test_core.py::test_load_plain_text_document PASSED
src/agent_bid_rigging/tests/test_core.py::test_unsupported_suffix_raises PASSED
src/agent_bid_rigging/tests/test_core.py::test_load_zip_archive_with_multiple_documents PASSED
src/agent_bid_rigging/tests/test_core.py::test_extract_signals_filters_tender_template PASSED
src/agent_bid_rigging/tests/test_core.py::test_pairwise_scoring_finds_shared_signals PASSED
src/agent_bid_rigging/tests/test_core.py::test_pairwise_scoring_can_stay_low PASSED
src/agent_bid_rigging/tests/test_core.py::test_signature_noise_does_not_create_high_risk PASSED
src/agent_bid_rigging/tests/test_core.py::test_template_opinion_mentions_high_risk_pair PASSED
src/agent_bid_rigging/tests/test_full_e2e.py::TestCLIEndToEnd::test_help PASSED
src/agent_bid_rigging/tests/test_full_e2e.py::TestCLIEndToEnd::test_analyze_generates_artifacts PASSED
src/agent_bid_rigging/tests/test_full_e2e.py::TestCLIEndToEnd::test_analyze_accepts_zip_archives PASSED

============================== 11 passed in 0.48s ===============================
```

## Summary Statistics

- Total tests: 11
- Pass rate: 100%
- Execution time: 0.48s

## Coverage Notes

- Covered: plain text loading, zip archive ingestion, extraction, scoring, signature-noise filtering, opinion drafting, CLI help, end-to-end artifact generation, zip-input CLI flow
- Not yet covered: `.docx` parsing regression cases, explicit `pdftotext` branch validation, malformed procurement tables, OCR/scanned files
