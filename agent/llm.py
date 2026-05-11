"""LLM interface. The LLM is treated as a constrained reasoning engine —
it generates hypotheses, designs probes, and proposes patches, but never
controls the agent loop. Control flow lives in the planner."""

import json
import os
import urllib.error
import urllib.request
from typing import Optional

DEFAULT_OLLAMA_MODEL = "qwen2.5-coder:7b"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"


class LLMClient:
    def __init__(
        self,
        model: str = DEFAULT_OLLAMA_MODEL,
        base_url: Optional[str] = None,
    ):
        self.model = model
        self.call_count = 0
        self.base_url = base_url or os.environ.get("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL)

    def call(self, system: str, user: str, max_tokens: int = 1024) -> str:
        self.call_count += 1
        prompt = f"{system}\n\n{user}"
        payload = json.dumps({
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }).encode("utf-8")
        url = f"{self.base_url}/api/generate"
        request = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8")
            raise RuntimeError(f"Ollama request failed: {detail}") from exc
        return data.get("response", "")


def parse_json(text: str, key: Optional[str] = None):
    """Extract JSON from an LLM response, tolerating markdown code fences."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[-1].strip().startswith("```"):
            lines = lines[1:-1]
        else:
            lines = lines[1:]
        text = "\n".join(lines)

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object found in response: {text[:200]}")
    data = json.loads(text[start : end + 1])
    if key is not None:
        return data.get(key, [])
    return data


def generate_hypotheses(llm: LLMClient, state, file_content: str) -> list:
    """Ask the LLM to produce a ranked list of hypotheses about the bug."""
    system = (
        "You are a code debugging assistant. Given a buggy Python file and "
        "a failing test, generate a ranked list of hypotheses about what is wrong. "
        "Each hypothesis must be specific and testable.\n\n"
        "Output strictly as JSON in this shape:\n"
        "{\n"
        '  "hypotheses": [\n'
        "    {\n"
        '      "description": "concrete claim about what is wrong",\n'
        '      "suspected_location": "file.py:line",\n'
        '      "initial_confidence": 0.0\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "initial_confidence is a number between 0 and 1. Output JSON only — no prose."
    )

    excluded_text = ""
    if state.ruled_out:
        excluded_text = "\n\nThese hypotheses have already been ruled out — DO NOT repeat them:\n"
        excluded_text += "\n".join(f"- {h}" for h in state.ruled_out)

    tb = state.traceback or {}
    user = (
        f"Target file: {state.target_file}\n\n"
        f"File content:\n{file_content}\n\n"
        f"Failing test output (parsed):\n{json.dumps(tb, indent=2)}\n"
        f"{excluded_text}\n\n"
        f"Generate 3-5 specific hypotheses ranked by likelihood. Output JSON only."
    )

    response = llm.call(system, user, max_tokens=1500)
    return parse_json(response, "hypotheses")


INVESTIGATION_TOOLS = ("search_code", "run_snippet", "get_traceback_frames")


def pick_investigation(llm: LLMClient, state, hypothesis, file_content: str) -> dict:
    """Ask the LLM to pick one tool from a fixed menu to investigate a hypothesis.

    The LLM may not invent new tools — anything outside the menu is rejected and
    falls back to a safe default. This is the proposal's "constrained menu" rule."""
    system = (
        "You are debugging Python code. Pick exactly ONE investigation tool from "
        "the menu below and provide its inputs. You may not invent new tools.\n\n"
        "Menu:\n"
        '  - "search_code"          inputs: {"pattern": "<regex>"}\n'
        '  - "run_snippet"          inputs: {"snippet": "<python -c code>"}\n'
        '  - "get_traceback_frames" inputs: {}\n\n'
        "For run_snippet, also provide expected substrings so the planner can score "
        "the probe.\n\n"
        "Output strictly as JSON:\n"
        "{\n"
        '  "tool": "search_code" | "run_snippet" | "get_traceback_frames",\n'
        '  "inputs": { ... },\n'
        '  "expected_if_true": "substring that confirms the hypothesis (run_snippet only, else \\"\\")",\n'
        '  "expected_if_false": "substring that refutes the hypothesis (run_snippet only, else \\"\\")"\n'
        "}\n\n"
        "Output JSON only — no prose."
    )

    user = (
        f"File: {state.target_file}\n\n"
        f"Content:\n{file_content}\n\n"
        f"Hypothesis: {hypothesis.description}\n"
        f"Suspected location: {hypothesis.suspected_location}\n\n"
        f"Pick one tool. Output JSON only."
    )

    response = llm.call(system, user, max_tokens=600)
    data = parse_json(response)

    if data.get("tool") not in INVESTIGATION_TOOLS:
        data = {
            "tool": "search_code",
            "inputs": {"pattern": (hypothesis.suspected_location or "return")},
            "expected_if_true": "",
            "expected_if_false": "",
        }
    data.setdefault("inputs", {})
    data.setdefault("expected_if_true", "")
    data.setdefault("expected_if_false", "")
    return data


def propose_patch(llm: LLMClient, state, hypothesis, file_content: str) -> dict:
    """Ask the LLM for a minimal string-replace patch to fix the bug."""
    system = (
        "You are a code debugging assistant. Given a hypothesis about a bug, "
        "propose a minimal patch as a string replacement.\n\n"
        "Output strictly as JSON:\n"
        "{\n"
        '  "old": "exact string to replace — must appear EXACTLY ONCE in the file",\n'
        '  "new": "replacement string",\n'
        '  "rationale": "one sentence explaining why this fixes the bug"\n'
        "}\n\n"
        "The `old` string must be precise enough to be unique in the file. "
        "Include surrounding context if needed. Do NOT modify test code. "
        "Output JSON only — no prose."
    )

    user = (
        f"File: {state.target_file}\n\n"
        f"Content:\n{file_content}\n\n"
        f"Hypothesis: {hypothesis.description}\n"
        f"Suspected location: {hypothesis.suspected_location}\n\n"
        f"Propose a minimal patch. Output JSON only."
    )

    response = llm.call(system, user, max_tokens=1000)
    return parse_json(response)
