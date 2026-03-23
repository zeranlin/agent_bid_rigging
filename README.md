# agent_bid_rigging

`agent_bid_rigging` 是一个面向政府采购围串标筛查的 agent-first 审查 harness。它接收 1 份招标文件和多份投标文件，抽取可比较信号，执行投标人两两异常模式检查，并输出可供人工审查员复核的审查产物包。

本仓库刻意按照 OpenAI 的 harness engineering 思路组织：

- 从空仓库起步，让仓库本身成为运行界面
- 保持 `AGENTS.md` 简短，把 `docs/` 作为事实文档入口
- 构建可重复的“任务定义 -> 工具执行 -> 证据采集 -> 评分 -> 审查产物”循环

相关参考：

- [Harness engineering](https://openai.com/zh-Hans-CN/index/harness-engineering/)
- [Unrolling the Codex agent loop](https://openai.com/zh-Hans-CN/index/unrolling-the-codex-agent-loop/)

## 系统能做什么

1. 从磁盘加载 1 份招标材料包和多份投标材料包。
2. 通过解析后端与递归加载能力标准化文档文本。
3. 抽取可疑信号：
   - 电话、邮箱、地址、法定代表人、银行账户等重合
   - 报价完全一致或高度接近
   - 非模板文本在不同投标人之间重合
   - 不来源于招标文件的罕见文本重合
4. 为每组投标人评分，并给出 `low`、`medium`、`high`、`critical` 风险等级。
5. 生成结构化审查意见书，并可选使用 LLM 增强文案。
6. 持久化完整运行目录，包含机器可读 JSON 与人类可读 Markdown 产物。

## 仓库结构

- `AGENTS.md`：简洁的 agent 工作地图
- `ARCHITECTURE.md`：系统分层和审查主循环
- `docs/design-docs/`：设计意图和核心信念
- `docs/exec-plans/`：活动与已完成执行计划
- `src/agent_bid_rigging/`：CLI harness 与审查引擎
- `runs/`：运行生成的审查产物
- `examples/`：示例招标和投标文件

## 快速开始

```bash
cd /Users/linzeran/code/2026-zn/agent_bid_rigging
python3 -m pip install -e .
agent-bid-rigging analyze \
  --tender examples/tender.txt \
  --bid alpha=examples/bid_alpha.txt \
  --bid beta=examples/bid_beta.txt \
  --bid gamma=examples/bid_gamma.txt \
  --opinion-mode auto
```

真实采购包示例：

```bash
agent-bid-rigging analyze \
  --tender 招标文件-01-胃肠镜.zip \
  --bid 恒禾=投标文件-01-恒禾.zip \
  --bid 华康=投标文件-01-华康.zip \
  --bid 唯美=投标文件-01-唯美.zip \
  --output-dir runs/wcb_review \
  --opinion-mode template
```

最小 Web 演示：

```bash
agent-bid-rigging web-demo --host 127.0.0.1 --port 8000
```

打开 `http://127.0.0.1:8000` 后可以：

- 上传 1 份招标文件和多份投标文件
- 不写 CLI 命令也能启动新的审查任务
- 在本地慢速 LLM 场景下查看运行状态
- 在浏览器中打开 `formal_report`、`opinion` 与关键证据表

OCR 能力示例：

```bash
agent-bid-rigging ocr \
  --input /path/to/proof.pdf \
  --output-dir runs/ocr_demo
```

这个命令会从 PDF 中提取嵌入图片，或直接接收单独图片，然后调用配置好的多模态模型描述图像内容，并写出：

- `image_index.json`
- `image_ocr_table.json`
- `ocr_result.json`
- `ocr_result.md`

该命令会在 `runs/` 下创建一个带时间戳的目录，包含：

- `manifest.json`
- `case_manifest.json`
- `source_file_index.json`
- `extracted_file_index.json`
- `document_catalog.json`
- `entity_field_table.json`
- `price_analysis_table.json`
- `structure_similarity_table.json`
- `file_fingerprint_table.json`
- `duplicate_detection_table.json`
- `text_similarity_table.json`
- `shared_error_table.json`
- `authorization_chain_table.json`
- `license_match_table.json`
- `timeline_table.json`
- `evidence_grade_table.json`
- `risk_score_table.json`
- `review_conclusion_table.json`
- `formal_report.json`
- `formal_report.rule.json`
- `formal_report.rule.md`
- `formal_report.md`
- `normalized/*.json`
- `pairwise_report.json`
- `summary.md`
- `opinion.json`
- `opinion.rule.json`
- `opinion.rule.md`
- `opinion.md`

## LLM 审查层

系统现在内置了意见草拟层：

- `--opinion-mode template`：始终生成确定性的模板意见
- `--opinion-mode llm`：强制通过 OpenAI Responses API 生成 LLM 版意见
- `--opinion-mode auto`：配置了 `OPENAI_API_KEY` 时使用 OpenAI，否则回退到确定性模板

环境变量：

- `OPENAI_API_KEY`：启用 LLM 意见草拟
- `OPENAI_MODEL`：可选模型覆盖，默认 `gpt-5`
- `OPENAI_BASE_URL`：可选的 OpenAI 兼容根地址或 Responses 接口覆盖
- `OPENAI_TIMEOUT`：可选请求超时秒数，默认 `1800`
- `OPENAI_REASONING_EFFORT`：可选推理强度，例如 `low`
- `OPENAI_NO_THINKING`：面向兼容接口的布尔开关，设为 `1` 时发送 `enable_thinking=false`
- `AGENT_BID_RIGGING_ASYNC_LLM`：可选布尔开关，仅当你希望先写规则版产物、再后台继续做 LLM 增强时设为 `1`

自托管 OpenAI 兼容接口示例：

```bash
export OPENAI_BASE_URL="http://112.111.54.86:10011/v1"
export OPENAI_MODEL="qwen3.5-27b"
export OPENAI_API_KEY="your-password-or-api-key"
export OPENAI_TIMEOUT="1800"
export OPENAI_NO_THINKING="1"
agent-bid-rigging analyze \
  --tender 招标文件.zip \
  --bid A=投标文件A.zip \
  --bid B=投标文件B.zip \
  --opinion-mode llm
```

默认情况下，只要启用 `--opinion-mode llm`，harness 会等待完整 LLM 审查链结束后再把任务视为完成。这也是本地慢模型场景下的推荐设置。如果你明确希望先写规则版产物、再让 LLM 增强后台继续运行，可设置 `AGENT_BID_RIGGING_ASYNC_LLM=1`。

启用 LLM 审查后，系统会同时保留规则版和增强版两套报告：

- `formal_report.rule.md`：确定性的规则/模板报告
- `formal_report.llm.md`：LLM 增强版报告，LLM 成功完成后写出
- `opinion.rule.md`：确定性的规则/模板意见
- `opinion.llm.md`：LLM 增强版意见，LLM 成功完成后写出
- `formal_report.md` 与 `opinion.md`：当前默认入口，指向当前可用的最佳版本

如果 `OPENAI_BASE_URL` 以 `/v1` 结尾，系统会自动追加 `/responses`。

OpenAI 集成遵循官方文档中的 Responses API 模式：

- [OpenAI Platform overview](https://platform.openai.com/docs/overview)
- [Responses API reference](https://platform.openai.com/docs/api-reference/responses/create?api-mode=responses)
- [Migrate to the Responses API](https://platform.openai.com/docs/guides/migrate-to-responses)

## 支持的输入

- 单文件：`.txt`、`.md`、`.json`、`.docx`、`.pdf`
- 包含嵌套支持文件的目录
- 包含嵌套支持文件的 `.zip` 压缩包

PDF 解析优先使用 `pdftotext`，缺失时自动回退到 `pypdf`。

## 当前范围

当前系统仍然是审查 harness，而不是最终法律裁定引擎。它输出的是有证据支撑的异常指标和供人工采购审查员使用的意见草稿。后续版本可以继续增强 OCR、更丰富的元数据抽取、基准数据集以及更强的多文档推理。
