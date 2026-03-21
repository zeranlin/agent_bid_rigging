# AGENTS.md

This repository is designed for agent-first execution. Treat this file as a map, not an encyclopedia.

## Start here

1. Read [ARCHITECTURE.md](/Users/linzeran/code/2026-zn/agent_bid_rigging/ARCHITECTURE.md) for the system layers and the review loop.
2. Read [docs/design-docs/index.md](/Users/linzeran/code/2026-zn/agent_bid_rigging/docs/design-docs/index.md) for design intent.
3. Check [docs/exec-plans/active/bootstrap-harness.md](/Users/linzeran/code/2026-zn/agent_bid_rigging/docs/exec-plans/active/bootstrap-harness.md) for the active plan.
4. Keep outputs reproducible by writing run artifacts into `runs/`.

## Working rules

- Prefer extending existing modules over creating parallel implementations.
- Preserve review traceability: every suspicion score should be backed by evidence text.
- Keep human-readable and machine-readable outputs aligned.
- Do not hide parser failures. Surface them in the run manifest.
- When adding new checks, update docs and tests in the same change.
- Treat `.zip` archives and extracted bid directories as first-class inputs, not edge cases.
- New design documents should be written in Chinese by default unless there is a special reason to do otherwise.

## Key code paths

- `src/agent_bid_rigging/cli.py`: CLI entry point and REPL
- `src/agent_bid_rigging/capabilities/`: reusable atomic abilities such as OCR and metadata extraction
- `src/agent_bid_rigging/core/runner.py`: end-to-end run orchestration
- `src/agent_bid_rigging/core/extractor.py`: signal extraction
- `src/agent_bid_rigging/core/opinion.py`: review opinion generation
- `src/agent_bid_rigging/core/scoring.py`: pairwise risk scoring
- `src/agent_bid_rigging/utils/openai_client.py`: OpenAI Responses API adapter
- `src/agent_bid_rigging/utils/file_loader.py`: document backend selection

## Documents

- Architecture: [ARCHITECTURE.md](/Users/linzeran/code/2026-zn/agent_bid_rigging/ARCHITECTURE.md)
- Design docs: [docs/design-docs/index.md](/Users/linzeran/code/2026-zn/agent_bid_rigging/docs/design-docs/index.md)
- Plan index: [docs/PLANS.md](/Users/linzeran/code/2026-zn/agent_bid_rigging/docs/PLANS.md)
- Test plan: [src/agent_bid_rigging/tests/TEST.md](/Users/linzeran/code/2026-zn/agent_bid_rigging/src/agent_bid_rigging/tests/TEST.md)
