# Bid-Rigging Decision Model

## Purpose

Define the business judgment model for one core question:

**Do the bidder submissions contain enough suspicious signals to justify a bid-rigging concern between one or more supplier pairs?**

This document is upstream of `ReviewFacts`, `strategy`, OCR, and LLM usage. The system should first define what must be judged, then derive which facts are needed, and only then decide which capabilities to run.

## Design order

The design order for this repository should be:

1. Decision model
2. Unified facts model
3. Review strategy
4. Atomic capabilities
5. Reporting

This means:

- `scoring` should be driven by explicit judgment dimensions.
- `ReviewFacts` should only carry facts that serve those dimensions.
- `strategy` should only request OCR/LLM/table extraction when those facts are missing or weak.

## Core judgment target

The business layer does **not** try to directly prove a legal conclusion. It produces one of three review outcomes for each supplier pair:

1. `no_clear_signal`
   Current materials do not show sufficient suspicious signals.
2. `needs_follow_up`
   Suspicious signals exist, but current evidence is insufficient and follow-up checks are required.
3. `priority_review`
   Multiple strong signals exist and the pair should be treated as a priority target for further investigation.

The system output is therefore:

- pair-level suspicion judgment
- case-level summary of which supplier pairs are most suspicious
- evidence-backed explanation of why

## Judgment dimensions

The business layer should evaluate supplier pairs across six dimensions.

### 1. Identity linkage

Question:
Are the bidders directly or indirectly linked through core identity fields?

Typical signals:

- same legal representative
- same authorized representative
- same phone number
- same email
- same bank account
- same address
- same unified social credit code

Interpretation:

- strongest dimension for direct linkage
- should be weighted heavily
- low tolerance for false positives

### 2. Pricing linkage

Question:
Do the quoted prices suggest coordination rather than independent competition?

Typical signals:

- identical total bid amount
- extremely close total bid amount
- unusually similar itemized pricing structure
- same pricing rounding pattern
- same non-market pricing distribution across line items

Interpretation:

- important but not sufficient on its own
- should always be read together with identity, file origin, or textual signals

### 3. Text and solution linkage

Question:
Do the bids share unusual text or solution content suggesting shared drafting?

Typical signals:

- rare shared wording
- shared uncommon errors
- same custom narrative structures
- same technical solution sections
- same implementation or training content after template filtering

Interpretation:

- high false-positive risk without denoising
- must strongly downweight:
  - standard bidding templates
  - platform workflow descriptions
  - common service/training promises
  - normative response sections

### 4. Structural and document-origin linkage

Question:
Do the submission structures suggest common preparation or document reuse?

Typical signals:

- same chapter order
- same missing sections
- same file/component structure
- same file naming patterns
- same table layout style
- same editable document fingerprints

Interpretation:

- useful supporting dimension
- especially important in multi-file bid packages
- in long-PDF scenarios, chapter-level structure is more important than file-tree similarity

### 5. Authorization and qualification-chain linkage

Question:
Do the bidders rely on overlapping or suspicious authorization/qualification material?

Typical signals:

- same manufacturer authorization chain
- same registration certificate numbers
- same license numbers
- overlapping authorization dates
- same qualification material reused across bidders

Interpretation:

- medium-to-high value when stable identifiers are present
- requires careful source tracking

### 6. Time and electronic-trace linkage

Question:
Do the electronic traces suggest common preparation, same device, or coordinated submission timing?

Typical signals:

- same or clustered creation/modification times
- same CA certificate operator
- same upload terminal or IP
- same document fingerprints
- same page/image generation traits

Interpretation:

- very high value when trustworthy metadata exists
- often unavailable in current materials, so the system must tolerate partial absence

## Required fact families

The judgment layer implies the minimum fact families that `ReviewFacts` must carry.

### Supplier identity facts

- company name
- legal representative
- authorized representative
- phone
- email
- address
- bank account
- unified social credit code

### Pricing facts

- total bid amount
- itemized pricing rows
- pricing source section
- pricing source page

### Text and section facts

- chapter/section titles
- section family classification
- rare overlap snippets
- overlap source document and page
- shared-error snippets

### Structure facts

- section catalog
- section order
- component list
- file fingerprints

### Authorization and qualification facts

- manufacturer
- authorization issuer
- authorization date
- registration number
- license number

### Time and trace facts

- created/modified timestamps
- upload timing
- certificate/operator clues
- file hash or fingerprint

## Fact quality rules

The decision layer should consume facts using these rules:

1. Prefer stable identifiers over narrative similarity.
2. Prefer sourced facts over inferred facts.
3. Prefer primary values over candidate values.
4. Treat missing facts as `unknown`, not as `negative`.
5. Do not upgrade pair suspicion from text overlap alone unless the text is rare and non-normative.

## Dimension weighting guidance

This is not a fixed numeric scoring table, but it defines the intended priority.

- Highest priority:
  - identity linkage
  - time/electronic trace linkage
- High priority:
  - pricing linkage
  - authorization/qualification linkage
- Medium priority:
  - structural linkage
- Conditional priority:
  - text and solution linkage
    only after strong template and normative filtering

## Output contract for scoring

The scoring layer should produce, per supplier pair:

- `judgment`
  - `no_clear_signal`
  - `needs_follow_up`
  - `priority_review`
- `risk_level`
  - low / medium / high / critical
- `dimension_summary`
  a per-dimension summary of which dimensions contributed
- `findings`
  evidence-backed findings tied to specific dimensions

This makes scoring more than a flat score sum. It becomes a dimension-based judgment engine.

## Implications for ReviewFacts

`ReviewFacts` should not be a generic storage bucket. It should be a structured container for the fact families above, with:

- primary value
- candidate values
- source document
- source page
- source type
- confidence
- conflict markers when needed

If a fact family does not support one of the six judgment dimensions, it should not be promoted into the core fact layer.

## Implications for strategy

`strategy` should be driven by dimension gaps.

Examples:

- If pricing facts are weak, trigger quotation-table extraction or OCR for pricing pages.
- If identity facts are weak, target business-license/basic-profile/authorization sections.
- If text evidence is the only suspicious signal, avoid over-escalation and prefer low-cost follow-up checks.
- If strong identity or timing linkage already exists, escalate to deeper review and richer reporting.

So strategy should answer:

- which judgment dimensions are currently under-supported
- which capability can best fill that gap
- whether the expected value justifies OCR/LLM cost

## Implications for long-PDF support

For long-PDF bids, the decision model implies:

- chapter-aware facts are first-class
- quotation extraction must be section-aware
- technical/implementation/training comparison must be chapter-aware
- OCR should be a supplement for scanned pages, not the default entry path

## Non-goals

This model does not:

- make a final legal determination
- replace human review
- assume every suspicious signal is equally meaningful
- require every dimension to be present in every case

## Current conclusion

For the current repository, the next architectural rule should be:

**Business judgment dimensions define the fact model. The fact model defines strategy. Strategy defines capability execution.**
