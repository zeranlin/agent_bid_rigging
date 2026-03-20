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

1. Load a tender file and multiple bid files from disk.
2. Normalize document text using parser backends.
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

The command creates a timestamped directory under `runs/` containing:

- `manifest.json`
- `normalized/*.json`
- `pairwise_report.json`
- `summary.md`
- `opinion.json`
- `opinion.md`

## LLM review agent

The harness now includes an opinion drafting layer:

- `--opinion-mode template`: always generate a deterministic opinion template
- `--opinion-mode llm`: require an LLM draft through OpenAI Responses API
- `--opinion-mode auto`: use OpenAI when `OPENAI_API_KEY` is configured, otherwise fall back to the deterministic template

Environment variables:

- `OPENAI_API_KEY`: enables LLM opinion drafting
- `OPENAI_MODEL`: optional model override, default `gpt-5`
- `OPENAI_BASE_URL`: optional Responses API endpoint override

The OpenAI integration uses the official Responses API pattern documented by OpenAI:

- [OpenAI Platform overview](https://platform.openai.com/docs/overview)
- [Responses API reference](https://platform.openai.com/docs/api-reference/responses/create?api-mode=responses)
- [Migrate to the Responses API](https://platform.openai.com/docs/guides/migrate-to-responses)

## Supported formats

- `.txt`, `.md`, `.json`
- `.docx` through direct OOXML extraction
- `.pdf` through the external `pdftotext` backend if installed

## Current scope

This remains a review harness, not a final legal adjudication engine. It produces evidence-backed suspicion indicators and a draft opinion for human procurement reviewers. Later iterations can add OCR, richer metadata extraction, benchmark datasets, and stronger multi-document reasoning.
