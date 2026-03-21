from __future__ import annotations

from agent_bid_rigging.core.llm_review import _build_evidence_input


def test_build_evidence_input_mentions_review_facts_summary() -> None:
    report = {
        "run_name": "demo",
        "suppliers": ["alpha"],
        "formal_report": {
            "project_basic_info": {
                "project_name": "测试项目",
            }
        },
        "risk_score_table": [
            {
                "supplier_a": "alpha",
                "supplier_b": "beta",
                "total_score": 30,
                "risk_level": "medium",
                "technical_text_score": 30,
                "entity_link_score": 0,
                "pricing_score": 0,
                "file_homology_score": 0,
            }
        ],
        "evidence_grade_table": [],
        "review_facts": {
            "suppliers": [
                {
                    "supplier": "alpha",
                    "company_names": [{"value": "阿尔法公司", "is_primary": True}],
                    "bid_amounts": [{"value": "1888800.00", "is_primary": True}],
                    "legal_representatives": [{"value": "张三", "is_primary": True}],
                    "phones": [{"value": "13800000000", "is_primary": True}],
                    "addresses": [{"value": "呼和浩特市新城区示例路1号", "is_primary": True}],
                    "license_numbers": [{"value": "LIC-001", "is_primary": True}],
                    "registration_numbers": [{"value": "REG-001", "is_primary": True}],
                }
            ]
        },
    }

    prompt = _build_evidence_input(report)

    assert "统一事实层摘要" in prompt
    assert "阿尔法公司" in prompt
    assert "1888800.00" in prompt
    assert "LIC-001" in prompt
