from __future__ import annotations

from dataclasses import dataclass, field
import re

from agent_bid_rigging.capabilities.ocr import OcrRequest
from agent_bid_rigging.capabilities.ocr.contracts import OCR_MODE_TARGETED
from agent_bid_rigging.models import ExtractedSignals, PairwiseAssessment
from agent_bid_rigging.utils.openai_client import OpenAIResponsesClient

LICENSE_NUMBER_RE = re.compile(r"(?:许可证编号|经营许可证|许可证号)\s*[:：]?\s*([A-Za-z0-9\u4e00-\u9fff -]{4,40})")
REGISTRATION_NUMBER_RE = re.compile(r"(?:注册证编号|注册证号|备案凭证编号|备案编号)\s*[:：]?\s*([A-Za-z0-9\u4e00-\u9fff -]{4,40})")
MANUFACTURER_RE = re.compile(r"(?:制造商|生产厂家|厂家名称|授权厂家)\s*[:：]?\s*([^\n]{2,80})")


@dataclass(slots=True)
class OcrTaskPlan:
    role: str
    supplier: str | None
    enabled: bool
    request: OcrRequest | None = None
    reasons: list[str] = field(default_factory=list)


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
    bid_signals: list[ExtractedSignals] | None = None,
    preliminary_assessments: list[PairwiseAssessment] | None = None,
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
    explicit_report_requested = enable_ocr
    risk_suppliers = _medium_or_higher_suppliers(preliminary_assessments or [])
    tender_task = OcrTaskPlan(
        role="tender",
        supplier=None,
        enabled=enable_ocr and explicit_report_requested,
        request=build_review_ocr_request(role="tender") if enable_ocr and explicit_report_requested else None,
        reasons=["用户明确要求生成带 OCR 的正式报告"] if enable_ocr and explicit_report_requested else [],
    )
    signals_by_supplier = {signal.document.name: signal for signal in (bid_signals or [])}
    bid_tasks = {
        supplier: _build_bid_ocr_task(
            supplier=supplier,
            enable_ocr=enable_ocr,
            signal=signals_by_supplier.get(supplier),
            explicit_report_requested=explicit_report_requested,
            flagged_by_risk=supplier in risk_suppliers,
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
            file_hints=["采购需求", "技术参数", "注册证", "注册证相关", "参数"],
            max_sources=3,
            max_images=12,
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
        max_sources=4,
        max_images=20,
        metadata={"role": role, "supplier": supplier},
    )


def _ocr_task_to_dict(task: OcrTaskPlan) -> dict:
    return {
        "role": task.role,
        "supplier": task.supplier,
        "enabled": task.enabled,
        "request": task.request.to_dict() if task.request is not None else None,
        "reasons": list(task.reasons),
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


def _build_bid_ocr_task(
    *,
    supplier: str,
    enable_ocr: bool,
    signal: ExtractedSignals | None,
    explicit_report_requested: bool,
    flagged_by_risk: bool,
) -> OcrTaskPlan:
    reasons: list[str] = []
    if not enable_ocr:
        return OcrTaskPlan(role="bid", supplier=supplier, enabled=False, reasons=reasons)

    if signal is not None:
        reasons.extend(_missing_field_reasons(signal))
    if flagged_by_risk:
        reasons.append("案件初筛已达到 medium 及以上风险")
    if explicit_report_requested:
        reasons.append("用户明确要求生成带 OCR 的正式报告")

    enabled = bool(reasons)
    return OcrTaskPlan(
        role="bid",
        supplier=supplier,
        enabled=enabled,
        request=build_review_ocr_request(role="bid", supplier=supplier) if enabled else None,
        reasons=reasons,
    )


def _missing_field_reasons(signal: ExtractedSignals) -> list[str]:
    reasons: list[str] = []
    text = signal.document.text
    if not signal.bid_amounts:
        reasons.append("文本抽取未识别到投标总报价")
    if not signal.legal_representatives:
        reasons.append("文本抽取未识别到法定代表人")
    if not LICENSE_NUMBER_RE.search(text):
        reasons.append("文本抽取未识别到许可证号")
    if not REGISTRATION_NUMBER_RE.search(text):
        reasons.append("文本抽取未识别到注册证号/备案编号")
    if not MANUFACTURER_RE.search(text):
        reasons.append("文本抽取未识别到授权厂家/制造商")
    return reasons


def _medium_or_higher_suppliers(assessments: list[PairwiseAssessment]) -> set[str]:
    suppliers: set[str] = set()
    for assessment in assessments:
        if assessment.risk_level in {"medium", "high", "critical"}:
            suppliers.add(assessment.supplier_a)
            suppliers.add(assessment.supplier_b)
    return suppliers
