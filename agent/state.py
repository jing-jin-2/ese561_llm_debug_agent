"""State and data classes for the debugging agent."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class HypothesisStatus(str, Enum):
    OPEN = "open"
    CONFIRMED = "confirmed"
    RULED_OUT = "ruled_out"
    FAILED = "failed"


@dataclass
class Hypothesis:
    id: int
    description: str
    suspected_location: Optional[str] = None
    score: float = 0.0
    status: HypothesisStatus = HypothesisStatus.OPEN

    def is_open(self) -> bool:
        return self.status == HypothesisStatus.OPEN


@dataclass
class AgentState:
    target_file: str
    test_cmd: str
    traceback: Optional[dict] = None
    hypotheses: list = field(default_factory=list)
    ruled_out: list = field(default_factory=list)
    patches_tried: list = field(default_factory=list)
    history: list = field(default_factory=list)
    iteration: int = 0
    regenerations: int = 0
    done: bool = False
    final_status: Optional[str] = None
    next_hypothesis_id: int = 0

    def open_hypotheses(self) -> list:
        return [h for h in self.hypotheses if h.is_open()]

    def log(self, entry_type: str, **fields) -> None:
        self.history.append({
            "iteration": self.iteration,
            "type": entry_type,
            **fields,
        })
