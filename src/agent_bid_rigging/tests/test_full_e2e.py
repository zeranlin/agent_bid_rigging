from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
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
        assert (out_dir / "pairwise_report.json").exists()
        assert (out_dir / "summary.md").exists()
        assert (out_dir / "opinion.json").exists()
        assert (out_dir / "opinion.md").exists()
