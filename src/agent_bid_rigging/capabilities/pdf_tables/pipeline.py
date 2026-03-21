from __future__ import annotations

import json
import re
from pathlib import Path

from agent_bid_rigging.capabilities.base import CapabilityContext, CapabilityResult, ReviewCapability
from agent_bid_rigging.capabilities.pdf_sectioning.pipeline import build_pdf_sectioning_response
from agent_bid_rigging.capabilities.pdf_sectioning.schemas import PdfSection
from agent_bid_rigging.capabilities.pdf_tables.schemas import PdfTableResponse, PdfTableRow


class PdfTablesCapability(ReviewCapability):
    name = "pdf_tables"

    def run(self, context: CapabilityContext, **kwargs: object) -> CapabilityResult:
        source_path = kwargs.get("source_path") or context.source_path
        if not source_path:
            raise ValueError("source_path is required for PDF table extraction capability")

        source = Path(str(source_path)).expanduser().resolve()
        if source.suffix.lower() != ".pdf":
            raise ValueError("PDF table extraction currently supports only .pdf inputs")

        output_dir = Path(str(kwargs.get("output_dir") or source.parent / f"{source.stem}_tables")).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        section_payload = kwargs.get("section_payload")
        if isinstance(section_payload, dict) and section_payload.get("sections"):
            sections = [PdfSection(**section) for section in section_payload["sections"]]
        else:
            section_response = build_pdf_sectioning_response(source, output_dir=output_dir, include_text=True)
            sections = section_response.sections

        response = build_pdf_table_response(source, output_dir=output_dir, sections=sections)
        payload = response.to_dict()
        (output_dir / "table_extract_rows.json").write_text(json.dumps({"rows": payload["rows"]}, ensure_ascii=False, indent=2), encoding="utf-8")
        (output_dir / "table_result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return CapabilityResult(
            capability=self.name,
            backend="section-text",
            status="completed",
            payload=payload,
            evidence=[f"{row.table_type}:{row.field_name}={row.value}" for row in response.rows],
            warnings=response.warnings,
        )


def build_pdf_table_response(source: Path, *, output_dir: Path, sections: list[PdfSection]) -> PdfTableResponse:
    rows: list[PdfTableRow] = []
    warnings: list[str] = []
    for section in sections:
        if section.family != "quotation":
            continue
        row = _extract_bid_total_amount(section)
        if row:
            rows.append(row)
    if not rows:
        warnings.append("No quotation/opening table values were extracted from section text.")
    return PdfTableResponse(
        source_path=str(source),
        output_dir=str(output_dir),
        row_count=len(rows),
        rows=rows,
        warnings=warnings,
    )


def _extract_bid_total_amount(section: PdfSection) -> PdfTableRow | None:
    text = section.text
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    patterns = [
        r"(?:小写|投标总价|报价金额|报价)\s*[：:]\s*([0-9][0-9,]*(?:\.\d+)?)",
        r"(?:人民币|金额)\s*([0-9][0-9,]*(?:\.\d+)?)\s*元",
    ]
    candidates: list[str] = []
    for line in lines[:60]:
        for pattern in patterns:
            for match in re.findall(pattern, line):
                amount = _normalize_amount(match)
                if amount:
                    candidates.append(amount)
    if not candidates:
        compact = text.replace(" ", "")
        for pattern in patterns:
            for match in re.findall(pattern, compact):
                amount = _normalize_amount(match)
                if amount:
                    candidates.append(amount)
    if not candidates:
        return None
    chosen = max(candidates, key=lambda item: float(item))
    return PdfTableRow(
        table_type="quotation",
        field_name="bid_total_amount",
        value=chosen,
        source_section=section.title,
        source_page=section.start_page,
        confidence=0.9,
        snippet=section.snippet[:180],
    )


def _normalize_amount(value: str) -> str | None:
    try:
        amount = float(value.replace(",", ""))
    except ValueError:
        return None
    if amount < 1:
        return None
    return f"{amount:.2f}"
