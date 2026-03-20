# Review Loop

## Input contract

- exactly one tender document
- two or more supplier bid documents
- optional run label and output directory

## Loop stages

1. Parse files into normalized text.
2. Extract entities and suspicious line fingerprints.
3. Build supplier-to-supplier comparison matrix.
4. Score each pair using weighted heuristics.
5. Produce:
   - machine JSON for automation
   - markdown summary for auditors
   - reusable artifact files for later agent runs

## Why this is a harness

The loop is stable, replayable, and tool-oriented. An LLM can later sit on top of it, but the harness already defines:

- what tools are available
- what state is persisted
- what observations feed the next step
- what a final review artifact must contain
