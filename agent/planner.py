"""Symbolic planner. Decides the next action based on state.

This module contains NO LLM calls. Control flow lives here, deliberately,
so that the agent's decision-making is inspectable Python rather than
hidden inside an LLM prompt."""

from .state import AgentState, Hypothesis, HypothesisStatus

CONFIDENCE_THRESHOLD = 0.7
MAX_REGENERATIONS = 2

# Score adjustment rules — keyed by event type for transparency.
SCORE_DELTAS = {
    "probe_confirmed": +2.0,
    "probe_refuted": -3.0,
    "probe_inconclusive": +0.3,
    "patch_did_nothing": -5.0,
    "patch_changed_signal": -2.0,
    "patch_proposal_failed": -1.0,
}

RULED_OUT_THRESHOLD = -1.0
FAILED_THRESHOLD = -3.0


def plan_next_action(state: AgentState) -> dict:
    """Decide the next action. Pure function over state."""

    # Rule 1: no hypotheses yet -> generate.
    if not state.hypotheses:
        return {"type": "generate_hypotheses"}

    open_hyps = state.open_hypotheses()

    # Rule 2: no open hypotheses -> regenerate or give up.
    if not open_hyps:
        if state.regenerations < MAX_REGENERATIONS:
            return {"type": "generate_hypotheses", "exclude": list(state.ruled_out)}
        return {"type": "give_up", "reason": "all hypotheses exhausted"}

    # Rule 3: pick the highest-scoring open hypothesis.
    top = max(open_hyps, key=lambda h: h.score)

    # Rule 4: confidence above threshold -> propose a patch.
    if top.score >= CONFIDENCE_THRESHOLD:
        return {"type": "propose_patch", "hypothesis": top}

    # Rule 5: otherwise, investigate it with a probe.
    return {"type": "investigate", "hypothesis": top}


def update_score(hypothesis: Hypothesis, event: str) -> None:
    """Apply a fixed score delta and update status if thresholds are crossed."""
    delta = SCORE_DELTAS.get(event, 0.0)
    hypothesis.score += delta

    if event == "patch_did_nothing":
        hypothesis.status = HypothesisStatus.FAILED
    elif hypothesis.score <= FAILED_THRESHOLD:
        hypothesis.status = HypothesisStatus.FAILED
    elif hypothesis.score <= RULED_OUT_THRESHOLD:
        hypothesis.status = HypothesisStatus.RULED_OUT
