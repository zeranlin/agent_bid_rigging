# Bootstrap Harness Plan

## Objective

Create the first runnable version of the bid-rigging review harness from an empty repository.

## Scope

- repository map and agent docs
- installable Python package
- CLI and REPL
- document parsers
- extraction and scoring engine
- run artifacts
- tests and sample data

## Progress Log

- 2026-03-20: repository bootstrapped from empty remote
- 2026-03-20: implementing deterministic review loop and artifact writer

## Exit Criteria

- `pip install -e .` succeeds
- example run produces a report under `runs/`
- automated tests pass locally
