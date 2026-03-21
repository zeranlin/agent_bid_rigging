from __future__ import annotations

from pathlib import Path

from agent_bid_rigging.capabilities import CapabilityContext
from agent_bid_rigging.capabilities.pdf_sectioning.pipeline import build_pdf_sectioning_response
from agent_bid_rigging.capabilities.pdf_tables.pipeline import PdfTablesCapability
from agent_bid_rigging.core.artifacts import build_section_similarity_table
from agent_bid_rigging.core.fusion import build_review_facts
from agent_bid_rigging.core.extractor import build_tender_baseline, extract_signals
from agent_bid_rigging.utils.file_loader import load_document


def test_pdf_tables_extract_bid_total_amount_from_long_pdf(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[4]
    source_pdf = root / "test_target" / "wcb" / "pdf2" / "电子商城项目A响应文件-投标人 C.pdf"
    section_response = build_pdf_sectioning_response(source_pdf, output_dir=tmp_path / "sectioning", include_text=True)

    capability = PdfTablesCapability()
    result = capability.run(
        CapabilityContext(source_path=str(source_pdf)),
        source_path=str(source_pdf),
        output_dir=str(tmp_path / "tables"),
        section_payload=section_response.to_dict(include_text=True),
    )

    rows = result.payload["rows"]
    assert any(row["field_name"] == "bid_total_amount" for row in rows)
    amount_row = next(row for row in rows if row["field_name"] == "bid_total_amount")
    assert amount_row["value"] == "350000.00"


def test_section_similarity_table_uses_long_pdf_sections(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[4]
    tender_path = root / "test_target" / "wcb" / "pdf2" / "电子商城建设项目 A-投标.pdf"
    bid_a = root / "test_target" / "wcb" / "pdf2" / "电子商城项目 A响应文件-投标人 A.pdf"
    bid_b = root / "test_target" / "wcb" / "pdf2" / "电子商城项目 A响应文件-投标人 B.pdf"

    tender_doc = load_document("tender", "tender", str(tender_path))
    tender_lines = build_tender_baseline(tender_doc)
    signal_a = extract_signals(load_document("投标人 A", "bid", str(bid_a)), tender_lines=tender_lines)
    signal_b = extract_signals(load_document("投标人 B", "bid", str(bid_b)), tender_lines=tender_lines)

    section_rows = []
    for supplier, path in (("投标人 A", bid_a), ("投标人 B", bid_b)):
        response = build_pdf_sectioning_response(path, output_dir=tmp_path / supplier, include_text=True)
        for section in response.sections:
            section_rows.append(
                {
                    "role": "bid",
                    "supplier": supplier,
                    "source_path": str(path),
                    **section.to_dict(include_text=True),
                }
            )

    review_facts = build_review_facts(
        tender_doc,
        [signal_a, signal_b],
        [],
        [],
        section_rows,
        [],
    )
    rows = build_section_similarity_table(review_facts)

    families = {row["section_family"] for row in rows}
    assert "technical_plan" in families
    assert "implementation_plan" in families or "training_plan" in families
