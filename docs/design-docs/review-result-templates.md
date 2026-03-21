# Review Result Templates

## Goal

Define a stable output contract for bid-rigging review results so that:

- rule-based and LLM-enhanced outputs use the same section order
- reviewers can quickly find facts, clues, exclusions, and recommendations
- structured tables and markdown reports stay aligned

## Output Layers

### 1. Quick Summary

Audience:
- reviewers doing first-pass triage
- managers who only need the top conclusion

Required sections:
- project name / project id
- supplier list
- overall conclusion
- top suspicious supplier pairs
- next-step recommendation

Primary file:
- `summary.md`

### 2. Formal Review Report

Audience:
- procurement reviewers
- archive / case bundle readers

Required sections:
1. project basic info
2. review purpose
3. review basis
4. review scope and document acceptance
5. review method
6. review status
7. suspicious clues
8. exclusionary factors
9. preliminary conclusion
10. follow-up checks
11. notes

Inside `review status`, the report should keep these five fixed subsections:
- pricing comparison
- structure and text comparison
- identity / contact comparison
- authorization and qualification comparison
- timeline and generation-feature comparison

Primary files:
- `formal_report.json`
- `formal_report.md`

### 3. Review Opinion

Audience:
- reviewers who need a concise opinion memo
- LLM-enhanced narrative consumers

Required sections:
1. project overview
2. review basis and method
3. facts summary
4. suspicious clues
5. exclusionary factors
6. preliminary opinion
7. suggested follow-up checks
8. notes

Primary files:
- `opinion.json`
- `opinion.md`

### 4. Evidence Tables

Audience:
- auditors
- later agents / replay workflows

Required tables:
- `review_facts.json`
- `entity_field_table.json`
- `price_analysis_table.json`
- `authorization_chain_table.json`
- `license_match_table.json`
- `timeline_table.json`
- `evidence_grade_table.json`
- `risk_score_table.json`
- `review_conclusion_table.json`

## Template Rules

### Naming

- Use full supplier names in formal markdown when available.
- If short labels are needed for pairwise summaries, define the mapping once and stay consistent.
- Do not mix full names and short names in the same section without explanation.

### Facts vs. Opinions

- `review status` and `facts summary` should state observed facts only.
- each subsection may end with a short `审查意见` paragraph
- `preliminary conclusion` must be separate from fact description

### Suspicious Clues Coverage

- every supplier pair shown as `medium` or above in the risk table should have at least one clue entry in markdown
- clue ordering should follow risk score descending

### Exclusionary Factors

- exclusionary factors must be explicitly listed
- if none exist, write that no clear exclusionary factors were identified

### Conclusion Levels

Use exactly one of these normalized conclusion bands:
- no strong abnormal signal identified
- suspicious clues exist but evidence is insufficient, continue verification
- strong suspicious clues exist, prioritize enhanced verification

## Alignment Requirements

### `formal_report` alignment

- should be the most complete narrative artifact
- should use full project metadata
- should map directly to evidence tables

### `opinion` alignment

- should be shorter than `formal_report`
- should reuse the same conclusion band and same top suspicious pairs
- should not introduce new facts absent from `formal_report` or evidence tables

### LLM alignment

- LLM outputs should follow the same section contract
- LLM may improve explanation and wording, but must not change evidence hierarchy

## Current Implementation Direction

- `summary.md` stays as the fast triage surface
- `formal_report.md` is the primary full report body
- `opinion.md` is the concise opinion memo using the same fact and conclusion hierarchy
- `review_facts.json` is the canonical fact bundle for downstream reporting and LLM prompting
