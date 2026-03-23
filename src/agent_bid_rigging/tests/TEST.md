# 测试计划

## 测试清单规划

- `test_core.py`：规划中的单元测试
- `test_full_e2e.py`：规划中的端到端测试

## 单元测试计划

- `utils/file_loader.py`
  - 测试纯文本加载与标准化
  - 测试 zip 压缩包加载与聚合
  - 边界情况：不支持的后缀
- `core/extractor.py`
  - 抽取电话、邮箱、价格以及模板过滤后的行
  - 边界情况：没有价格
- `core/scoring.py`
  - 基于标识重合和文本线索进行两两评分
  - 边界情况：无重合的低风险组合、签章页噪声
- `core/opinion.py`
  - 基于结构化报告生成确定性审查意见
  - 边界情况：高风险组合必须在结论里被点名
- `core/artifacts.py`
  - 已知文档类型分类与结构化产物生成
  - 边界情况：未知/已知标签、重复 hash 检测、证据分级和最终报告渲染

## 端到端测试计划

- 用已安装 CLI 或模块方式运行示例招标与投标文件
- 直接对 zip 压缩包运行 CLI
- 校验 JSON 与报告输出结构
- 校验运行目录内的产物是否齐全

## 真实工作流场景

- 工作流名称：基础围串标筛查
  - 模拟：1 份招标、3 份投标，其中两家共享可疑标识
  - 操作链：加载招标、加载投标、抽取、比较、评分、写出产物
  - 验证点：两两风险排序与运行产物文件

- 工作流名称：干净样本对比
  - 模拟：两家供应商数据不同、重合很少
  - 操作链：同上
  - 验证点：结果为 low 或 medium，不出现误判 critical

- 工作流名称：压缩包审查
  - 模拟：1 个招标 zip + 多个投标 zip，内部包含嵌套文本组件
  - 操作链：解压、聚合、抽取、比较、写出产物
  - 验证点：zip 输入支持与产物生成

## 测试结果

```text
============================= test session starts ==============================
platform darwin -- Python 3.11.9, pytest-9.0.2, pluggy-1.6.0 -- /Library/Frameworks/Python.framework/Versions/3.11/bin/python3
cachedir: .pytest_cache
rootdir: /Users/linzeran/code/2026-zn/agent_bid_rigging
configfile: pyproject.toml
testpaths: src/agent_bid_rigging/tests
plugins: anyio-4.8.0
collecting ... collected 11 items

src/agent_bid_rigging/tests/test_core.py::test_load_plain_text_document PASSED
src/agent_bid_rigging/tests/test_core.py::test_unsupported_suffix_raises PASSED
src/agent_bid_rigging/tests/test_core.py::test_load_zip_archive_with_multiple_documents PASSED
src/agent_bid_rigging/tests/test_core.py::test_extract_signals_filters_tender_template PASSED
src/agent_bid_rigging/tests/test_core.py::test_pairwise_scoring_finds_shared_signals PASSED
src/agent_bid_rigging/tests/test_core.py::test_pairwise_scoring_can_stay_low PASSED
src/agent_bid_rigging/tests/test_core.py::test_signature_noise_does_not_create_high_risk PASSED
src/agent_bid_rigging/tests/test_core.py::test_template_opinion_mentions_high_risk_pair PASSED
src/agent_bid_rigging/tests/test_full_e2e.py::TestCLIEndToEnd::test_help PASSED
src/agent_bid_rigging/tests/test_full_e2e.py::TestCLIEndToEnd::test_analyze_generates_artifacts PASSED
src/agent_bid_rigging/tests/test_full_e2e.py::TestCLIEndToEnd::test_analyze_accepts_zip_archives PASSED

============================== 11 passed in 0.48s ===============================
```

## 汇总统计

- 测试总数：11
- 通过率：100%
- 执行时间：0.48s

## 覆盖说明

- 已覆盖：纯文本加载、zip 压缩包加载、抽取、评分、签章噪声过滤、意见草拟、CLI help、端到端产物生成、zip 输入 CLI 流程
- 尚未覆盖：`.docx` 解析回归、`pdftotext` 分支显式校验、异常采购表格、OCR/扫描件
