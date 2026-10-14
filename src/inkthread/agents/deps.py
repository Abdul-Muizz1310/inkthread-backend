"""What every agent stage needs (ports and configuration) and what it reports back."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from inkthread.core.config import LlmMode
from inkthread.llm.ports import AnswerStore, CallLog, ModelPort

SkipReason = Literal["budget", "replay_miss", "disabled", "model_unavailable", "invalid_answer"]


@dataclass(frozen=True)
class AgentDeps:
    """Ports plus configuration for the agent stages.

    `temperature` overrides the prompt file's when set; `max_tokens` caps the prompt file's.
    """

    model: ModelPort
    store: AnswerStore
    log: CallLog
    mode: LlmMode
    producer_cascade: tuple[str, ...]
    verifier_cascade: tuple[str, ...]
    temperature: float | None = None
    max_tokens: int = 6000

    def __post_init__(self) -> None:
        if not self.producer_cascade or not self.verifier_cascade:
            msg = "both cascades need at least one model"
            raise ValueError(msg)
        if self.producer_cascade[0] == self.verifier_cascade[0]:
            msg = "the verifier's first model must differ from the producer's"
            raise ValueError(msg)


@dataclass(frozen=True)
class AgentReport:
    """What a stage did: HTTP attempts, recorded hits, claims kept and refused, and why it stopped.

    `skipped_reason` is the first batch-level abstention (None when every batch was answered).
    """

    calls: int = 0
    cached: int = 0
    accepted: int = 0
    rejected: int = 0
    skipped_reason: SkipReason | None = None


@dataclass
class Tally:
    """A stage's running counts, frozen into an `AgentReport` at the end."""

    calls: int = 0
    cached: int = 0
    accepted: int = 0
    rejected: int = 0
    skipped: SkipReason | None = None

    def report(self) -> AgentReport:
        """The stage's report."""
        return AgentReport(self.calls, self.cached, self.accepted, self.rejected, self.skipped)
