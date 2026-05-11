"""Tools (skills) the agent can invoke. These are pure Python — no LLM calls."""

import ast
import os
import re
import subprocess
from typing import Optional


def run_tests(test_cmd: str, cwd: Optional[str] = None, timeout: int = 30) -> dict:
    """Run the test command and return a structured result."""
    try:
        result = subprocess.run(
            test_cmd,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {
            "passed": False,
            "returncode": -1,
            "stdout": "",
            "stderr": "",
            "error": "timeout",
            "parsed": None,
        }

    passed = result.returncode == 0
    return {
        "passed": passed,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "parsed": parse_pytest_output(result.stdout + "\n" + result.stderr) if not passed else None,
    }


def parse_pytest_output(output: str) -> dict:
    """Extract structured information from pytest output."""
    parsed: dict = {}

    failed_match = re.search(r"FAILED\s+(\S+)", output)
    if failed_match:
        parsed["failed_test"] = failed_match.group(1)

    error_match = re.search(r"ERROR\s+(\S+)", output)
    if error_match:
        parsed["error_test"] = error_match.group(1)

    e_lines = re.findall(r"^E\s+(.+)$", output, re.MULTILINE)
    if e_lines:
        parsed["error_lines"] = e_lines[:10]

    exception_match = re.search(r"^E\s+([A-Z]\w*Error|AssertionError|Exception):\s*(.*)$", output, re.MULTILINE)
    if exception_match:
        parsed["exception_type"] = exception_match.group(1)
        parsed["exception_message"] = exception_match.group(2).strip()

    assert_match = re.search(r"assert\s+(.+?)(?:\n|$)", output)
    if assert_match:
        parsed["assertion"] = assert_match.group(1).strip()

    tb_matches = re.findall(r"(\S+\.py):(\d+):", output)
    if tb_matches:
        parsed["traceback_locations"] = [
            {"file": f, "line": int(l)} for f, l in tb_matches
        ]

    parsed["raw_tail"] = output[-1500:]
    return parsed


def read_file(path: str, start: int = 1, end: Optional[int] = None) -> str:
    """Read a file (or slice) and return numbered lines as a string."""
    with open(path) as f:
        lines = f.readlines()
    if end is None:
        end = len(lines)
    selected = lines[start - 1 : end]
    return "".join(f"{i + start:4d}: {line}" for i, line in enumerate(selected))


def search_code(pattern: str, path: str) -> list:
    """Grep-style search inside a file. Returns list of (line_no, line)."""
    matches = []
    try:
        matcher = re.compile(pattern)
    except re.error:
        matcher = re.compile(re.escape(pattern))

    with open(path) as f:
        for i, line in enumerate(f, start=1):
            if matcher.search(line):
                matches.append((i, line.rstrip()))
    return matches


def apply_patch(path: str, old: str, new: str) -> dict:
    """Apply a string-replace patch. Returns a record that can be reverted."""
    with open(path) as f:
        content = f.read()

    if old not in content:
        return {"success": False, "error": f"old string not found in {path}"}
    if content.count(old) > 1:
        return {"success": False, "error": f"old string is not unique in {path}"}

    new_content = content.replace(old, new, 1)
    with open(path, "w") as f:
        f.write(new_content)

    return {
        "success": True,
        "path": path,
        "original_content": content,
        "old": old,
        "new": new,
    }


def revert_patch(patch_record: dict) -> dict:
    """Restore a file from a patch record's saved original content."""
    if not patch_record.get("success"):
        return {"success": False, "error": "cannot revert failed patch"}
    with open(patch_record["path"], "w") as f:
        f.write(patch_record["original_content"])
    return {"success": True}


def run_snippet(code: str, cwd: Optional[str] = None, timeout: int = 10) -> dict:
    """Execute a small Python snippet via `python -c` and capture its output."""
    try:
        result = subprocess.run(
            ["python3", "-c", code],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "stdout": "", "stderr": "", "error": "timeout"}


def lint(path: str) -> dict:
    """Check a Python file for syntax errors using `ast.parse`."""
    with open(path) as f:
        source = f.read()
    try:
        ast.parse(source, filename=path)
        return {"clean": True}
    except SyntaxError as e:
        return {
            "clean": False,
            "error": str(e),
            "line": e.lineno,
            "offset": e.offset,
        }


_TB_FRAME_RE = re.compile(r'File "([^"]+)", line (\d+), in (\S+)')


def get_traceback_frames(traceback_str: str) -> list:
    """Parse a Python traceback into structured frames."""
    frames = []
    for m in _TB_FRAME_RE.finditer(traceback_str or ""):
        frames.append({
            "file": m.group(1),
            "line": int(m.group(2)),
            "function": m.group(3),
        })
    return frames
