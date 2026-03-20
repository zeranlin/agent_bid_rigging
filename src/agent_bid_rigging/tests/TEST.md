# Test Plan

## Test Inventory Plan

- `test_core.py`: 5 unit tests planned
- `test_full_e2e.py`: 2 end-to-end tests planned

## Unit Test Plan

- `utils/file_loader.py`
  - test plain text loading and normalization
  - edge cases: unsupported suffix
  - expected tests: 2
- `core/extractor.py`
  - extract phone, email, price, and template-filtered lines
  - edge cases: no price present
  - expected tests: 2
- `core/scoring.py`
  - score supplier pair from overlapping identifiers and text
  - edge cases: low-risk pair with no overlap
  - expected tests: 1

## E2E Test Plan

- run the installed or module CLI on sample tender and bid files
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

## Test Results

```text
============================= test session starts ==============================
platform darwin -- Python 3.11.9, pytest-9.0.2, pluggy-1.6.0 -- /Library/Frameworks/Python.framework/Versions/3.11/bin/python3
cachedir: .pytest_cache
rootdir: /Users/linzeran/code/2026-zn/agent_bid_rigging
configfile: pyproject.toml
testpaths: src/agent_bid_rigging/tests
plugins: anyio-4.8.0
collecting ... collected 7 items

src/agent_bid_rigging/tests/test_core.py::test_load_plain_text_document PASSED [ 14%]
src/agent_bid_rigging/tests/test_core.py::test_unsupported_suffix_raises PASSED [ 28%]
src/agent_bid_rigging/tests/test_core.py::test_extract_signals_filters_tender_template PASSED [ 42%]
src/agent_bid_rigging/tests/test_core.py::test_pairwise_scoring_finds_shared_signals PASSED [ 57%]
src/agent_bid_rigging/tests/test_core.py::test_pairwise_scoring_can_stay_low PASSED [ 71%]
src/agent_bid_rigging/tests/test_full_e2e.py::TestCLIEndToEnd::test_help PASSED [ 85%]
src/agent_bid_rigging/tests/test_full_e2e.py::TestCLIEndToEnd::test_analyze_generates_artifacts PASSED [100%]

============================== 7 passed in 0.16s ===============================
```

## Summary Statistics

- Total tests: 7
- Pass rate: 100%
- Execution time: 0.16s

## Coverage Notes

- Covered: plain text loading, unsupported format handling, extraction, scoring, CLI help, end-to-end artifact generation
- Not yet covered: `.docx` parsing, external `pdftotext` backend integration, malformed procurement tables, OCR/scanned files
