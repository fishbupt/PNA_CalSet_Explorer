from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import numpy as np


@dataclass
class ComplexSeries:
    name: str
    frequency_hz: np.ndarray = field(default_factory=lambda: np.array([], dtype=float))
    data: np.ndarray = field(default_factory=lambda: np.array([], dtype=np.complex128))
    raw_name: str | None = None
    read_errors: list[str] = field(default_factory=list)

    @property
    def point_count(self) -> int:
        return int(self.data.size)

    @property
    def start_hz(self) -> float | None:
        return float(self.frequency_hz[0]) if self.frequency_hz.size else None

    @property
    def stop_hz(self) -> float | None:
        return float(self.frequency_hz[-1]) if self.frequency_hz.size else None


@dataclass
class QueryRecord:
    command: str
    ok: bool
    response: Any = None
    error: str | None = None


@dataclass
class CalSetSnapshot:
    name: str
    info: dict[str, Any] = field(default_factory=dict)
    properties: dict[str, Any] = field(default_factory=dict)
    items: dict[str, Any] = field(default_factory=dict)
    standards: list[ComplexSeries] = field(default_factory=list)
    error_terms: list[ComplexSeries] = field(default_factory=list)
    audit: list[QueryRecord] = field(default_factory=list)
