from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class CapabilityContext:
    run_id: str | None = None
    source_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CapabilityResult:
    capability: str
    backend: str
    status: str
    payload: dict[str, Any] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ReviewCapability(ABC):
    name: str

    @abstractmethod
    def run(self, context: CapabilityContext, **kwargs: Any) -> CapabilityResult:
        """Execute the atomic capability and return a structured result."""
