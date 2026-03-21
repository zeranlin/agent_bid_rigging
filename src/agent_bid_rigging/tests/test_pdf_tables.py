from __future__ import annotations

from pathlib import Path

from agent_bid_rigging.capabilities import CapabilityContext
from agent_bid_rigging.capabilities.pdf_sectioning.pipeline import build_pdf_sectioning_response
from agent_bid_rigging.capabilities.pdf_tables.pipeline import PdfTablesCapability, build_pdf_table_response
from agent_bid_rigging.core.artifacts import _primary_value
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


def test_pdf_tables_extract_bid_total_amount_from_bidder_a_quote_sheet(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[4]
    source_pdf = root / "test_target" / "wcb" / "pdf2" / "电子商城项目 A响应文件-投标人 A.pdf"
    section_response = build_pdf_sectioning_response(source_pdf, output_dir=tmp_path / "sectioning_a", include_text=True)

    table_response = build_pdf_table_response(source_pdf, output_dir=tmp_path / "tables_a", sections=section_response.sections)

    amount_row = next(row for row in table_response.rows if row.field_name == "bid_total_amount")
    assert amount_row.value == "1.00"
    assert amount_row.source_section in {"5.2. 报价单", "报价单"}
    pricing_rows = [row for row in table_response.rows if row.field_name == "pricing_row"]
    assert any("系统实施报价=1.00" == row.value for row in pricing_rows)


def test_pdf_tables_prefer_total_amount_over_item_amounts_for_bidder_b(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[4]
    source_pdf = root / "test_target" / "wcb" / "pdf2" / "电子商城项目 A响应文件-投标人 B.pdf"
    section_response = build_pdf_sectioning_response(source_pdf, output_dir=tmp_path / "sectioning_b", include_text=True)

    table_response = build_pdf_table_response(source_pdf, output_dir=tmp_path / "tables_b", sections=section_response.sections)

    amount_row = next(row for row in table_response.rows if row.field_name == "bid_total_amount")
    assert amount_row.value == "2000000.00"
    pricing_rows = [row for row in table_response.rows if row.field_name == "pricing_row"]
    assert any(row.value.startswith("成品软件=") for row in pricing_rows)


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


def test_review_facts_extract_long_pdf_profile_fields(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[4]
    tender_path = root / "test_target" / "wcb" / "pdf2" / "电子商城建设项目 A-投标.pdf"
    bid_a = root / "test_target" / "wcb" / "pdf2" / "电子商城项目 A响应文件-投标人 A.pdf"
    bid_b = root / "test_target" / "wcb" / "pdf2" / "电子商城项目 A响应文件-投标人 B.pdf"
    bid_c = root / "test_target" / "wcb" / "pdf2" / "电子商城项目A响应文件-投标人 C.pdf"

    tender_doc = load_document("tender", "tender", str(tender_path))
    tender_lines = build_tender_baseline(tender_doc)
    signals = [
        extract_signals(load_document("A", "bid", str(bid_a)), tender_lines=tender_lines),
        extract_signals(load_document("B", "bid", str(bid_b)), tender_lines=tender_lines),
        extract_signals(load_document("C", "bid", str(bid_c)), tender_lines=tender_lines),
    ]

    section_rows = []
    table_rows = []
    for supplier, path in (("A", bid_a), ("B", bid_b), ("C", bid_c)):
        section_response = build_pdf_sectioning_response(path, output_dir=tmp_path / f"sections_{supplier}", include_text=True)
        for section in section_response.sections:
            section_rows.append({"role": "bid", "supplier": supplier, "source_path": str(path), **section.to_dict(include_text=True)})
        table_response = build_pdf_table_response(path, output_dir=tmp_path / f"tables_{supplier}", sections=section_response.sections)
        for row in table_response.rows:
            table_rows.append({"role": "bid", "supplier": supplier, "source_path": str(path), **row.to_dict()})

    review_facts = build_review_facts(tender_doc, signals, [], [], section_rows, table_rows)
    supplier_map = {supplier.supplier: supplier for supplier in review_facts.suppliers}

    assert _primary_value(supplier_map["A"], "company_names") == "投标人 A"
    assert _primary_value(supplier_map["A"], "legal_representatives") == "郑新刚"
    assert _primary_value(supplier_map["A"], "phones") == "*******8093"
    assert "长乐区" in (_primary_value(supplier_map["A"], "addresses") or "")
    assert _primary_value(supplier_map["A"], "bid_amounts") == "1.00"
    assert any(row["value"].startswith("系统实施报价=") for row in supplier_map["A"].pricing_rows)

    assert _primary_value(supplier_map["B"], "company_names") == "投标人 B"
    assert _primary_value(supplier_map["B"], "legal_representatives") == "王淑云"
    assert _primary_value(supplier_map["B"], "bid_amounts") == "2000000.00"
    assert any(row["value"].startswith("成品软件=") for row in supplier_map["B"].pricing_rows)

    assert _primary_value(supplier_map["C"], "company_names") == "投标人 C"
    assert _primary_value(supplier_map["C"], "phones") == "*******6767"
    assert "中关村东路" in (_primary_value(supplier_map["C"], "addresses") or "")
