from __future__ import annotations

from pathlib import Path

from agent_bid_rigging.core.fusion import (
    append_ocr_authorization_rows,
    append_ocr_entity_rows,
    append_ocr_license_rows,
    merge_ocr_into_signal,
    renumber_ocr_rows,
)
from agent_bid_rigging.core.extractor import extract_signals
from agent_bid_rigging.tests.test_core import load_document_from_text


def test_merge_ocr_into_signal_enriches_core_fields() -> None:
    signal = extract_signals(load_document_from_text("alpha", "bid", "投标总报价：100000"))
    rows = [
        {
            "supplier": "alpha",
            "fields": {
                "phone": "13800000000",
                "legal_representative": "张三",
                "address": "呼和浩特市新城区示例路1号",
                "bid_total_amount": "1888800.00",
            },
        }
    ]
    merge_ocr_into_signal(signal, rows)
    assert signal.phones == ["13800000000"]
    assert signal.legal_representatives == ["张三"]
    assert "呼和浩特市新城区示例路1号" in signal.addresses
    assert 1888800.0 in signal.bid_amounts


def test_append_ocr_rows_updates_artifact_tables() -> None:
    entity_rows: list[dict] = []
    authorization_rows = [
        {"supplier": "alpha", "manufacturer_mentions": [], "authorization_mentions": [], "summary": "未发现明确授权链线索"}
    ]
    license_rows = [
        {"supplier": "alpha", "license_lines": [], "registration_ids": []}
    ]
    ocr_rows = [
        {
            "supplier": "alpha",
            "source_path": "/tmp/a.pdf",
            "page_index": 1,
            "doc_type": "authorization_letter",
            "summary": "厂家授权书",
            "extracted_text": "授权厂家：测试厂家",
            "fields": {
                "company_name": "测试公司",
                "legal_representative": "张三",
                "address": "示例地址",
                "phone": "13800000000",
                "manufacturer": "测试厂家",
                "license_number": "LIC-001",
                "registration_number": "REG-001",
            },
        }
    ]
    append_ocr_entity_rows(entity_rows, ocr_rows)
    append_ocr_authorization_rows(authorization_rows, ocr_rows)
    append_ocr_license_rows(license_rows, ocr_rows)

    assert any(row["field_name"] == "phones" for row in entity_rows)
    assert authorization_rows[0]["manufacturer_mentions"] == ["测试厂家"]
    assert authorization_rows[0]["authorization_mentions"]
    assert "LIC-001" in license_rows[0]["registration_ids"]
    assert "REG-001" in license_rows[0]["registration_ids"]


def test_renumber_ocr_rows_assigns_global_ids() -> None:
    image_index_rows = [
        {"stored_path": str(Path("/tmp/1.jpg")), "page_index": 1, "supplier": "alpha", "image_index": 1},
        {"stored_path": str(Path("/tmp/2.jpg")), "page_index": 2, "supplier": "beta", "image_index": 1},
    ]
    image_ocr_rows = [
        {"stored_path": str(Path("/tmp/1.jpg")), "page_index": 1, "supplier": "alpha", "image_index": 1},
        {"stored_path": str(Path("/tmp/2.jpg")), "page_index": 2, "supplier": "beta", "image_index": 1},
    ]
    renumber_ocr_rows(image_index_rows, image_ocr_rows)
    assert image_index_rows[0]["image_id"] == "IMG001"
    assert image_index_rows[1]["image_id"] == "IMG002"
    assert image_ocr_rows[1]["image_index"] == 2
