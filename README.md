# llm_debug_agent

A hypothesis-driven LLM debugging agent. Give it a buggy Python file and a failing pytest command, and it iteratively localizes the bug and patches it.

The LLM proposes hypotheses and patches; a deterministic Python planner decides what to do next. Wrong hypotheses are scored down by fixed rules, so the agent doesn't loop on the same plausible-but-wrong fix.

## Installation

```bash
pip install -r requirements.txt
```
To use Ollama locally (no API key required):

```bash
ollama pull qwen2.5-coder:7b
```

## Usage

```bash
python3 main.py \
    --file examples/wrong_operator.py \
    --test "pytest examples/test_wrong_operator.py -x"
```

Flags:

- `--file` — path to the buggy Python file (required)
- `--test` — shell command that runs the failing test (required)
- `--max-iter` — iteration cap (default: 15)
- `--model` — model ID (default: `qwen2.5-coder:7b`)
- `--quiet` — suppress per-iteration logging
- `--trace-out` — write the full run as JSON to this path

Exit code is 0 if the bug was fixed, 1 otherwise.

## Examples

Four sample bugs ship in `examples/`:

```bash
python3 main.py --file examples/wrong_operator.py    --test "pytest examples/test_wrong_operator.py -x"
python3 main.py --file examples/off_by_one.py        --test "pytest examples/test_off_by_one.py -x"
python3 main.py --file examples/wrong_condition.py   --test "pytest examples/test_wrong_condition.py -x"
python3 main.py --file examples/missing_edge_case.py --test "pytest examples/test_missing_edge_case.py -x"

# Ollama example
python3 main.py --model qwen2.5-coder:7b --file examples/wrong_operator.py \
  --test "pytest examples/test_wrong_operator.py -x"
```

## Project Layout

```
agent/
  state.py     # AgentState, Hypothesis, HypothesisStatus
  planner.py   # Symbolic planner (no LLM calls)
  tools.py     # run_tests, read_file, apply_patch, ...
  llm.py       # generate_hypotheses, pick_investigation, propose_patch
  loop.py      # Main agent loop
main.py        # CLI entry point
examples/      # Buggy samples and tests
```

## Documentation

- [DESIGN.md](DESIGN.md) — full architecture, every functional unit, scoring rules, execution flow
- [report.pdf](report.pdf) — final project report (motivation, method, design choices)

## Requirements

- Python 3.9+
- `pytest` (see `requirements.txt`)
