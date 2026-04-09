from __future__ import annotations

import json
import os
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
      --bg: #f6f7f9;
      --panel: #ffffff;
      --panel-soft: #f8f9fb;
      --ink: #1f2933;
      --muted: #667085;
      --line: #d9dee5;
      --accent: #2563eb;
      --accent-soft: #eaf2ff;
      --ok: #1f7a36;
      --warn: #9a6700;
      --bad: #b42318;
      --shadow: 0 10px 26px rgba(15, 23, 42, 0.06);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      background: var(--bg);
      color: var(--ink);
      min-height: 100vh;
    }
    main {
      width: min(1040px, calc(100vw - 32px));
      margin: 24px auto 40px;
    }
    .hero, .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 16px;
      box-shadow: var(--shadow);
    }
    .hero {
      display: grid;
      gap: 12px;
      padding: 28px;
      margin-bottom: 18px;
    }
    h1, h2, h3 { margin: 0; font-weight: 700; }
    h1 {
      font-size: 30px;
      line-height: 1.25;
    }
    h2 {
      font-size: 20px;
      margin-bottom: 14px;
    }
    p, li, label, input, select, button, textarea, th, td { font-size: 15px; line-height: 1.6; }
    .muted { color: var(--muted); }
    .grid {
      display: grid;
      grid-template-columns: minmax(0, 1.2fr) minmax(280px, 0.9fr);
      gap: 18px;
      align-items: start;
    }
    .hero-kicker {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      width: fit-content;
      padding: 4px 10px;
      border-radius: 999px;
      background: var(--accent-soft);
      color: var(--accent);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.02em;
    }
    .hero-kicker::before {
      content: "";
      width: 6px;
      height: 6px;
      border-radius: 999px;
      background: var(--accent);
    }
    .panel {
      padding: 22px;
      background: var(--panel);
    }
    .hero-lead {
      max-width: 52em;
      margin: 0;
      font-size: 15px;
    }
    form { display: grid; gap: 14px; }
    .field { display: grid; gap: 8px; }
    label {
      font-size: 14px;
      font-weight: 700;
      color: var(--ink);
    }
    input[type="text"], select, textarea, input[type="file"] {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 10px 12px;
      background: var(--panel-soft);
      color: var(--ink);
      transition: border-color 180ms ease, box-shadow 180ms ease;
    }
    input[type="text"]::placeholder {
      color: #98a2b3;
    }
    input[type="text"]:focus,
    textarea:focus,
    input[type="file"]:focus {
      outline: none;
      border-color: rgba(37, 99, 235, 0.45);
      box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.12);
    }
    input[type="file"] {
      min-height: 46px;
    }
    .upload-pair {
      display: grid;
      gap: 12px;
    }
    button, .button {
      appearance: none;
      border: 0;
      border-radius: 10px;
      padding: 11px 16px;
      background: var(--accent);
      color: white;
      text-decoration: none;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-weight: 600;
      box-shadow: none;
      transition: background 180ms ease;
    }
    button:hover, .button:hover {
      background: #1d4ed8;
    }
    .button.secondary {
      background: transparent;
      color: var(--ink);
      border: 1px solid var(--line);
      box-shadow: none;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 15px;
    }
    th, td {
      text-align: left;
      border-bottom: 1px solid var(--line);
      padding: 10px 8px;
      vertical-align: top;
    }
    th {
      color: var(--muted);
      font-size: 12px;
      letter-spacing: 0.02em;
      font-weight: 700;
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
    .hint {
      padding: 12px 14px;
      border-radius: 12px;
      background: #f8fafc;
      border: 1px dashed var(--line);
      color: var(--muted);
    }
    .hint strong { color: var(--ink); }
    .runs-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin-bottom: 8px;
    }
    .runs-note {
      color: var(--muted);
      font-size: 14px;
      margin: 0 0 14px;
      max-width: 28em;
    }
    @media (max-width: 900px) {
      main { width: min(100vw - 20px, 1040px); }
      .grid { grid-template-columns: 1fr; }
      .hero {
        padding: 22px;
      }
      h1 {
        font-size: 26px;
      }
      .panel {
        padding: 18px;
      }
    }
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <span class="hero-kicker">最小演示版</span>
      <h1>围串标审查工作台</h1>
      <p class="hero-lead muted">上传 1 份招标文件和多家投标文件，系统会沿着现有审查链路完成抽取、比对、打分，并在处理完成后展示正式报告。</p>
    </section>
    <section class="grid">
      <section class="panel">
        <h2>新建案件</h2>
        <form action="{{ url_for('create_run') }}" method="post" enctype="multipart/form-data">
          <input type="hidden" name="review_mode" value="llm_ocr">
          <div class="field">
            <label for="label">案件标识</label>
            <input id="label" type="text" name="label" placeholder="例如：wcb_demo_release">
          </div>
          <div class="upload-pair">
            <div class="field">
              <label for="tender_file">招标文件</label>
              <input id="tender_file" type="file" name="tender_file" required>
            </div>
            <div class="field">
              <label for="bid_files">投标文件（至少 2 份）</label>
              <input id="bid_files" type="file" name="bid_files" multiple required>
            </div>
          </div>
          <button type="submit">开始审查</button>
        </form>
        <div class="hint">
          <strong>演示建议：</strong>当前页面仅保留大模型审查入口；提交后会持续等待，直到 LLM + OCR 完成后再展示结果。
        </div>
      </section>
      <section class="panel">
        <div class="runs-head">
          <h2>最近案件</h2>
          <span class="badge">最近运行</span>
        </div>
        <p class="runs-note">这里会展示最近案件的处理状态，方便直接查看正在等待的任务和已经完成的报告。</p>
        {% if runs %}
        <table>
          <thead>
            <tr>
              <th>案件</th>
              <th>状态</th>
              <th>生成时间</th>
            </tr>
          </thead>
          <tbody>
            {% for run in runs %}
            <tr>
              <td><a href="{{ url_for('run_detail', run_id=run.run_id) }}">{{ run.run_id }}</a></td>
              <td class="state-{{ run.state }}">{{ run.state_label }}</td>
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
      --bg: #f5f7ff;
      --panel: rgba(255, 255, 255, 0.84);
      --ink: #182033;
      --muted: #5c6880;
      --line: rgba(108, 123, 168, 0.22);
      --accent: #205cff;
      --accent-2: #8a3ffc;
      --ok: #18864b;
      --warn: #a56400;
      --bad: #c23552;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Avenir Next", "PingFang SC", "Helvetica Neue", sans-serif;
      background:
        radial-gradient(circle at 8% 12%, rgba(99, 102, 241, 0.22) 0, rgba(99, 102, 241, 0) 28%),
        radial-gradient(circle at 84% 12%, rgba(17, 184, 178, 0.16) 0, rgba(17, 184, 178, 0) 26%),
        linear-gradient(180deg, #f7f9ff 0%, #eef3ff 100%);
      color: var(--ink);
    }
    main { width: min(1180px, calc(100vw - 40px)); margin: 24px auto 40px; display: grid; gap: 18px; }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 28px;
      padding: 26px;
      backdrop-filter: blur(14px);
      -webkit-backdrop-filter: blur(14px);
      box-shadow: 0 24px 80px rgba(41, 57, 97, 0.14);
    }
    h1, h2, h3 { margin: 0 0 12px; }
    .muted { color: var(--muted); }
    .meta { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
    .meta div {
      padding: 14px 16px;
      border-radius: 20px;
      background: rgba(255,255,255,0.72);
      border: 1px solid var(--line);
    }
    .links { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; }
    .dimension-summary {
      margin-top: 16px;
      padding: 16px 18px;
      border-radius: 22px;
      background: rgba(255,255,255,0.8);
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
      background: rgba(194, 53, 82, 0.1);
      color: #a02248;
      border-color: rgba(194, 53, 82, 0.16);
    }
    .dimension-chip.medium {
      background: rgba(247, 173, 44, 0.12);
      color: #a56400;
      border-color: rgba(247, 173, 44, 0.22);
    }
    .dimension-chip.weak {
      background: rgba(24, 134, 75, 0.1);
      color: #18864b;
      border-color: rgba(24, 134, 75, 0.18);
    }
    a.button {
      display: grid;
      gap: 6px;
      text-decoration: none;
      padding: 16px 18px;
      border-radius: 22px;
      background: rgba(255,255,255,0.78);
      border: 1px solid var(--line);
      color: var(--accent);
      font-weight: 600;
      min-height: 92px;
      align-content: center;
    }
    a.button.active {
      background: linear-gradient(135deg, var(--accent) 0%, var(--accent-2) 100%);
      color: white;
      box-shadow: 0 16px 32px rgba(74, 81, 228, 0.24);
      border: 0;
    }
    a.button.active span { color: rgba(255,255,255,0.82); }
    a.button strong { font-size: 20px; }
    a.button span { font-size: 13px; color: color-mix(in srgb, var(--accent) 80%, white); }
    a.secondary {
      background: rgba(255,255,255,0.78);
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
      border-radius: 30px;
      background: #ffffff;
      border: 1px solid rgba(118, 133, 180, 0.18);
      box-shadow: 0 22px 44px rgba(41, 57, 97, 0.1);
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
      font-size: 44px;
      line-height: 1.18;
      text-align: center;
      margin-bottom: 1.1em;
      font-weight: 700;
      letter-spacing: 0.02em;
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
      border-radius: 26px;
      background: linear-gradient(135deg, rgba(32, 92, 255, 0.08) 0%, rgba(138, 63, 252, 0.1) 100%);
      border: 1px solid var(--line);
    }
    .spinner {
      width: 34px;
      height: 34px;
      border-radius: 999px;
      border: 3px solid rgba(32, 92, 255, 0.18);
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
      main { width: min(100vw - 20px, 1120px); }
      .meta, .links { grid-template-columns: 1fr; }
      .report-viewer {
        padding: 28px 22px 32px;
        font-size: 15px;
      }
      .report-viewer h1 {
        font-size: 34px;
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
      <p class="muted">状态会自动刷新。当前页面默认展示大模型审查任务，并持续等待直到 LLM + OCR 报告处理完成。</p>
      <div class="meta">
        <div><strong>当前状态</strong><br><span class="state-{{ status.state }}">{{ status_label }}</span></div>
        <div><strong>审查模式</strong><br>{{ mode_label }}</div>
        <div><strong>生成时间</strong><br>{{ status.generated_at or job.generated_at or '-' }}</div>
      </div>
    </section>
    {% if dimension_overview %}
    <section class="panel">
      <h2>结果概览</h2>
      {% if not waiting_for_llm_result %}
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
    {% endif %}
    {% if waiting_for_llm_result %}
    <section class="panel">
      <h2>等待审查完成</h2>
      <div class="waiting">
        <div class="spinner"></div>
        <div>
          <strong>系统正在处理案件材料。</strong><br>
          当前正在执行 OCR、事实融合与 LLM 报告生成，请耐心等待页面自动刷新；增强报告完成前不会展示任何报告正文。
        </div>
      </div>
    </section>
    {% endif %}
    {% if report_content and not waiting_for_llm_result %}
    <section class="panel">
      <h2>报告查看</h2>
      <p class="section-note">这里直接展示当前案件的大模型增强报告正文。</p>
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
    app.config["ACTIVE_WEB_RUNS"] = set()
    app.config["WEB_RUN_STALE_SECONDS"] = int(os.getenv("AGENT_BID_RIGGING_WEB_STALE_SECONDS", "180"))

    @app.get("/")
    def index() -> str:
        return render_template_string(
            INDEX_TEMPLATE,
            runs=_list_runs(
                runs_dir,
                active_run_ids=app.config["ACTIVE_WEB_RUNS"],
                stale_after_seconds=app.config["WEB_RUN_STALE_SECONDS"],
            ),
        )

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

        review_mode = (request.form.get("review_mode") or "llm_ocr").lower()
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
                "active_run_ids": app.config["ACTIVE_WEB_RUNS"],
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
        job, status = _load_run_state(
            run_dir,
            active_run_ids=app.config["ACTIVE_WEB_RUNS"],
            stale_after_seconds=app.config["WEB_RUN_STALE_SECONDS"],
        )
        if job.get("state") in {"queued", "running", "failed"} and status.get("state") == "not-requested":
            status["state"] = job.get("state")
        waiting_for_llm_result = _should_wait_for_llm_result(job, status, run_dir)
        selected_report = request.args.get("report", "main")
        if job.get("review_mode") == "llm_ocr":
            if waiting_for_llm_result:
                selected_report = "llm"
            report_path, report_label = _resolve_llm_report_variant(run_dir)
        else:
            report_path, report_label = _resolve_default_report_variant(run_dir)
        report_content = None
        if report_path.exists() and not waiting_for_llm_result:
            report_content = _render_markdown(_normalize_report_markdown(report_path.read_text(encoding="utf-8")))
        return render_template_string(
            RUN_TEMPLATE,
            run_id=run_id,
            job=job,
            status=status,
            status_label=_status_label(status.get("state") or job.get("state")),
            mode_label=_review_mode_label(job.get("review_mode")),
            status_json=json.dumps(status, ensure_ascii=False, indent=2),
            report_links=_report_links(run_id, run_dir, selected_report) if not waiting_for_llm_result else [],
            dimension_overview=_build_dimension_overview(run_dir),
            export_href=url_for("artifact", run_id=run_id, name=report_path.name, download=1),
            report_content=report_content,
            auto_refresh=status.get("state") in {"queued", "running"},
            waiting_for_llm_result=waiting_for_llm_result,
            llm_result_only=(job.get("review_mode") == "llm_ocr"),
        )

    @app.get("/api/runs/<run_id>")
    def run_status(run_id: str) -> Any:
        run_dir = runs_dir / run_id
        if not run_dir.exists():
            abort(404)
        job, status = _load_run_state(
            run_dir,
            active_run_ids=app.config["ACTIVE_WEB_RUNS"],
            stale_after_seconds=app.config["WEB_RUN_STALE_SECONDS"],
        )
        return jsonify(
            {
                "run_id": run_id,
                "job": job,
                "llm_status": status,
                "review_mode": job.get("review_mode", "llm_ocr"),
                "available_reports": []
                if _should_wait_for_llm_result(job, status, run_dir)
                else [item["label"] for item in _report_links(run_id, run_dir, "main")],
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
    active_run_ids: set[str] | None = None,
) -> None:
    if active_run_ids is not None:
        active_run_ids.add(run_id)
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
    finally:
        if active_run_ids is not None:
            active_run_ids.discard(run_id)


def _list_runs(runs_dir: Path, active_run_ids: set[str], stale_after_seconds: int) -> list[dict[str, str]]:
    runs: list[dict[str, str]] = []
    for item in sorted(runs_dir.iterdir(), reverse=True):
        if not item.is_dir():
            continue
        job, status = _load_run_state(
            item,
            active_run_ids=active_run_ids,
            stale_after_seconds=stale_after_seconds,
        )
        runs.append(
            {
                "run_id": item.name,
                "state": status.get("state") or job.get("state", "unknown"),
                "state_label": _status_label(status.get("state") or job.get("state", "unknown")),
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


def _load_run_state(run_dir: Path, active_run_ids: set[str], stale_after_seconds: int) -> tuple[dict[str, Any], dict[str, Any]]:
    job = _read_json(run_dir / "web_job.json", default={"state": "unknown"})
    status = _read_json(
        run_dir / "llm_status.json",
        default={
            "state": job.get("state", "queued"),
            "requested_mode": job.get("opinion_mode", "template"),
        },
    )
    return _mark_stale_run_failed(run_dir, job, status, active_run_ids, stale_after_seconds)


def _mark_stale_run_failed(
    run_dir: Path,
    job: dict[str, Any],
    status: dict[str, Any],
    active_run_ids: set[str],
    stale_after_seconds: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    run_id = job.get("run_id") or run_dir.name
    if run_id in active_run_ids:
        return job, status
    if job.get("state") not in {"queued", "running"} and status.get("state") not in {"queued", "running"}:
        return job, status

    generated_at = job.get("generated_at") or status.get("generated_at")
    if not generated_at:
        return job, status
    try:
        generated_at_dt = datetime.fromisoformat(generated_at)
    except ValueError:
        return job, status
    age_seconds = (datetime.now() - generated_at_dt).total_seconds()
    if age_seconds < stale_after_seconds:
        return job, status

    error = "Web 服务重启或后台任务中断，旧运行任务已自动标记为失败。"
    failed_at = datetime.now().isoformat(timespec="seconds")
    failed_job = {
        **job,
        "run_id": run_id,
        "state": "failed",
        "generated_at": failed_at,
        "error": error,
    }
    failed_status = {
        **status,
        "requested_mode": status.get("requested_mode") or job.get("opinion_mode", "template"),
        "state": "failed",
        "generated_at": failed_at,
        "error": error,
    }
    _write_json(run_dir / "web_job.json", failed_job)
    _write_json(run_dir / "llm_status.json", failed_status)
    return failed_job, failed_status


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


def _resolve_llm_report_variant(run_dir: Path) -> tuple[Path, str]:
    return run_dir / "formal_report.llm.md", "LLM版"


def _resolve_default_report_variant(run_dir: Path) -> tuple[Path, str]:
    return run_dir / "formal_report.md", "正式报告"


def _should_wait_for_llm_result(job: dict[str, Any], status: dict[str, Any], run_dir: Path) -> bool:
    if job.get("review_mode") != "llm_ocr":
        return False
    if status.get("state") != "completed":
        return True
    return not (run_dir / "formal_report.llm.md").exists()


def _status_label(state: str | None) -> str:
    mapping = {
        "completed": "完成",
        "failed": "失败",
        "running": "处理中",
        "queued": "排队中",
    }
    return mapping.get((state or "").lower(), state or "-")


def _resolve_review_mode(review_mode: str) -> tuple[str, bool]:
    if review_mode == "llm_ocr":
        return "llm", True
    return "template", False


def _review_mode_label(review_mode: str | None) -> str:
    if review_mode == "llm_ocr":
        return "大模型审查（LLM + OCR）"
    return "正式审查"


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
    lines = text.lstrip("\ufeff").splitlines()
    if not lines:
        return text
    title_candidates = {"围串标审查意见书", "围串标审查报告"}
    for index, raw_line in enumerate(lines[:3]):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("# "):
            title = line[2:].strip()
            if title in title_candidates:
                lines[index] = f"# {title}"
            break
        if re.fullmatch(r"\*\*[^*]+\*\*", line):
            title = line[2:-2].strip()
            if title in title_candidates:
                lines[index] = f"# {title}"
                break
        break
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
