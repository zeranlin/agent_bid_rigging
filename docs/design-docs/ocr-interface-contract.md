# OCR 接口契约

## 定位

`capabilities/ocr` 是原子能力层。  
它不负责判断围串标风险。  
它只接收 OCR 请求，并返回结构化 OCR 事实。

## 请求对象

主对象：`OcrRequest`

字段：

- `mode`
  - `generic`：返回更通用的 OCR 结果
  - `targeted`：优先满足调用方指定的文档类型和字段
- `doc_types`
  - 调用方期望识别的文档类型，例如 `business_license`、`quotation`、`authorization_letter`
- `fields`
  - 调用方期望抽取的字段，例如 `company_name`、`bid_total_amount`、`license_number`
- `page_hints`
  - 为未来页级路由预留的页码提示
- `file_hints`
  - 用于缩小 OCR 范围的文件名或路径提示
- `max_sources`
  - 发现源文件数量的上限
- `max_images`
  - 提取图片数量的上限
- `confidence_threshold`
  - 为下游门控预留的置信度阈值
- `include_raw_text`
  - 调用方是否需要返回原始抽取文本
- `include_images`
  - 调用方是否需要响应中包含图片条目
- `include_debug_payload`
  - 是否保留额外调试载荷
- `metadata`
  - 自由扩展的调用方元数据

## 返回对象

主对象：`OcrResponse`

字段：

- `request`
- `source_path`
- `output_dir`
- `source_count`
- `image_count`
- `images`
- `image_results`
- `warnings`

这个响应停留在能力层，可被多个业务模块复用。

## 模式

### generic

用于调用方没有明确业务目标的场景。

预期行为：

- 发现可做 OCR 的输入
- 抽取图片
- 分类图像/文档类型
- 返回较广义的结构化字段
- 保留原始抽取文本

### targeted

用于调用方明确知道要什么的场景。

预期行为：

- 优先满足 `doc_types`
- 优先满足 `fields`
- 允许通过 `file_hints`、`max_sources`、`max_images` 收缩范围
- 如果图片与目标不相关，也要诚实返回实际 `doc_type` 和 `summary`

## 与审查主流程的关系

主审查流程只是 OCR 的调用方。

推荐分层：

1. `capabilities/ocr`
   - 接收 `OcrRequest`
   - 返回 `OcrResponse`
2. `fusion`
   - 合并 OCR 事实与文本抽取事实
   - 处理置信度、冲突与来源优先级
3. `core`
   - 基于统一事实进行围串标评分与判断
4. `llm_review`
   - 基于统一事实与已评分证据做解释和写作

这样可以把 OCR 隔离成独立能力，并复用于围串标之外的模块。
