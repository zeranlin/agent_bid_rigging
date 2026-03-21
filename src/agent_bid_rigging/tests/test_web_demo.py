from __future__ import annotations

import io
import json
from pathlib import Path

from agent_bid_rigging.web.app import _derive_supplier_name, create_app


def test_web_index_loads(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    client = app.test_client()

    response = client.get("/")

    assert response.status_code == 200
    assert "围串标审查演示台" in response.get_data(as_text=True)


def test_web_create_run_starts_review(monkeypatch, tmp_path: Path) -> None:
    app = create_app(tmp_path)
    client = app.test_client()

    def fake_execute_run(run_id: str, tender_path: str, bids: dict[str, str], run_dir: Path, opinion_mode: str) -> None:
        (run_dir / "summary.md").write_text("# summary", encoding="utf-8")
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
            "opinion_mode": "template",
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


def test_supplier_name_derivation() -> None:
    assert _derive_supplier_name("投标文件-01-恒禾.zip", 1) == "恒禾"
    assert _derive_supplier_name("bid_beta.docx", 2) == "bid_beta"
