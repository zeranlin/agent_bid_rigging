from __future__ import annotations

import json
import re
import threading
import unicodedata
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from flask import Flask, abort, jsonify, redirect, render_template_string, request, send_file, url_for
from markdown_it import MarkdownIt
from werkzeug.datastructures import FileStorage

from agent_bid_rigging.core.runner import run_review

DIMENSION_LABELS = {
    "identity_link": "主体关联",
    "pricing_link": "报价关联",
    "text_similarity": "文本与方案关联",
    "file_homology": "结构同源",
    "authorization_chain": "授权与资质链",
    "timeline_trace": "时间与电子痕迹",
}
DIMENSION_ORDER = (
    "identity_link",
    "pricing_link",
    "text_similarity",
    "file_homology",
    "authorization_chain",
    "timeline_trace",
)
DIMENSION_TIER_LABELS = {
    "strong": "强",
    "medium": "中",
    "weak": "弱",
    "none": "未命中",
}
MARKDOWN_RENDERER = MarkdownIt("commonmark", {"html": False, "linkify": True, "breaks": True})

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
    .mode-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
    }
    .mode-card {
      position: relative;
      display: grid;
      gap: 8px;
      padding: 16px;
      border: 1px solid var(--line);
      border-radius: 16px;
      background: #fffaf4;
    }
    .mode-card input {
      position: absolute;
      inset: 0;
      opacity: 0;
      cursor: pointer;
    }
    .mode-card.selected {
      border-color: var(--accent);
      box-shadow: 0 10px 24px rgba(124, 63, 0, 0.12);
      background: linear-gradient(180deg, #fff7ee 0%, #f7ebdb 100%);
    }
    .mode-card strong { font-size: 18px; }
    .mode-card span { color: var(--muted); font-size: 14px; }
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
      .grid, .row, .mode-grid { grid-template-columns: 1fr; }
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
          <div class="field">
            <label>审查模式</label>
            <div class="mode-grid">
              <label class="mode-card selected" id="mode-rule-card">
                <input type="radio" name="review_mode" value="rule" checked>
                <strong>规则审查</strong>
                <span>不调用大模型，快速返回规则版正式报告。</span>
              </label>
              <label class="mode-card" id="mode-llm-card">
                <input type="radio" name="review_mode" value="llm_ocr">
                <strong>大模型审查</strong>
                <span>调用 LLM + OCR，时间较长，返回增强版正式报告。</span>
              </label>
            </div>
          </div>
          <div class="field">
            <label for="bid_names">供应商名称（可选）</label>
            <textarea id="bid_names" name="bid_names" placeholder="每行 1 个名称，顺序与投标文件一致"></textarea>
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
          <strong>演示建议：</strong>规则审查适合快速演示；大模型审查会进入等待状态，系统会一直处理直到 LLM + OCR 完成后再展示结果。
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
  <script>
    const ruleCard = document.getElementById("mode-rule-card");
    const llmCard = document.getElementById("mode-llm-card");
    const syncModeCards = () => {
      const selected = document.querySelector("input[name='review_mode']:checked")?.value;
      ruleCard.classList.toggle("selected", selected === "rule");
      llmCard.classList.toggle("selected", selected === "llm_ocr");
    };
    document.querySelectorAll("input[name='review_mode']").forEach((radio) => {
      radio.addEventListener("change", syncModeCards);
    });
    syncModeCards();
  </script>
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
    .meta { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
    .meta div { padding: 12px; border-radius: 12px; background: #faf5ee; border: 1px solid var(--line); }
    .links { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; }
    .dimension-summary {
      margin-top: 16px;
      padding: 16px 18px;
      border-radius: 16px;
      background: #faf5ee;
      border: 1px solid var(--line);
      display: grid;
      gap: 10px;
    }
    .dimension-summary ul {
      padding-left: 18px;
      margin: 0;
    }
    .dimension-summary li {
      margin: 0;
      color: var(--ink);
    }
    .dimension-chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      margin: 4px 6px 0 0;
      padding: 4px 10px;
      border-radius: 999px;
      font-size: 13px;
      font-weight: 700;
      border: 1px solid transparent;
    }
    .dimension-chip.strong {
      background: #f6dfdf;
      color: #8b1f1f;
      border-color: #e5b9b9;
    }
    .dimension-chip.medium {
      background: #f8edd8;
      color: #8f5d00;
      border-color: #e8d2a6;
    }
    .dimension-chip.weak {
      background: #e7efe1;
      color: #256d1b;
      border-color: #c6dbbb;
    }
    a.button {
      display: grid;
      gap: 6px;
      text-decoration: none;
      padding: 16px 18px;
      border-radius: 18px;
      background: #fffaf4;
      border: 1px solid var(--line);
      color: var(--accent);
      font-weight: 600;
      min-height: 92px;
      align-content: center;
    }
    a.button.active {
      background: linear-gradient(180deg, #975200 0%, #7c3f00 100%);
      color: white;
      box-shadow: 0 12px 28px rgba(124, 63, 0, 0.22);
      border: 0;
    }
    a.button.active span { color: rgba(255,255,255,0.82); }
    a.button strong { font-size: 20px; }
    a.button span { font-size: 13px; color: color-mix(in srgb, var(--accent) 82%, white); }
    a.secondary {
      background: #fffaf4;
      border: 1px solid var(--line);
      color: var(--accent);
    }
    a.secondary span { color: color-mix(in srgb, var(--accent) 82%, white); }
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
    .report-viewer {
      max-width: 900px;
      margin: 0 auto;
      padding: 44px 58px 52px;
      border-radius: 18px;
      background: #ffffff;
      border: 1px solid #d8cbb8;
      box-shadow: 0 12px 24px rgba(69, 49, 23, 0.06);
      line-height: 1.75;
      font-size: 17px;
    }
    .report-viewer h1,
    .report-viewer h2,
    .report-viewer h3,
    .report-viewer h4 {
      color: #3b2a19;
      margin: 1.05em 0 0.45em;
      letter-spacing: 0.01em;
    }
    .report-viewer h1:first-child,
    .report-viewer h2:first-child,
    .report-viewer h3:first-child { margin-top: 0; }
    .report-viewer h1 {
      font-size: 52px;
      line-height: 1.18;
      text-align: center;
      margin-bottom: 1.1em;
      font-weight: 700;
    }
    .report-viewer h2 {
      font-size: 28px;
      margin-top: 1.35em;
    }
    .report-viewer h3 {
      font-size: 21px;
    }
    .report-viewer p {
      margin: 0.3em 0 0.82em;
      color: #1f2730;
    }
    .report-viewer ul,
    .report-viewer ol {
      margin: 0.35em 0 0.95em 1.45em;
      padding-left: 0.4em;
    }
    .report-viewer li { margin: 0.22em 0; }
    .report-viewer li > p { margin: 0.15em 0; }
    .report-viewer br + br {
      display: block;
      content: "";
      margin-top: 0.45em;
    }
    .report-viewer code {
      padding: 2px 6px;
      border-radius: 6px;
      background: #f4efe8;
      color: #4b3420;
      font-size: 0.95em;
    }
    .report-viewer pre {
      background: #1d2429;
      color: #f7f1e8;
      border-radius: 16px;
      padding: 16px;
      overflow: auto;
      margin: 0.8em 0;
    }
    .report-viewer pre code {
      background: transparent;
      color: inherit;
      padding: 0;
    }
    .report-viewer blockquote {
      margin: 0.8em 0;
      padding: 0.35em 1em;
      border-left: 4px solid #b99c79;
      color: #5a4b3d;
      background: #f8f5f1;
    }
    .report-viewer table {
      width: 100%;
      border-collapse: collapse;
      margin: 0.8em 0;
      font-size: 14px;
      background: #ffffff;
    }
    .report-viewer th,
    .report-viewer td {
      border: 1px solid #dfd2c1;
      padding: 8px 10px;
      text-align: left;
      vertical-align: top;
    }
    .report-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-bottom: 14px;
    }
    .report-signoff {
      margin-top: 3.2em;
      display: grid;
      justify-items: end;
      color: #3f3429;
      font-size: 15px;
    }
    .report-signoff p {
      margin: 0.18em 0;
      text-align: right;
    }
    .report-tabs {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-bottom: 16px;
    }
    .report-tab {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 132px;
      padding: 10px 14px;
      border-radius: 999px;
      border: 1px solid var(--line);
      text-decoration: none;
      color: var(--accent);
      background: #fffaf4;
      font-weight: 700;
    }
    .report-tab.active {
      background: linear-gradient(180deg, #975200 0%, #7c3f00 100%);
      color: white;
      border-color: transparent;
      box-shadow: 0 10px 24px rgba(124, 63, 0, 0.18);
    }
    .section-note {
      margin-top: -4px;
      margin-bottom: 16px;
      color: var(--muted);
      font-size: 14px;
    }
    .waiting {
      display: grid;
      gap: 14px;
      padding: 22px;
      border-radius: 18px;
      background: linear-gradient(180deg, #fff6ec 0%, #f8ead9 100%);
      border: 1px solid var(--line);
    }
    .spinner {
      width: 34px;
      height: 34px;
      border-radius: 999px;
      border: 3px solid rgba(124, 63, 0, 0.18);
      border-top-color: var(--accent);
      animation: spin 0.9s linear infinite;
    }
    @keyframes spin {
      to { transform: rotate(360deg); }
    }
    ul { margin: 0; padding-left: 20px; }
    .state-completed { color: var(--ok); }
    .state-running, .state-queued { color: var(--warn); }
    .state-failed { color: var(--bad); }
    @media (max-width: 900px) {
      main { width: min(100vw - 24px, 1120px); }
      .meta, .links { grid-template-columns: 1fr; }
      .report-viewer {
        padding: 28px 22px 32px;
        font-size: 15px;
      }
      .report-viewer h1 {
        font-size: 38px;
      }
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
      <p class="muted">状态会自动刷新。规则审查会较快完成；大模型审查会持续等待，直到 LLM + OCR 报告处理完成。</p>
      <div class="meta">
        <div><strong>当前状态</strong><br><span class="state-{{ status.state }}">{{ status.state }}</span></div>
        <div><strong>审查模式</strong><br>{{ mode_label }}</div>
        <div><strong>生成时间</strong><br>{{ status.generated_at or job.generated_at or '-' }}</div>
      </div>
    </section>
    <section class="panel">
      <h2>结果报告</h2>
      <p class="section-note">演示页默认只突出正式报告入口；规则审查展示 `formal_report.md`，大模型审查优先展示 `formal_report.llm.md`。</p>
      <div class="links">
        {% for item in report_links %}
        <a class="button {% if item.secondary %}secondary{% endif %} {% if item.active %}active{% endif %}" href="{{ item.href }}">
          <strong>{{ item.label }}</strong>
          <span>{{ item.caption }}</span>
        </a>
        {% endfor %}
      </div>
      {% if dimension_overview %}
      <div class="dimension-summary">
        <strong>维度摘要概览</strong>
        <ul>
          {% for item in dimension_overview %}
          <li>
            <strong>{{ item.pair }}</strong>：
            {% for chip in item.chips %}
            <span class="dimension-chip {{ chip.tier }}">{{ chip.label }}{{ chip.tier_label }}</span>
            {% endfor %}
          </li>
          {% endfor %}
        </ul>
      </div>
      {% endif %}
    </section>
    {% if auto_refresh %}
    <section class="panel">
      <h2>等待审查完成</h2>
      <div class="waiting">
        <div class="spinner"></div>
        <div>
          <strong>系统正在处理案件材料。</strong><br>
          {% if mode_label == '大模型审查（LLM + OCR）' %}
          当前正在执行 OCR、事实融合与 LLM 报告生成，请耐心等待页面自动刷新。
          {% else %}
          当前正在执行规则抽取、比对与正式报告生成，请稍候。
          {% endif %}
        </div>
      </div>
    </section>
    {% endif %}
    {% if report_content %}
    <section class="panel">
      <h2>报告查看</h2>
      <p class="section-note">这里直接展示当前案件的正式报告正文。</p>
      <div class="report-actions">
        <a class="button secondary" href="{{ export_href }}">导出当前报告</a>
      </div>
      <div class="report-viewer">{{ report_content|safe }}</div>
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

        review_mode = (request.form.get("review_mode") or "rule").lower()
        opinion_mode, enable_ocr = _resolve_review_mode(review_mode)
        _write_json(
            run_dir / "web_job.json",
            {
                "run_id": run_id,
                "state": "queued",
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "review_mode": review_mode,
                "opinion_mode": opinion_mode,
                "enable_ocr": enable_ocr,
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
                "enable_ocr": enable_ocr,
                "review_mode": review_mode,
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
        selected_report = request.args.get("report", "main")
        report_path, report_label = _resolve_report_variant(run_dir, selected_report)
        report_content = None
        if report_path.exists():
            report_content = _render_markdown(_normalize_report_markdown(report_path.read_text(encoding="utf-8")))
        return render_template_string(
            RUN_TEMPLATE,
            run_id=run_id,
            job=job,
            status=status,
            mode_label=_review_mode_label(job.get("review_mode")),
            status_json=json.dumps(status, ensure_ascii=False, indent=2),
            report_links=_report_links(run_id, run_dir, selected_report),
            dimension_overview=_build_dimension_overview(run_dir),
            export_href=url_for("artifact", run_id=run_id, name=report_path.name, download=1),
            report_content=report_content,
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
                "review_mode": job.get("review_mode", "rule"),
                "available_reports": [item["label"] for item in _report_links(run_id, run_dir, "main")],
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
        download = request.args.get("download") == "1"
        return send_file(path, as_attachment=download, download_name=path.name if download else None)

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
    enable_ocr: bool,
    review_mode: str,
) -> None:
    _write_json(
        run_dir / "web_job.json",
        {
            "run_id": run_id,
            "state": "running",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "review_mode": review_mode,
            "opinion_mode": opinion_mode,
            "enable_ocr": enable_ocr,
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
            enable_ocr=enable_ocr,
        )
        _write_json(
            run_dir / "web_job.json",
            {
                "run_id": run_id,
                "state": "completed",
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "review_mode": review_mode,
                "opinion_mode": opinion_mode,
                "enable_ocr": enable_ocr,
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
                "review_mode": review_mode,
                "opinion_mode": opinion_mode,
                "enable_ocr": enable_ocr,
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
                "mode": _review_mode_label(job.get("review_mode")),
                "generated_at": status.get("generated_at") or job.get("generated_at", "-"),
            }
        )
    return runs[:12]


def _save_uploaded_file(target_dir: Path, upload: FileStorage) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = _safe_upload_filename(upload.filename or "upload.bin")
    path = _unique_upload_path(target_dir, filename)
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


def _safe_upload_filename(raw: str) -> str:
    normalized = unicodedata.normalize("NFKC", raw).strip()
    normalized = normalized.replace("\\", "/").split("/")[-1]
    normalized = re.sub(r"\s+", "_", normalized)
    normalized = re.sub(r"[^\w\u4e00-\u9fff.\-()（）]+", "_", normalized)
    normalized = normalized.strip("._-")
    return normalized or "upload.bin"


def _unique_upload_path(target_dir: Path, filename: str) -> Path:
    candidate = target_dir / filename
    if not candidate.exists():
        return candidate

    stem = Path(filename).stem or "upload"
    suffix = Path(filename).suffix
    index = 2
    while True:
        candidate = target_dir / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def _report_links(run_id: str, run_dir: Path, selected: str) -> list[dict[str, Any]]:
    mapping = [
        ("formal_report.md", "主报告", "当前正式报告主入口", "main"),
        ("formal_report.rule.md", "规则版报告", "规则链路生成的正式报告", "rule"),
        ("formal_report.llm.md", "大模型版报告", "LLM + OCR 增强版正式报告", "llm"),
    ]
    links = []
    for name, label, caption, key in mapping:
        path = run_dir / name
        if path.exists():
            links.append(
                {
                    "label": label,
                    "caption": caption,
                    "href": url_for("run_detail", run_id=run_id, report=key),
                    "secondary": name != "formal_report.md",
                    "active": selected == key,
                }
            )
    return links


def _build_dimension_overview(run_dir: Path) -> list[dict[str, str]]:
    risk_rows = _read_json(run_dir / "risk_score_table.json", default=[])
    if not isinstance(risk_rows, list):
        return []
    rows: list[dict[str, str]] = []
    for item in risk_rows[:6]:
        summary = _render_dimension_summary_text(item.get("dimension_summary", {}))
        if not summary:
            continue
        rows.append(
            {
                "pair": f"{item.get('supplier_a', '-')} 与 {item.get('supplier_b', '-')}",
                "summary": summary,
                "chips": _build_dimension_chips(item.get("dimension_summary", {})),
            }
        )
    return rows


def _render_dimension_summary_text(summary: dict[str, dict]) -> str:
    if not summary:
        return ""
    parts: list[str] = []
    for key in DIMENSION_ORDER:
        item = summary.get(key, {})
        tier = item.get("tier", "none")
        if tier == "none":
            continue
        parts.append(f"{DIMENSION_LABELS[key]}{DIMENSION_TIER_LABELS.get(tier, '未命中')}")
    if not parts:
        return "六个判断维度均未形成明确命中"
    return "；".join(parts)


def _build_dimension_chips(summary: dict[str, dict]) -> list[dict[str, str]]:
    chips: list[dict[str, str]] = []
    for key in DIMENSION_ORDER:
        item = summary.get(key, {})
        tier = item.get("tier", "none")
        if tier == "none":
            continue
        chips.append(
            {
                "label": DIMENSION_LABELS[key],
                "tier": tier,
                "tier_label": DIMENSION_TIER_LABELS.get(tier, ""),
            }
        )
    return chips


def _resolve_report_variant(run_dir: Path, selected: str) -> tuple[Path, str]:
    variant_map = {
        "main": ("formal_report.md", "主报告"),
        "rule": ("formal_report.rule.md", "规则版"),
        "llm": ("formal_report.llm.md", "LLM版"),
    }
    filename, label = variant_map.get(selected, variant_map["main"])
    path = run_dir / filename
    if path.exists():
        return path, label
    return run_dir / "formal_report.md", "主报告"


def _report_variants(run_id: str, run_dir: Path, active_label: str) -> list[dict[str, Any]]:
    variants = [
        ("主报告", "main", run_dir / "formal_report.md"),
        ("规则版", "rule", run_dir / "formal_report.rule.md"),
        ("LLM版", "llm", run_dir / "formal_report.llm.md"),
    ]
    rows = []
    for label, key, path in variants:
        if not path.exists():
            continue
        rows.append(
            {
                "label": label,
                "href": url_for("run_detail", run_id=run_id, report=key),
                "active": label == active_label,
            }
        )
    return rows


def _resolve_review_mode(review_mode: str) -> tuple[str, bool]:
    if review_mode == "llm_ocr":
        return "llm", True
    return "template", False


def _review_mode_label(review_mode: str | None) -> str:
    if review_mode == "llm_ocr":
        return "大模型审查（LLM + OCR）"
    return "规则审查"


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _render_markdown(text: str) -> str:
    try:
        html = MARKDOWN_RENDERER.render(text)
        return _postprocess_report_html(html)
    except Exception:  # noqa: BLE001
        return f"<pre>{escape(text)}</pre>"


def _normalize_report_markdown(text: str) -> str:
    lines = text.splitlines()
    if not lines:
        return text
    first_line = lines[0].strip()
    if re.fullmatch(r"\*\*[^*]+\*\*", first_line):
        title = first_line[2:-2].strip()
        if title in {"围串标审查意见书", "围串标审查报告"}:
            lines[0] = f"# {title}"
    return "\n".join(lines)


def _postprocess_report_html(html: str) -> str:
    patterns = [
        re.compile(
            r"<p>审查人：(?P<reviewer>[^<]+)</p>\s*<p>审查日期：(?P<date>[^<]+)</p>\s*$",
            flags=re.S,
        ),
        re.compile(
            r"<p>审查人：(?P<reviewer>[^<]+)<br\s*/?>\s*审查日期：(?P<date>[^<]+)</p>\s*$",
            flags=re.S,
        ),
    ]
    replacement = r'<div class="report-signoff"><p>审查人：\g<reviewer></p><p>审查日期：\g<date></p></div>'
    for pattern in patterns:
        updated = pattern.sub(replacement, html)
        if updated != html:
            return updated
    return html
