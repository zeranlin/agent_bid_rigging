from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


def _resolve_cli(name: str) -> list[str]:
    force = os.environ.get("CLI_ANYTHING_FORCE_INSTALLED", "").strip() == "1"
    path = shutil.which(name)
    if path:
        return [path]
    if force:
        raise RuntimeError(f"{name} not found in PATH. Install with: pip install -e .")
    return [sys.executable, "-m", "agent_bid_rigging.cli"]


class TestCLIEndToEnd:
    CLI_BASE = _resolve_cli("agent-bid-rigging")

    def _run(self, args: list[str], check: bool = True):
        return subprocess.run(
            self.CLI_BASE + args,
            capture_output=True,
            text=True,
            check=check,
        )

    def test_help(self) -> None:
        result = self._run(["analyze", "--help"])
        assert result.returncode == 0
        assert "--tender" in result.stdout

    def test_analyze_generates_artifacts(self, tmp_path: Path) -> None:
        root = Path(__file__).resolve().parents[3]
        out_dir = tmp_path / "run_artifacts"
        result = self._run(
            [
                "analyze",
                "--json-output",
                "--tender",
                str(root / "examples" / "tender.txt"),
                "--bid",
                f"alpha={root / 'examples' / 'bid_alpha.txt'}",
                "--bid",
                f"beta={root / 'examples' / 'bid_beta.txt'}",
                "--bid",
                f"gamma={root / 'examples' / 'bid_gamma.txt'}",
                "--output-dir",
                str(out_dir),
            ]
        )
        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert payload["pairwise_assessments"]
        assert (out_dir / "manifest.json").exists()
        assert (out_dir / "case_manifest.json").exists()
        assert (out_dir / "source_file_index.json").exists()
        assert (out_dir / "extracted_file_index.json").exists()
        assert (out_dir / "document_catalog.json").exists()
        assert (out_dir / "entity_field_table.json").exists()
        assert (out_dir / "price_analysis_table.json").exists()
        assert (out_dir / "structure_similarity_table.json").exists()
        assert (out_dir / "file_fingerprint_table.json").exists()
        assert (out_dir / "duplicate_detection_table.json").exists()
        assert (out_dir / "text_similarity_table.json").exists()
        assert (out_dir / "shared_error_table.json").exists()
        assert (out_dir / "authorization_chain_table.json").exists()
        assert (out_dir / "license_match_table.json").exists()
        assert (out_dir / "timeline_table.json").exists()
        assert (out_dir / "evidence_grade_table.json").exists()
        assert (out_dir / "risk_score_table.json").exists()
        assert (out_dir / "review_conclusion_table.json").exists()
        assert (out_dir / "formal_report.json").exists()
        assert (out_dir / "formal_report.md").exists()
        assert (out_dir / "pairwise_report.json").exists()
        assert (out_dir / "summary.md").exists()
        assert (out_dir / "opinion.json").exists()
        assert (out_dir / "opinion.md").exists()
        source_index = json.loads((out_dir / "source_file_index.json").read_text(encoding="utf-8"))
        assert len(source_index["rows"]) == 4
        entity_table = json.loads((out_dir / "entity_field_table.json").read_text(encoding="utf-8"))
        assert any(row["field_name"] == "bid_amounts" for row in entity_table["rows"])
        structure_table = json.loads((out_dir / "structure_similarity_table.json").read_text(encoding="utf-8"))
        assert len(structure_table["rows"]) == 3
        risk_table = json.loads((out_dir / "risk_score_table.json").read_text(encoding="utf-8"))
        assert risk_table["rows"]
        formal_report = (out_dir / "formal_report.md").read_text(encoding="utf-8")
        assert "围串标审查意见书" in formal_report
        assert "审查情况" in formal_report
        assert "初步审查结论" in formal_report

    def test_analyze_accepts_zip_archives(self, tmp_path: Path) -> None:
        tender_dir = tmp_path / "tender_dir"
        alpha_dir = tmp_path / "alpha_dir"
        beta_dir = tmp_path / "beta_dir"
        tender_dir.mkdir()
        alpha_dir.mkdir()
        beta_dir.mkdir()

        (tender_dir / "tender.txt").write_text("项目名称：设备采购\n通用条款：投标人独立编制。", encoding="utf-8")
        (alpha_dir / "a.txt").write_text(
            "联系人电话：13800000000\n投标总报价：100000\n特别承诺：备用机18小时到场",
            encoding="utf-8",
        )
        (beta_dir / "b.txt").write_text(
            "联系人电话：13900000000\n投标总报价：130000\n特别承诺：备用机18小时到场",
            encoding="utf-8",
        )

        tender_zip = tmp_path / "tender.zip"
        alpha_zip = tmp_path / "alpha.zip"
        beta_zip = tmp_path / "beta.zip"
        for archive_path, source_dir in (
            (tender_zip, tender_dir),
            (alpha_zip, alpha_dir),
            (beta_zip, beta_dir),
        ):
            with zipfile.ZipFile(archive_path, "w") as archive:
                for path in source_dir.iterdir():
                    archive.write(path, arcname=path.name)

        out_dir = tmp_path / "zip_run_artifacts"
        result = self._run(
            [
                "analyze",
                "--json",
                "--tender",
                str(tender_zip),
                "--bid",
                f"alpha={alpha_zip}",
                "--bid",
                f"beta={beta_zip}",
                "--output-dir",
                str(out_dir),
                "--opinion-mode",
                "template",
            ]
        )
        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert payload["pairwise_assessments"][0]["supplier_a"] == "alpha"
        assert (out_dir / "summary.md").exists()
        assert (out_dir / "case_manifest.json").exists()
        assert (out_dir / "text_similarity_table.json").exists()
        assert (out_dir / "formal_report.md").exists()
