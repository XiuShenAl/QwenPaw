# -*- coding: utf-8 -*-
"""Contract test: no bare asyncio.wait_for in tool files.

Scans src/qwenpaw/agents/tools/*.py for asyncio.wait_for usage.
Remaining occurrences should only be in the whitelist (cleanup code).
"""
import re
from pathlib import Path

TOOLS_DIR = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "qwenpaw"
    / "agents"
    / "tools"
)

# Whitelist: (filename, line_number) pairs for known-intentional usages.
# These are cleanup/polling code, not main tool timeouts.
_WAIT_FOR_RE = re.compile(r"asyncio\.wait_for\s*\(")


def _build_whitelist():
    """Dynamically find cleanup wait_for calls to whitelist.

    Whitelisted patterns:
    - shell.py: proc.wait()/proc.communicate() after TimeoutError (cleanup)
    - delegate_external_agent.py: response_queue.get() polling
    """
    whitelist = set()

    shell_path = TOOLS_DIR / "shell.py"
    if shell_path.exists():
        lines = shell_path.read_text().splitlines()
        for i, line in enumerate(lines, 1):
            if _WAIT_FOR_RE.search(line):
                # Check next 3 lines for cleanup patterns
                context = "\n".join(lines[i - 1 : i + 3])
                if any(
                    p in context for p in ("proc.wait()", "proc.communicate()")
                ):
                    # Check if this is NOT the main communicate call
                    # (main one uses cancellable_wait now)
                    if "cancellable_wait" not in line:
                        whitelist.add(("shell.py", i))

    delegate_path = TOOLS_DIR / "delegate_external_agent.py"
    if delegate_path.exists():
        lines = delegate_path.read_text().splitlines()
        for i, line in enumerate(lines, 1):
            if _WAIT_FOR_RE.search(line):
                context = "\n".join(lines[i - 1 : i + 3])
                if "response_queue.get()" in context:
                    whitelist.add(("delegate_external_agent.py", i))

    return whitelist


def test_no_naked_asyncio_wait_for():
    whitelist = _build_whitelist()
    violations = []
    for py_file in sorted(TOOLS_DIR.glob("*.py")):
        for lineno, line in enumerate(py_file.read_text().splitlines(), 1):
            if _WAIT_FOR_RE.search(line):
                if (py_file.name, lineno) in whitelist:
                    continue
                violations.append(
                    f"{py_file.name}:{lineno}: {line.strip()}",
                )

    assert not violations, (
        f"Found {len(violations)} bare asyncio.wait_for call(s) "
        f"that should use cancellable_wait:\n"
        + "\n".join(f"  {v}" for v in violations)
    )
