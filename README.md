# agent_bid_rigging

`agent_bid_rigging` is an agent-first review harness for government procurement anti-collusion screening. It ingests one tender document and multiple supplier bid documents, extracts comparable signals, performs pairwise suspicious-pattern checks, and writes a review artifact bundle that a human auditor can verify.

The repository is intentionally shaped by harness engineering ideas from OpenAI:

- start from an empty repository and make the repository itself the operating surface
- keep `AGENTS.md` short and use `docs/` as the source-of-truth map
- build a repeatable loop of task definition, tool execution, evidence capture, scoring, and review artifacts

Relevant references:

- [Harness engineering](https://openai.com/zh-Hans-CN/index/harness-engineering/)
- [Unrolling the Codex agent loop](https://openai.com/zh-Hans-CN/index/unrolling-the-codex-agent-loop/)

## What the harness does

1. Load a tender package and multiple bid packages from disk.
2. Normalize document text using parser backends and recursive package ingestion.
3. Extract suspicious signals:
   - shared phone numbers, emails, addresses, legal representatives, and bank accounts
   - bid amount proximity and exact matches
   - repeated non-template text across suppliers
   - identical rare lines that do not originate from the tender
4. Score each supplier pair and classify the result as `low`, `medium`, `high`, or `critical`.
5. Generate a structured review opinion document, with optional LLM drafting.
6. Persist a full run directory with machine-readable JSON and human-readable Markdown artifacts.

## Repository map

- `AGENTS.md`: concise agent operating map
- `ARCHITECTURE.md`: system layers and review loop
- `docs/design-docs/`: design intent and core beliefs
- `docs/exec-plans/`: active and completed execution plans
- `src/agent_bid_rigging/`: CLI harness and review engine
- `runs/`: generated review artifacts
- `examples/`: sample tender and bid documents

## Quick start

```bash
cd /Users/linzeran/code/2026-zn/agent_bid_rigging
python3 -m pip install -e .
agent-bid-rigging analyze \
  --tender examples/tender.txt \
  --bid alpha=examples/bid_alpha.txt \
  --bid beta=examples/bid_beta.txt \
  --bid gamma=examples/bid_gamma.txt \
  --opinion-mode auto
```

Real procurement-package example:

```bash
agent-bid-rigging analyze \
  --tender 招标文件-01-胃肠镜.zip \
  --bid 恒禾=投标文件-01-恒禾.zip \
  --bid 华康=投标文件-01-华康.zip \
  --bid 唯美=投标文件-01-唯美.zip \
  --output-dir runs/wcb_review \
  --opinion-mode template
```

The command creates a timestamped directory under `runs/` containing:

- `manifest.json`
- `case_manifest.json`
- `source_file_index.json`
- `extracted_file_index.json`
- `document_catalog.json`
- `entity_field_table.json`
- `price_analysis_table.json`
- `structure_similarity_table.json`
- `file_fingerprint_table.json`
- `duplicate_detection_table.json`
- `text_similarity_table.json`
- `shared_error_table.json`
- `authorization_chain_table.json`
- `license_match_table.json`
- `timeline_table.json`
- `evidence_grade_table.json`
- `risk_score_table.json`
- `review_conclusion_table.json`
- `formal_report.json`
- `formal_report.rule.json`
- `formal_report.rule.md`
- `formal_report.md`
- `normalized/*.json`
- `pairwise_report.json`
- `summary.md`
- `opinion.json`
- `opinion.rule.json`
- `opinion.rule.md`
- `opinion.md`

## LLM review agent

The harness now includes an opinion drafting layer:

- `--opinion-mode template`: always generate a deterministic opinion template
- `--opinion-mode llm`: require an LLM draft through OpenAI Responses API
- `--opinion-mode auto`: use OpenAI when `OPENAI_API_KEY` is configured, otherwise fall back to the deterministic template

Environment variables:

- `OPENAI_API_KEY`: enables LLM opinion drafting
- `OPENAI_MODEL`: optional model override, default `gpt-5`
- `OPENAI_BASE_URL`: optional OpenAI-compatible root URL or Responses endpoint override
- `OPENAI_TIMEOUT`: optional request timeout in seconds, default `1800`
- `OPENAI_REASONING_EFFORT`: optional reasoning effort override, for example `low`
- `OPENAI_NO_THINKING`: optional boolean flag for compatible endpoints, set `1` to send `enable_thinking=false`
- `AGENT_BID_RIGGING_ASYNC_LLM`: optional boolean flag, set `1` only if you want LLM enhancement to continue in the background instead of blocking the main run

Example for a self-hosted OpenAI-compatible endpoint:

```bash
export OPENAI_BASE_URL="http://112.111.54.86:10011/v1"
export OPENAI_MODEL="qwen3.5-27b"
export OPENAI_API_KEY="your-password-or-api-key"
export OPENAI_TIMEOUT="1800"
export OPENAI_NO_THINKING="1"
agent-bid-rigging analyze \
  --tender 招标文件.zip \
  --bid A=投标文件A.zip \
  --bid B=投标文件B.zip \
  --opinion-mode llm
```

By default, when `--opinion-mode llm` is enabled, the harness waits for the full LLM review chain to finish before considering the run complete. This is the recommended setting for slow local models. If you explicitly want a non-blocking run that writes the rule-based artifacts first and lets LLM enhancement continue in the background, set `AGENT_BID_RIGGING_ASYNC_LLM=1`.

When LLM review is enabled, the harness keeps both report variants:

- `formal_report.rule.md`: deterministic rule/template report
- `formal_report.llm.md`: LLM-enhanced report, written when LLM finishes successfully
- `opinion.rule.md`: deterministic rule/template opinion
- `opinion.llm.md`: LLM-enhanced opinion, written when LLM finishes successfully
- `formal_report.md` and `opinion.md`: current default entrypoints, pointing to the best available version

If `OPENAI_BASE_URL` ends with `/v1`, the harness automatically appends `/responses`.

The OpenAI integration uses the official Responses API pattern documented by OpenAI:

- [OpenAI Platform overview](https://platform.openai.com/docs/overview)
- [Responses API reference](https://platform.openai.com/docs/api-reference/responses/create?api-mode=responses)
- [Migrate to the Responses API](https://platform.openai.com/docs/guides/migrate-to-responses)

## Supported inputs

- single files: `.txt`, `.md`, `.json`, `.docx`, `.pdf`
- directories containing nested supported files
- `.zip` archives containing nested supported files

PDF parsing prefers `pdftotext` when available and falls back to `pypdf` automatically.

## Current scope

This remains a review harness, not a final legal adjudication engine. It produces evidence-backed suspicion indicators and a draft opinion for human procurement reviewers. Later iterations can add OCR, richer metadata extraction, benchmark datasets, and stronger multi-document reasoning.
