from __future__ import annotations

import json
from pathlib import Path

from agent_bid_rigging.capabilities import CapabilityContext
from agent_bid_rigging.capabilities.pdf_sectioning.pipeline import PdfSectioningCapability, build_pdf_sectioning_response


def test_pdf_sectioning_detects_core_sections_in_long_bid_pdf(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[4]
    source_pdf = root / "test_target" / "wcb" / "pdf2" / "电子商城项目A响应文件-投标人 C.pdf"
    output_dir = tmp_path / "sectioning_run"

    capability = PdfSectioningCapability()
    result = capability.run(
        CapabilityContext(run_id="pdf_section_demo", source_path=str(source_pdf)),
        source_path=str(source_pdf),
        output_dir=str(output_dir),
        include_text=False,
    )

    payload = result.to_dict()["payload"]
    titles = [row["title"] for row in payload["sections"]]
    assert any("投标函" in title for title in titles)
    assert any("报价一览表" in title or "开标一览表" in title for title in titles)
    assert any("资格审查" in title for title in titles)
    assert any("技术方案" in title for title in titles)
    assert any("实施方案" in title for title in titles)
    assert any("培训方案" in title for title in titles)
    assert (output_dir / "section_catalog.json").exists()
    assert (output_dir / "sectioning_result.json").exists()
    assert (output_dir / "sectioning_result.md").exists()
    section_catalog = json.loads((output_dir / "section_catalog.json").read_text(encoding="utf-8"))
    assert section_catalog["rows"][0]["start_page"] >= 1


def test_pdf_sectioning_uses_toc_when_available() -> None:
    root = Path(__file__).resolve().parents[4]
    source_pdf = root / "test_target" / "wcb" / "pdf2" / "电子商城项目 A响应文件-投标人 A.pdf"

    response = build_pdf_sectioning_response(source_pdf, output_dir=source_pdf.parent, include_text=False)

    assert response.toc_pages
    assert response.section_count >= 6
    assert any(section.family == "qualification" for section in response.sections)
    assert any(section.family == "technical_plan" for section in response.sections)
