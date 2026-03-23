# SOP 第二阶段计划

## 目标

实现 SOP 要求的专项分析链：

- 结构相似性
- 文件指纹与重复检测
- 文本相似
- 共同错误检测
- 授权与资质摘要
- 时间线抽取

## 交付物

- `structure_similarity_table.json`
- `file_fingerprint_table.json`
- `duplicate_detection_table.json`
- `text_similarity_table.json`
- `shared_error_table.json`
- `authorization_chain_table.json`
- `license_match_table.json`
- `timeline_table.json`

## 退出标准

- 每次运行都产出第二阶段表
- 测试验证表存在，并在应有场景下包含非空行
- 不回归第一阶段输出
