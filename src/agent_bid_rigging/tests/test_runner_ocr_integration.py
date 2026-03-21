from __future__ import annotations

import json
from pathlib import Path

from agent_bid_rigging.core.runner import run_review


class StubOcrCapability:
    def run(self, context, **kwargs):  # noqa: ANN001, D401
        supplier = context.metadata.get("supplier")
        role = context.metadata.get("role")
        image_payload = {
            "source_path": kwargs["source_path"],
            "output_dir": kwargs["output_dir"],
            "source_count": 1,
            "sources": [kwargs["source_path"]],
            "image_count": 1,
            "images": [
                {
                    "source_path": kwargs["source_path"],
                    "page_index": 1,
                    "image_index": 1,
                    "image_name": "page_001_img_01.jpg",
                    "stored_path": str(Path(kwargs["output_dir"]) / "images" / "page_001_img_01.jpg"),
                    "media_type": "image/jpeg",
                    "width": 100,
                    "height": 200,
                }
            ],
            "image_results": [
                {
                    "image": {
                        "source_path": kwargs["source_path"],
                        "page_index": 1,
                        "image_index": 1,
                        "image_name": "page_001_img_01.jpg",
                        "stored_path": str(Path(kwargs["output_dir"]) / "images" / "page_001_img_01.jpg"),
                        "media_type": "image/jpeg",
                        "width": 100,
                        "height": 200,
                    },
                    "doc_type": "business_license" if role == "bid" else "unknown",
                    "summary": "营业执照图片" if role == "bid" else "招标图片",
                    "extracted_text": "法定代表人：张三\n地址：呼和浩特市新城区示例路1号\n联系电话：13800000000",
                    "fields": (
                        {
                            "company_name": supplier or "",
                            "legal_representative": "张三",
                            "bid_total_amount": "1888800.00" if supplier == "alpha" else "",
                            "license_number": "LIC-001",
                            "registration_number": "REG-001",
                            "manufacturer": "测试厂家",
                            "brand": "",
                            "model": "",
                            "address": "呼和浩特市新城区示例路1号",
                            "phone": "13800000000",
                        }
                        if role == "bid"
                        else {}
                    ),
                    "confidence": 0.95,
                }
            ],
        }

        class Result:
            payload = image_payload

        return Result()


def test_run_review_with_ocr_writes_tables_and_merges_fields(tmp_path: Path, monkeypatch) -> None:
    tender = tmp_path / "tender.txt"
    alpha = tmp_path / "alpha.txt"
    beta = tmp_path / "beta.txt"
    tender.write_text("项目名称：设备采购\n通用条款：投标人独立编制。", encoding="utf-8")
    alpha.write_text("联系人邮箱：alpha@example.com\n投标总报价：100000", encoding="utf-8")
    beta.write_text("联系人邮箱：beta@example.com\n投标总报价：130000", encoding="utf-8")

    monkeypatch.setattr("agent_bid_rigging.core.runner.OcrCapability", StubOcrCapability)

    out_dir = tmp_path / "review"
    report = run_review(
        str(tender),
        {"alpha": str(alpha), "beta": str(beta)},
        output_dir=str(out_dir),
        opinion_mode="template",
        enable_ocr=True,
    )

    assert report["image_index"]
    assert report["image_ocr_table"]
    assert report["review_facts"]["suppliers"]
    assert report["review_strategy"]["enable_ocr"] is True
    assert (out_dir / "image_index.json").exists()
    assert (out_dir / "image_ocr_table.json").exists()
    assert (out_dir / "review_facts.json").exists()
    assert (out_dir / "review_strategy.json").exists()

    entity_table = json.loads((out_dir / "entity_field_table.json").read_text(encoding="utf-8"))["rows"]
    phone_rows = [row for row in entity_table if row["supplier"] == "alpha" and row["field_name"] == "phones"]
    assert phone_rows
    assert "13800000000" in phone_rows[0]["values"]

    price_table = json.loads((out_dir / "price_analysis_table.json").read_text(encoding="utf-8"))["rows"]
    alpha_row = next(row for row in price_table if row["supplier"] == "alpha")
    assert alpha_row["bid_amount"] == "1888800.00"

    license_table = json.loads((out_dir / "license_match_table.json").read_text(encoding="utf-8"))["rows"]
    assert "LIC-001" in next(row for row in license_table if row["supplier"] == "alpha")["registration_ids"]

    review_facts = json.loads((out_dir / "review_facts.json").read_text(encoding="utf-8"))
    alpha_supplier = next(item for item in review_facts["suppliers"] if item["supplier"] == "alpha")
    assert alpha_supplier["phones"][0]["value"] == "13800000000"
