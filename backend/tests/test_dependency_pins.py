"""Assert the versions the tests run against are the versions production installs.

Why this file exists
--------------------
Two production outages were caused by exactly one thing: `requirements.txt`
pinned a version that nobody had ever run the test suite against.

1. ``scikit-learn`` was pinned to 1.3.2 while the committed model artifacts were
   pickled by 1.8.0. Unpickling died with ``ModuleNotFoundError: No module named
   '_loss'``; the startup handler swallowed it, and ``/ml/model-info`` reported
   ``model_source="none"`` -- indistinguishable from "no models trained" -- for
   weeks.
2. ``ortools`` was pinned to 9.7.2996 while ``app/optimization/stochastic.py``
   calls the snake_case CP-SAT API (``new_bool_var``, ``new_int_var``) that only
   exists from 9.9. ``POST /stochastic/frontier`` -- the two-stage stochastic
   programme with the CVaR objective, the most technically substantial endpoint
   in the project -- returned 500 in production while passing locally.

In both cases the suite was green. A green suite says nothing about production
if the suite and production install different code. At the time this gate was
written, **twelve** pins had drifted, including fastapi 0.104.1 -> 0.135.3 and
pydantic 2.5.0 -> 2.12.5.

This test closes that gap: it is the comparison nothing was making.

If this fails
-------------
Do not delete the pin or loosen it to a range. Either install the pinned version
(``pip install -r requirements.txt``) or, if you deliberately upgraded, re-pin to
the version you actually tested against and note why in the commit.
"""

from __future__ import annotations

import re
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import pytest

REQUIREMENTS = Path(__file__).resolve().parent.parent / "requirements.txt"

#: Packages that legitimately are not importable in a dev virtualenv -- they are
#: pulled in transitively via an extra, or only ever installed in the container.
#: Keep this list SHORT and justified; every entry is a hole in the gate.
NOT_IMPORTABLE_LOCALLY = {
    "bcrypt",  # provided via passlib[bcrypt]; no standalone dist metadata here
}


def _parse_pins() -> dict[str, str]:
    """``{distribution name: pinned version}`` from requirements.txt.

    Handles inline comments and extras syntax (``uvicorn[standard]==0.44.0``).
    """
    pins: dict[str, str] = {}
    for raw in REQUIREMENTS.read_text().splitlines():
        code = raw.split("#", 1)[0].strip()
        if not code or "==" not in code:
            continue
        name_part, pinned = code.split("==", 1)
        base = re.sub(r"\[.*\]$", "", name_part.strip())
        pins[base.strip()] = pinned.strip()
    return pins


def test_requirements_file_is_parseable_and_fully_pinned() -> None:
    """Every dependency is pinned with ``==``, not a range.

    A range would defeat the whole point: production could resolve to something
    the suite has never seen.
    """
    pins = _parse_pins()
    assert pins, "no pinned requirements were parsed -- has the file moved?"

    unpinned = []
    for raw in REQUIREMENTS.read_text().splitlines():
        code = raw.split("#", 1)[0].strip()
        if not code:
            continue
        if "==" not in code and any(op in code for op in (">=", "<=", ">", "<", "~=", "!=")):
            unpinned.append(code)
    assert not unpinned, (
        "these dependencies are not pinned to an exact version, so production "
        f"may install something untested: {unpinned}"
    )


@pytest.mark.parametrize("package", sorted(_parse_pins()))
def test_installed_version_matches_the_pin(package: str) -> None:
    """The running interpreter has exactly the version requirements.txt pins."""
    pinned = _parse_pins()[package]

    if package in NOT_IMPORTABLE_LOCALLY:
        pytest.skip(f"{package} has no standalone dist metadata in this environment")

    try:
        installed = version(package)
    except PackageNotFoundError:
        pytest.fail(
            f"{package} is pinned to {pinned} in requirements.txt but is not installed. "
            "The suite is therefore not exercising it, while production will."
        )

    assert installed == pinned, (
        f"{package}: requirements.txt pins {pinned}, but the tests are running "
        f"against {installed}. Production installs the pin, so this suite is "
        f"green against code that will never run in production. Either "
        f"`pip install {package}=={pinned}`, or re-pin to {installed} if the "
        f"upgrade was deliberate."
    )
