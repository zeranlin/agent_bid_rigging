from __future__ import annotations

import json
import re
import threading
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Flask, abort, jsonify, redirect, render_template_string, request, send_file, url_for
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from agent_bid_rigging.core.runner import run_review

INDEX_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>agent_bid_rigging 演示台</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4efe6;
      --panel: #fffdfa;
      --ink: #1f2a33;
      --muted: #68727d;
      --line: #d9cdbd;
      --accent: #7c3f00;
      --accent-soft: #f0dcc8;
      --ok: #256d1b;
      --warn: #8f5d00;
      --bad: #9a1f1f;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Noto Serif SC", "Songti SC", "STSong", serif;
      background:
        radial-gradient(circle at top left, #fff7ef 0, #f4efe6 45%, #efe5d8 100%);
      color: var(--ink);
    }
    main {
      width: min(1120px, calc(100vw - 48px));
      margin: 28px auto 40px;
    }
    .hero, .panel {
      background: color-mix(in srgb, var(--panel) 92%, white);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 24px;
      box-shadow: 0 18px 40px rgba(72, 47, 22, 0.08);
    }
    .hero {
      display: grid;
      gap: 12px;
      margin-bottom: 20px;
    }
    h1, h2, h3 { margin: 0; font-weight: 700; }
    h1 { font-size: 30px; }
    h2 { font-size: 20px; margin-bottom: 16px; }
    p, li, label, input, select, button, textarea { font-size: 15px; line-height: 1.6; }
    .muted { color: var(--muted); }
    .grid {
      display: grid;
      grid-template-columns: 1.2fr 1fr;
      gap: 20px;
      align-items: start;
    }
    form { display: grid; gap: 14px; }
    .field { display: grid; gap: 8px; }
    input[type="text"], select, textarea, input[type="file"] {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 10px 12px;
      background: white;
      color: var(--ink);
    }
    textarea { min-height: 88px; resize: vertical; }
    .row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    button, .button {
      appearance: none;
      border: 0;
      border-radius: 999px;
      padding: 11px 16px;
      background: var(--accent);
      color: white;
      text-decoration: none;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-weight: 600;
    }
    .button.secondary {
      background: transparent;
      color: var(--accent);
      border: 1px solid var(--line);
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }
    th, td {
      text-align: left;
      border-bottom: 1px solid var(--line);
      padding: 10px 8px;
      vertical-align: top;
    }
    .badge {
      display: inline-flex;
      padding: 4px 10px;
      border-radius: 999px;
      font-size: 12px;
      background: var(--accent-soft);
      color: var(--accent);
      font-weight: 700;
    }
    .state-completed { color: var(--ok); }
    .state-running, .state-queued { color: var(--warn); }
    .state-failed { color: var(--bad); }
    .hint { padding: 12px 14px; border-radius: 12px; background: #f8f2ea; border: 1px dashed var(--line); }
    @media (max-width: 900px) {
      main { width: min(100vw - 24px, 1120px); }
      .grid, .row { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <span class="badge">最小演示版</span>
      <h1>agent_bid_rigging 围串标审查演示台</h1>
      <p class="muted">上传 1 份招标文件和多家投标文件，系统会调用现有审查链路完成抽取、比对、打分，并生成规则版与 LLM 版报告。</p>
    </section>
    <section class="grid">
      <section class="panel">
        <h2>新建案件</h2>
        <form action="{{ url_for('create_run') }}" method="post" enctype="multipart/form-data">
          <div class="field">
            <label for="label">案件标识</label>
            <input id="label" type="text" name="label" placeholder="例如：wcb_demo_release">
          </div>
          <div class="row">
            <div class="field">
              <label for="opinion_mode">报告模式</label>
              <select id="opinion_mode" name="opinion_mode">
                <option value="template">template</option>
                <option value="llm">llm</option>
                <option value="auto" selected>auto</option>
              </select>
            </div>
            <div class="field">
              <label for="bid_names">供应商名称（可选）</label>
              <textarea id="bid_names" name="bid_names" placeholder="每行 1 个名称，顺序与投标文件一致"></textarea>
            </div>
          </div>
          <div class="field">
            <label for="tender_file">招标文件</label>
            <input id="tender_file" type="file" name="tender_file" required>
          </div>
          <div class="field">
            <label for="bid_files">投标文件（至少 2 份）</label>
            <input id="bid_files" type="file" name="bid_files" multiple required>
          </div>
          <button type="submit">开始审查</button>
        </form>
        <div class="hint">
          <strong>演示建议：</strong>选择 `template` 可以快速出规则版，选择 `llm` 时系统会等待 LLM 完成后再给出最终入口报告。
        </div>
      </section>
      <section class="panel">
        <h2>最近案件</h2>
        {% if runs %}
        <table>
          <thead>
            <tr>
              <th>案件</th>
              <th>状态</th>
              <th>模式</th>
              <th>生成时间</th>
            </tr>
          </thead>
          <tbody>
            {% for run in runs %}
            <tr>
              <td><a href="{{ url_for('run_detail', run_id=run.run_id) }}">{{ run.run_id }}</a></td>
              <td class="state-{{ run.state }}">{{ run.state }}</td>
              <td>{{ run.mode }}</td>
              <td>{{ run.generated_at }}</td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
        {% else %}
        <p class="muted">还没有案件，先上传一组文件试跑一次。</p>
        {% endif %}
      </section>
    </section>
  </main>
</body>
</html>
"""

RUN_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{{ run_id }} - agent_bid_rigging</title>
  <style>
    :root {
      --bg: #f4efe6;
      --panel: #fffdfa;
      --ink: #1f2a33;
      --muted: #68727d;
      --line: #d9cdbd;
      --accent: #7c3f00;
      --ok: #256d1b;
      --warn: #8f5d00;
      --bad: #9a1f1f;
    }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: "Noto Serif SC", "Songti SC", serif; background: var(--bg); color: var(--ink); }
    main { width: min(1120px, calc(100vw - 48px)); margin: 28px auto 40px; display: grid; gap: 18px; }
    .panel { background: var(--panel); border: 1px solid var(--line); border-radius: 18px; padding: 22px; }
    h1, h2, h3 { margin: 0 0 12px; }
    .muted { color: var(--muted); }
    .meta { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
    .meta div { padding: 12px; border-radius: 12px; background: #faf5ee; border: 1px solid var(--line); }
    .links { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
    a.button {
      display: inline-flex; justify-content: center; align-items: center;
      text-decoration: none; padding: 12px 14px; border-radius: 14px;
      background: var(--accent); color: white; font-weight: 600;
    }
    a.secondary { background: transparent; border: 1px solid var(--line); color: var(--accent); }
    pre {
      margin: 0;
      padding: 18px;
      overflow: auto;
      border-radius: 16px;
      background: #1d2429;
      color: #f7f1e8;
      font-size: 13px;
      line-height: 1.5;
    }
    ul { margin: 0; padding-left: 20px; }
    .state-completed { color: var(--ok); }
    .state-running, .state-queued { color: var(--warn); }
    .state-failed { color: var(--bad); }
    @media (max-width: 900px) {
      main { width: min(100vw - 24px, 1120px); }
      .meta, .links { grid-template-columns: 1fr; }
    }
  </style>
  {% if auto_refresh %}
  <meta http-equiv="refresh" content="10">
  {% endif %}
</head>
<body>
  <main>
    <section class="panel">
      <a class="secondary" href="{{ url_for('index') }}">返回首页</a>
      <h1>{{ run_id }}</h1>
      <p class="muted">状态会自动刷新。对于本地大模型案件，页面会持续等待直到 LLM 报告完成。</p>
      <div class="meta">
        <div><strong>当前状态</strong><br><span class="state-{{ status.state }}">{{ status.state }}</span></div>
        <div><strong>请求模式</strong><br>{{ status.requested_mode or 'template' }}</div>
        <div><strong>生成时间</strong><br>{{ status.generated_at or job.generated_at or '-' }}</div>
        <div><strong>输出目录</strong><br>{{ run_dir }}</div>
      </div>
    </section>
    <section class="panel">
      <h2>报告入口</h2>
      <div class="links">
        {% for item in report_links %}
        <a class="button {% if item.secondary %}secondary{% endif %}" href="{{ item.href }}">{{ item.label }}</a>
        {% endfor %}
      </div>
    </section>
    <section class="panel">
      <h2>关键文件</h2>
      <ul>
        {% for item in artifact_links %}
        <li><a href="{{ item.href }}">{{ item.label }}</a></li>
        {% endfor %}
      </ul>
    </section>
    <section class="panel">
      <h2>运行状态 JSON</h2>
      <pre>{{ status_json }}</pre>
    </section>
    {% if summary_excerpt %}
    <section class="panel">
      <h2>摘要预览</h2>
      <pre>{{ summary_excerpt }}</pre>
    </section>
    {% endif %}
  </main>
</body>
</html>
"""


def create_app(base_dir: str | Path | None = None) -> Flask:
    app = Flask(__name__)
    root = Path(base_dir or Path.cwd() / "runs" / "web_demo").resolve()
    uploads_dir = root / "uploads"
    runs_dir = root / "runs"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    runs_dir.mkdir(parents=True, exist_ok=True)
    app.config["DEMO_BASE_DIR"] = root
    app.config["DEMO_UPLOADS_DIR"] = uploads_dir
    app.config["DEMO_RUNS_DIR"] = runs_dir

    @app.get("/")
    def index() -> str:
        return render_template_string(INDEX_TEMPLATE, runs=_list_runs(runs_dir))

    @app.post("/runs")
    def create_run() -> Any:
        tender_file = request.files.get("tender_file")
        bid_files = [item for item in request.files.getlist("bid_files") if item and item.filename]
        if tender_file is None or not tender_file.filename:
            abort(400, "Missing tender_file")
        if len(bid_files) < 2:
            abort(400, "At least two bid_files are required")

        run_id = _safe_run_id(request.form.get("label"))
        upload_dir = uploads_dir / run_id
        run_dir = runs_dir / run_id
        upload_dir.mkdir(parents=True, exist_ok=True)
        run_dir.mkdir(parents=True, exist_ok=True)

        tender_path = _save_uploaded_file(upload_dir / "tender", tender_file)
        requested_names = _parse_supplier_names(request.form.get("bid_names", ""))
        bids = {}
        for index, bid_file in enumerate(bid_files):
            bid_path = _save_uploaded_file(upload_dir / "bids", bid_file)
            supplier_name = (
                requested_names[index]
                if index < len(requested_names) and requested_names[index]
                else _derive_supplier_name(bid_file.filename, index + 1)
            )
            bids[supplier_name] = str(bid_path)

        opinion_mode = (request.form.get("opinion_mode") or "auto").lower()
        _write_json(
            run_dir / "web_job.json",
            {
                "run_id": run_id,
                "state": "queued",
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "opinion_mode": opinion_mode,
                "tender_path": str(tender_path),
                "bids": bids,
            },
        )

        worker = threading.Thread(
            target=_execute_run,
            kwargs={
                "run_id": run_id,
                "tender_path": str(tender_path),
                "bids": bids,
                "run_dir": run_dir,
                "opinion_mode": opinion_mode,
            },
            daemon=True,
        )
        worker.start()
        return redirect(url_for("run_detail", run_id=run_id))

    @app.get("/runs/<run_id>")
    def run_detail(run_id: str) -> str:
        run_dir = runs_dir / run_id
        if not run_dir.exists():
            abort(404)
        job = _read_json(run_dir / "web_job.json", default={"state": "unknown"})
        status = _read_json(
            run_dir / "llm_status.json",
            default={
                "state": job.get("state", "queued"),
                "requested_mode": job.get("opinion_mode", "template"),
            },
        )
        if job.get("state") in {"queued", "running", "failed"} and status.get("state") == "not-requested":
            status["state"] = job.get("state")
        summary_excerpt = None
        summary_path = run_dir / "summary.md"
        if summary_path.exists():
            summary_excerpt = summary_path.read_text(encoding="utf-8")[:5000]
        return render_template_string(
            RUN_TEMPLATE,
            run_id=run_id,
            run_dir=str(run_dir),
            job=job,
            status=status,
            status_json=json.dumps(status, ensure_ascii=False, indent=2),
            report_links=_report_links(run_dir),
            artifact_links=_artifact_links(run_id, run_dir),
            summary_excerpt=summary_excerpt,
            auto_refresh=status.get("state") in {"queued", "running"},
        )

    @app.get("/api/runs/<run_id>")
    def run_status(run_id: str) -> Any:
        run_dir = runs_dir / run_id
        if not run_dir.exists():
            abort(404)
        job = _read_json(run_dir / "web_job.json", default={})
        status = _read_json(run_dir / "llm_status.json", default={})
        return jsonify(
            {
                "run_id": run_id,
                "job": job,
                "llm_status": status,
                "available_reports": [item["label"] for item in _report_links(run_dir)],
            }
        )

    @app.get("/runs/<run_id>/artifacts/<path:name>")
    def artifact(run_id: str, name: str) -> Any:
        run_dir = runs_dir / run_id
        if not run_dir.exists():
            abort(404)
        path = (run_dir / name).resolve()
        if run_dir not in path.parents and path != run_dir:
            abort(403)
        if not path.exists() or not path.is_file():
            abort(404)
        return send_file(path)

    return app


def run_demo_server(host: str = "127.0.0.1", port: int = 8000, base_dir: str | Path | None = None) -> None:
    app = create_app(base_dir=base_dir)
    app.run(host=host, port=port, debug=False)


def _execute_run(
    run_id: str,
    tender_path: str,
    bids: dict[str, str],
    run_dir: Path,
    opinion_mode: str,
) -> None:
    _write_json(
        run_dir / "web_job.json",
        {
            "run_id": run_id,
            "state": "running",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "opinion_mode": opinion_mode,
            "tender_path": tender_path,
            "bids": bids,
        },
    )
    try:
        run_review(
            tender_path=tender_path,
            bids=bids,
            output_dir=str(run_dir),
            label=run_id,
            opinion_mode=opinion_mode,
        )
        _write_json(
            run_dir / "web_job.json",
            {
                "run_id": run_id,
                "state": "completed",
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "opinion_mode": opinion_mode,
                "tender_path": tender_path,
                "bids": bids,
            },
        )
    except Exception as exc:  # noqa: BLE001
        _write_json(
            run_dir / "web_job.json",
            {
                "run_id": run_id,
                "state": "failed",
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "opinion_mode": opinion_mode,
                "tender_path": tender_path,
                "bids": bids,
                "error": str(exc),
            },
        )


def _list_runs(runs_dir: Path) -> list[dict[str, str]]:
    runs: list[dict[str, str]] = []
    for item in sorted(runs_dir.iterdir(), reverse=True):
        if not item.is_dir():
            continue
        job = _read_json(item / "web_job.json", default={})
        status = _read_json(item / "llm_status.json", default={})
        runs.append(
            {
                "run_id": item.name,
                "state": status.get("state") or job.get("state", "unknown"),
                "mode": status.get("requested_mode") or job.get("opinion_mode", "template"),
                "generated_at": status.get("generated_at") or job.get("generated_at", "-"),
            }
        )
    return runs[:12]


def _save_uploaded_file(target_dir: Path, upload: FileStorage) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = secure_filename(upload.filename or "upload.bin") or "upload.bin"
    path = target_dir / filename
    upload.save(path)
    return path


def _parse_supplier_names(raw: str) -> list[str]:
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _derive_supplier_name(filename: str, fallback_index: int) -> str:
    stem = Path(filename).stem
    stem = re.sub(r"^[投中标文件_\-\s\d]+", "", stem)
    stem = stem.replace("投标文件", "").replace("报价文件", "").strip("-_ ")
    return stem or f"supplier_{fallback_index}"


def _safe_run_id(raw: str | None) -> str:
    if raw:
        normalized = unicodedata.normalize("NFKC", raw).strip()
        normalized = re.sub(r"[^\w\u4e00-\u9fff\-]+", "_", normalized)
        normalized = normalized.strip("._-")
        if normalized:
            return normalized
    return f"web_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def _report_links(run_dir: Path) -> list[dict[str, Any]]:
    mapping = [
        ("formal_report.md", "主报告"),
        ("formal_report.rule.md", "规则版报告"),
        ("formal_report.llm.md", "LLM 版报告"),
        ("opinion.md", "主意见书"),
        ("opinion.rule.md", "规则版意见书"),
        ("opinion.llm.md", "LLM 版意见书"),
        ("summary.md", "摘要"),
    ]
    links = []
    for name, label in mapping:
        path = run_dir / name
        if path.exists():
            links.append(
                {
                    "label": label,
                    "href": url_for("artifact", run_id=run_dir.name, name=name),
                    "secondary": name not in {"formal_report.md", "opinion.md"},
                }
            )
    return links


def _artifact_links(run_id: str, run_dir: Path) -> list[dict[str, str]]:
    names = [
        "price_analysis_table.json",
        "risk_score_table.json",
        "evidence_grade_table.json",
        "pairwise_report.json",
        "llm_status.json",
        "llm_review_layers.json",
    ]
    links = []
    for name in names:
        path = run_dir / name
        if path.exists():
            links.append(
                {
                    "label": name,
                    "href": url_for("artifact", run_id=run_id, name=name),
                }
            )
    return links


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
