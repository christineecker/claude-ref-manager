"""Run named functions from the dashboard's scripts under node.

app.js and insights.js each keep their code in one closure, so tests lift
the functions they need out by name (`function name(` ... the closing `}`
at the same indent) plus any `var` constants, prepend stubs for the closure
state those functions read (KNOW, ins, ctx, ...), and print a JSON result.
Callers skip when node is absent.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[1] / "dashboard_assets"
SCRIPTS = [ASSETS / "insights.js", ASSETS / "app.js"]


def node() -> str | None:
    return shutil.which("node")


def require_node(test) -> None:
    """Skip `test` when node is missing -- unless REF_REQUIRE_NODE is set
    (CI sets it), where a missing node must fail, not silently skip."""
    if node():
        return
    if os.environ.get("REF_REQUIRE_NODE"):
        test.fail("node not installed but REF_REQUIRE_NODE is set")
    test.skipTest("node not installed")


def extract(names: list[str], variables: list[str] = ()) -> str:
    src = "\n".join(p.read_text(encoding="utf-8") for p in SCRIPTS)
    parts = []
    for v in variables:
        m = re.search(r"\n( +)var " + re.escape(v) + r"\b.*?;\n", src, re.S)
        if not m:
            raise LookupError(f"var {v} not found in the dashboard scripts")
        parts.append(m.group(0).strip())
    for name in names:
        m = re.search(r"\n( +)function " + re.escape(name) + r"\(.*?\n\1\}\n", src, re.S)
        if not m:
            raise LookupError(f"function {name} not found in the dashboard scripts")
        parts.append(m.group(0).strip())
    return "\n".join(parts)


def run(names: list[str], prelude: str, body: str, *, variables: list[str] = (), stdin=None):
    """`prelude` defines the stubbed closure state; `body` must end by
    assigning the value to print to `result`."""
    script = prelude + "\n" + extract(names, variables) + "\nvar result;\n" + body + \
        "\nprocess.stdout.write(JSON.stringify(result));\n"
    proc = subprocess.run([node(), "-e", script], input=json.dumps(stdin) if stdin is not None else "",
                          capture_output=True, text=True)
    if proc.returncode:
        raise AssertionError(proc.stderr)
    return json.loads(proc.stdout)
