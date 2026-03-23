# SOP 阶段计划

## 目标

让 `agent_bid_rigging` 与 `sop.md` 里定义的执行纪律对齐，同时避免把项目做成一堆一次性脚本。

## 阶段划分

### 第一阶段：可审计的中间产物

先交付稳定的案件登记与结构化审查表：

- `case_manifest.json`
- `source_file_index.json`
- `extracted_file_index.json`
- `document_catalog.json`
- `entity_field_table.json`
- `price_analysis_table.json`
- `review_conclusion_table.json`

这一阶段重点是可追溯、可复现和明确的证据边界。

### 第二阶段：专项分析链

补齐以下分析表：

- `structure_similarity_table`
- `file_fingerprint_table`
- `duplicate_detection_table`
- `text_similarity_table`
- `shared_error_table`
- `authorization_chain_table`
- `license_match_table`
- `timeline_table`

### 第三阶段：证据分级与正式 SOP 报告

补齐：

- `evidence_grade_table`
- `risk_score_table`
- 与 SOP 对齐的正式报告结构

## 当前决策

先从第一阶段开始，因为它能先把审查可追溯性立起来，并为后续所有模块建立稳定的存储契约。
