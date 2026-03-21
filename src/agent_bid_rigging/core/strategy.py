from __future__ import annotations

from dataclasses import dataclass, field

from agent_bid_rigging.capabilities.ocr import OcrRequest
from agent_bid_rigging.capabilities.ocr.contracts import OCR_MODE_TARGETED
from agent_bid_rigging.utils.openai_client import OpenAIResponsesClient


@dataclass(slots=True)
class OcrTaskPlan:
    role: str
    supplier: str | None
    enabled: bool
    request: OcrRequest | None = None


@dataclass(slots=True)
class LlmPlan:
    requested_mode: str
    enabled: bool
    async_enabled: bool
    wait_for_completion: bool


@dataclass(slots=True)
class ReviewStrategy:
    opinion_mode: str
    enable_ocr: bool
    tender_ocr: OcrTaskPlan
    bid_ocr: dict[str, OcrTaskPlan] = field(default_factory=dict)
    llm: LlmPlan | None = None

    def to_dict(self) -> dict:
        return {
            "opinion_mode": self.opinion_mode,
            "enable_ocr": self.enable_ocr,
            "tender_ocr": _ocr_task_to_dict(self.tender_ocr),
            "bid_ocr": {key: _ocr_task_to_dict(value) for key, value in self.bid_ocr.items()},
            "llm": _llm_plan_to_dict(self.llm),
        }


def build_review_strategy(
    *,
    opinion_mode: str,
    enable_ocr: bool,
    suppliers: list[str],
    openai_configured: bool | None = None,
    async_llm: bool = False,
) -> ReviewStrategy:
    configured = OpenAIResponsesClient.is_configured() if openai_configured is None else openai_configured
    llm_enabled = opinion_mode == "llm" or (opinion_mode == "auto" and configured)
    llm_plan = LlmPlan(
        requested_mode=opinion_mode,
        enabled=llm_enabled,
        async_enabled=llm_enabled and async_llm,
        wait_for_completion=llm_enabled and not async_llm,
    )
    tender_task = OcrTaskPlan(
        role="tender",
        supplier=None,
        enabled=enable_ocr,
        request=build_review_ocr_request(role="tender") if enable_ocr else None,
    )
    bid_tasks = {
        supplier: OcrTaskPlan(
            role="bid",
            supplier=supplier,
            enabled=enable_ocr,
            request=build_review_ocr_request(role="bid", supplier=supplier) if enable_ocr else None,
        )
        for supplier in suppliers
    }
    return ReviewStrategy(
        opinion_mode=opinion_mode,
        enable_ocr=enable_ocr,
        tender_ocr=tender_task,
        bid_ocr=bid_tasks,
        llm=llm_plan,
    )


def build_review_ocr_request(role: str, supplier: str | None = None) -> OcrRequest:
    if role == "tender":
        return OcrRequest(
            mode=OCR_MODE_TARGETED,
            doc_types=["quotation", "registration_certificate", "license"],
            fields=["manufacturer", "brand", "model", "registration_number", "license_number"],
            file_hints=["招标文件", "采购需求", "技术参数", "货物需求", "参数"],
            max_sources=6,
            max_images=24,
            metadata={"role": role},
        )

    return OcrRequest(
        mode=OCR_MODE_TARGETED,
        doc_types=[
            "quotation",
            "business_license",
            "authorization_letter",
            "registration_certificate",
            "license",
            "identity_document",
        ],
        fields=[
            "company_name",
            "legal_representative",
            "bid_total_amount",
            "license_number",
            "registration_number",
            "manufacturer",
            "brand",
            "model",
            "address",
            "phone",
        ],
        file_hints=[
            "开标一览表",
            "分项报价表",
            "报价表",
            "投标人基本情况表",
            "投标人(供应商)应提交的相关证明",
            "投标人（供应商）应提交的相关证明",
            "授权委托书",
            "授权书",
            "营业执照",
            "经营许可证",
            "注册证",
            "备案凭证",
            "身份证明",
        ],
        max_sources=12,
        max_images=48,
        metadata={"role": role, "supplier": supplier},
    )


def _ocr_task_to_dict(task: OcrTaskPlan) -> dict:
    return {
        "role": task.role,
        "supplier": task.supplier,
        "enabled": task.enabled,
        "request": task.request.to_dict() if task.request is not None else None,
    }


def _llm_plan_to_dict(plan: LlmPlan | None) -> dict | None:
    if plan is None:
        return None
    return {
        "requested_mode": plan.requested_mode,
        "enabled": plan.enabled,
        "async_enabled": plan.async_enabled,
        "wait_for_completion": plan.wait_for_completion,
    }
