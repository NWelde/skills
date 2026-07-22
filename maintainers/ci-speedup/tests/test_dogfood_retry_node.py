"""Run the JS dogfood-retry assertions under pytest so CI actually exercises them.

`dogfood-retry.test.mjs` pins the dogfood workflow's `isTransient` matcher and
`isForceFlag` predicate by extracting them from the workflow source. CI only runs
`pytest -v` (see `.github/workflows/ci.yml`) and pytest does not collect `.mjs`,
so without this shim the JS test would never run on a PR and a regression to the
matcher could merge green. This delegates to `node`, surfacing the JS assertions
as a normal pytest failure. Skips (does not fail) when `node` is unavailable in a
local dev environment; the CI workflow installs node (setup-node), so a missing
`node` there means the setup step broke — this suite hard-fails instead of
silently skipping so that regression can't merge green.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_TEST_MJS = Path(__file__).parent / "dogfood-retry.test.mjs"

_HAS_NODE = shutil.which("node") is not None
if not _HAS_NODE and os.environ.get("CI"):
    pytest.fail("node is required in CI (setup-node step missing or broken); "
                "this suite must not silently skip on the runner", pytrace=False)


@pytest.mark.skipif(not _HAS_NODE, reason="node not installed")
def test_dogfood_retry_mjs_passes():
    assert _TEST_MJS.exists(), f"missing JS test: {_TEST_MJS}"
    result = subprocess.run(
        ["node", str(_TEST_MJS)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        "dogfood-retry.test.mjs failed:\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
