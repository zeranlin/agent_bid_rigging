OCR_SYSTEM_PROMPT = """你是政府采购审查场景下的 OCR 与图片信息抽取助手。

你的任务不是判断围串标，而是忠实描述图片内容，并提取对后续审查有用的结构化信息。

要求：
1. 只根据图片内容回答，不要臆测看不清的内容。
2. 优先识别图片类型，例如：营业执照、身份证明、授权书、报价表、注册证、许可证、签章页、其他。
3. 输出必须是 JSON 对象，不要使用 Markdown 代码块。
4. 如果某项识别不出来，使用空字符串、空对象或 null。
5. extracted_text 尽量保留图片中的原文关键信息。
6. fields 里只保留对审查有价值的字段，例如 company_name、legal_representative、bid_total_amount、license_number、registration_number、brand、model、manufacturer、address、phone。
"""


def build_ocr_user_prompt(source_label: str, page_index: int | None, image_index: int) -> str:
    page_text = f"第 {page_index} 页" if page_index is not None else "无页码信息"
    return f"""请识别这张图片中的信息。

来源文件：{source_label}
页码：{page_text}
图片序号：{image_index}

请严格输出如下 JSON 结构：
{{
  "doc_type": "图片类型",
  "summary": "对图片主要内容的简短描述",
  "extracted_text": "尽量忠实提取的关键信息原文",
  "fields": {{
    "company_name": "",
    "legal_representative": "",
    "bid_total_amount": "",
    "license_number": "",
    "registration_number": "",
    "manufacturer": "",
    "brand": "",
    "model": "",
    "address": "",
    "phone": ""
  }},
  "confidence": 0.0
}}
"""
