from __future__ import annotations

import io
import json
from pathlib import Path

from agent_bid_rigging.web.app import _derive_supplier_name, _safe_upload_filename, _unique_upload_path, create_app


def test_web_index_loads(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    client = app.test_client()

    response = client.get("/")

    assert response.status_code == 200
    assert "围串标审查演示台" in response.get_data(as_text=True)


def test_web_create_run_starts_review(monkeypatch, tmp_path: Path) -> None:
    app = create_app(tmp_path)
    client = app.test_client()

    def fake_execute_run(
        run_id: str,
        tender_path: str,
        bids: dict[str, str],
        run_dir: Path,
        opinion_mode: str,
        enable_ocr: bool,
        review_mode: str,
    ) -> None:
        (run_dir / "formal_report.md").write_text("# report", encoding="utf-8")
        (run_dir / "opinion.md").write_text("# opinion", encoding="utf-8")
        (run_dir / "llm_status.json").write_text(
            json.dumps(
                {
                    "requested_mode": opinion_mode,
                    "state": "completed",
                    "generated_at": "2026-03-21T10:00:00",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (run_dir / "web_job.json").write_text(
            json.dumps({"run_id": run_id, "state": "completed"}, ensure_ascii=False),
            encoding="utf-8",
        )

    monkeypatch.setattr("agent_bid_rigging.web.app._execute_run", fake_execute_run)

    class ImmediateThread:
        def __init__(self, target=None, kwargs=None, daemon=None):
            self.target = target
            self.kwargs = kwargs or {}

        def start(self) -> None:
            assert self.target is not None
            self.target(**self.kwargs)

    monkeypatch.setattr("agent_bid_rigging.web.app.threading.Thread", ImmediateThread)

    response = client.post(
        "/runs",
        data={
            "label": "demo_case",
            "review_mode": "rule",
            "bid_names": "恒禾\n华康",
            "tender_file": (io.BytesIO(b"tender body"), "招标文件.zip"),
            "bid_files": [
                (io.BytesIO(b"bid a"), "投标文件-恒禾.zip"),
                (io.BytesIO(b"bid b"), "投标文件-华康.zip"),
            ],
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/runs/demo_case")
    run_dir = tmp_path / "runs" / "demo_case"
    assert (run_dir / "formal_report.md").exists()
    status_response = client.get("/api/runs/demo_case")
    payload = status_response.get_json()
    assert payload["llm_status"]["state"] == "completed"
    assert "主报告" in payload["available_reports"]
    assert payload["review_mode"] == "rule"


def test_run_detail_can_switch_report_variants(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    client = app.test_client()
    run_dir = tmp_path / "runs" / "demo_case"
    run_dir.mkdir(parents=True)
    (run_dir / "web_job.json").write_text(
        json.dumps(
            {
                "run_id": "demo_case",
                "state": "completed",
                "review_mode": "llm_ocr",
                "opinion_mode": "llm",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "llm_status.json").write_text(
        json.dumps({"requested_mode": "llm", "state": "completed"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (run_dir / "formal_report.md").write_text("main report", encoding="utf-8")
    (run_dir / "formal_report.rule.md").write_text("rule report", encoding="utf-8")
    (run_dir / "formal_report.llm.md").write_text("llm report", encoding="utf-8")
    (run_dir / "risk_score_table.json").write_text(
        json.dumps(
            [
                {
                    "supplier_a": "恒禾",
                    "supplier_b": "华康",
                    "dimension_summary": {
                        "identity_link": {"matched": True, "tier": "strong"},
                        "pricing_link": {"matched": True, "tier": "medium"},
                        "text_similarity": {"matched": False, "tier": "none"},
                        "file_homology": {"matched": False, "tier": "none"},
                        "authorization_chain": {"matched": False, "tier": "none"},
                        "timeline_trace": {"matched": False, "tier": "none"},
                    },
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    response = client.get("/runs/demo_case?report=rule")

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert ">rule report</p>" in body or "<p>rule report</p>" in body
    assert "大模型版报告" in body
    assert "维度摘要概览" in body
    assert "dimension-chip strong" in body
    assert "dimension-chip medium" in body
    assert "主体关联强" in body
    assert "报价关联中" in body
    assert "文本与方案关联未命中" not in body
    assert "导出当前报告" in body


def test_artifact_download_supports_export(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    client = app.test_client()
    run_dir = tmp_path / "runs" / "demo_case"
    run_dir.mkdir(parents=True)
    report_path = run_dir / "formal_report.md"
    report_path.write_text("# report", encoding="utf-8")

    response = client.get("/runs/demo_case/artifacts/formal_report.md?download=1")

    assert response.status_code == 200
    assert "attachment" in response.headers.get("Content-Disposition", "")


def test_supplier_name_derivation() -> None:
    assert _derive_supplier_name("投标文件-01-恒禾.zip", 1) == "恒禾"
    assert _derive_supplier_name("bid_beta.docx", 2) == "bid_beta"


def test_safe_upload_filename_preserves_readable_chinese_names() -> None:
    assert _safe_upload_filename("投标文件-01-恒禾.zip") == "投标文件-01-恒禾.zip"
    assert _safe_upload_filename("../../招标 文件 01.zip") == "招标_文件_01.zip"


def test_unique_upload_path_avoids_overwriting_similar_names(tmp_path: Path) -> None:
    first = _unique_upload_path(tmp_path, "投标文件-01-恒禾.zip")
    first.write_text("a", encoding="utf-8")
    second = _unique_upload_path(tmp_path, "投标文件-01-恒禾.zip")

    assert first.name == "投标文件-01-恒禾.zip"
    assert second.name == "投标文件-01-恒禾_2.zip"
