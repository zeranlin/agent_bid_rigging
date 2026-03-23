# AGENTS.md

本仓库按 agent-first 方式设计。请把这份文件当作地图，而不是百科全书。

## 从这里开始

1. 阅读 [ARCHITECTURE.md](https://github.com/zeranlin/agent_bid_rigging/blob/main/ARCHITECTURE.md)，了解系统分层和审查主循环。
2. 阅读 [docs/design-docs/index.md](https://github.com/zeranlin/agent_bid_rigging/blob/main/docs/design-docs/index.md)，了解设计意图。
3. 查看 [docs/exec-plans/active/bootstrap-harness.md](https://github.com/zeranlin/agent_bid_rigging/blob/main/docs/exec-plans/active/bootstrap-harness.md)，了解当前活动计划。
4. 为保证结果可复现，请把运行产物写入 `runs/`。

## 工作规则

- 优先扩展现有模块，不要平行造新实现。
- 保留审查可追溯性：每个怀疑分值都必须有证据文本支撑。
- 保持人类可读输出与机器可读输出一致。
- 不要隐藏解析失败，应在运行清单中显式暴露。
- 新增检查项时，同步更新文档和测试。
- 把 `.zip` 压缩包和解压后的投标目录视为一等输入，而不是边界情况。
- 新的设计文档默认使用中文编写，除非有特殊原因。

## 关键代码路径

- `src/agent_bid_rigging/cli.py`：CLI 入口与 REPL
- `src/agent_bid_rigging/capabilities/`：可复用的原子能力，如 OCR、元数据提取
- `src/agent_bid_rigging/core/runner.py`：端到端运行编排
- `src/agent_bid_rigging/core/extractor.py`：信号抽取
- `src/agent_bid_rigging/core/opinion.py`：审查意见生成
- `src/agent_bid_rigging/core/scoring.py`：两两风险评分
- `src/agent_bid_rigging/utils/openai_client.py`：OpenAI Responses API 适配器
- `src/agent_bid_rigging/utils/file_loader.py`：文档后端选择

## 文档入口

- 架构说明：[ARCHITECTURE.md](https://github.com/zeranlin/agent_bid_rigging/blob/main/ARCHITECTURE.md)
- 设计文档：[docs/design-docs/index.md](https://github.com/zeranlin/agent_bid_rigging/blob/main/docs/design-docs/index.md)
- 计划索引：[docs/PLANS.md](https://github.com/zeranlin/agent_bid_rigging/blob/main/docs/PLANS.md)
- 测试计划：[src/agent_bid_rigging/tests/TEST.md](https://github.com/zeranlin/agent_bid_rigging/blob/main/src/agent_bid_rigging/tests/TEST.md)
