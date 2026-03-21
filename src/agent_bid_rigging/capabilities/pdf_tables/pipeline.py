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
    prioritized_candidates = _extract_prioritized_amounts(lines, text)
    if not prioritized_candidates:
        return None
    chosen = prioritized_candidates[0]
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


def _extract_prioritized_amounts(lines: list[str], text: str) -> list[str]:
    compact = re.sub(r"\s+", "", text)

    high_priority_patterns = (
        r"(?:合计|总报价|投标总价|报价总计|项目报价(?:（人民币元）)?)[:：]?[¥￥]?\s*([0-9][0-9,]*(?:\.\d+)?)",
        r"总报价.*?[¥￥]\s*([0-9][0-9,]*(?:\.\d+)?)",
        r"合计[:：]?[¥￥]?\s*([0-9][0-9,]*(?:\.\d+)?)",
        r"项目报价.*?合计[:：]?[¥￥]?\s*([0-9][0-9,]*(?:\.\d+)?)",
    )
    medium_priority_patterns = (
        r"(?:报价金额|报价|小写)[:：]?[¥￥]?\s*([0-9][0-9,]*(?:\.\d+)?)",
        r"[¥￥]\s*([0-9][0-9,]*(?:\.\d+)?)",
        r"(?:人民币|金额)\s*([0-9][0-9,]*(?:\.\d+)?)\s*元",
    )

    for patterns in (high_priority_patterns, medium_priority_patterns):
        candidates: list[str] = []
        for line in lines[:80]:
            for pattern in patterns:
                for match in re.findall(pattern, line):
                    amount = _normalize_amount(match)
                    if amount:
                        candidates.append(amount)
        for pattern in patterns:
            for match in re.findall(pattern, compact):
                amount = _normalize_amount(match)
                if amount:
                    candidates.append(amount)
        if candidates:
            deduped = []
            seen = set()
            for value in candidates:
                if value not in seen:
                    deduped.append(value)
                    seen.add(value)
            return sorted(deduped, key=lambda item: float(item), reverse=True)
    return []
