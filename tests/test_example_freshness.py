from __future__ import annotations
from pathlib import Path 
import pytest 

_REPO = Path(__file__).resolve().parents[1]
_EXAMPLES = _REPO / "examples"

# Freshness check. Main idea being there is no way to check the breakpoint
# Function is creating the correct md so this is a test expansion to check the 
# Finding.json against the result .md file

def _example_findings():
    ef = sorted( _EXAMPLES.glob("*/findings.json"))

    if not ef:

        pytest.skip("no findings.json found under examples/ — nothing to freshness-check") 

    return ef

