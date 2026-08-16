"""Shared artifact-provenance stamping for every generator under ``seeds/``.

A reproducibility audit (2026-08) found that only 1 of 7 published JSON artifacts
recorded *any* provenance, and the one that did recorded a ``-dirty`` git SHA
silently — so a reader could not tell whether the numbers came from committed code
or from an uncommitted working tree.

Every generator now stamps a ``provenance`` block built by :func:`build_provenance`
containing:

  * ``generated_at_utc`` — ISO-8601 UTC timestamp of the run.
  * ``generator``        — the module that produced the artifact.
  * ``git``              — commit SHA, short SHA, branch and a ``dirty`` flag. When
                           the tree is dirty a loud ``warning`` string is included
                           *and* ``dirty`` is ``true``, so the condition is visible
                           in the artifact and in any doc rendered from it rather
                           than buried in a suffix.
  * ``inputs``           — SHA-256 + byte size of every input data file, so a reader
                           can tell whether two artifacts were built from the same
                           bytes. This is what caught the FRED in-place revision
                           that silently inverted the Chronos/Prophet headline.
  * ``python``/``platform`` — interpreter and machine, for timing figures.

Usage::

    from seeds.provenance import build_provenance, provenance_markdown

    prov = build_provenance(
        generator="seeds.run_forecast_backtest",
        inputs={"a34sno": CACHE_PATH},
        extra={"vintage": "2026-08-16"},
    )
    payload["provenance"] = prov
    md += provenance_markdown(prov)
"""
from __future__ import annotations

import hashlib
import platform
import subprocess
import sys
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Mapping, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]

DIRTY_WARNING = (
    "UNCOMMITTED CHANGES: this artifact was generated from a working tree that did "
    "not match its git commit. Checking out the recorded SHA alone will NOT reproduce "
    "these numbers. Regenerate from a clean tree before treating them as published."
)


def sha256_file(path: str | Path) -> Optional[str]:
    """SHA-256 of a file's bytes, or ``None`` when the file is missing."""
    p = Path(path)
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    """SHA-256 of a unicode string (UTF-8 encoded). Used for in-memory series."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _git(*args: str) -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except Exception:  # noqa: BLE001 - provenance must never break a generator
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip()


def git_info() -> dict[str, Any]:
    """Commit SHA / branch / dirty state of the repo this generator ran from."""
    commit = _git("rev-parse", "HEAD")
    status = _git("status", "--porcelain")
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    dirty = bool(status)
    info: dict[str, Any] = {
        "commit": commit,
        "commit_short": commit[:10] if commit else None,
        "branch": branch,
        "dirty": dirty,
    }
    if dirty:
        paths = sorted(line[3:].strip() for line in (status or "").splitlines())
        info["warning"] = DIRTY_WARNING
        info["dirty_file_count"] = len(paths)
        # Name the paths so a reader can judge whether they could affect the numbers,
        # truncated so provenance does not dominate the artifact.
        info["dirty_paths"] = paths[:20]
        if len(paths) > 20:
            info["dirty_paths_truncated"] = len(paths) - 20
    return info


def file_inputs(inputs: Mapping[str, str | Path]) -> dict[str, Any]:
    """Hash a mapping of ``label -> path`` into a provenance ``inputs`` block."""
    out: dict[str, Any] = {}
    for label, raw in inputs.items():
        p = Path(raw)
        digest = sha256_file(p)
        out[label] = {
            "path": _rel(p),
            "sha256": digest,
            "bytes": p.stat().st_size if p.is_file() else None,
            "exists": digest is not None,
        }
    return out


def build_provenance(
    generator: str,
    inputs: Optional[Mapping[str, str | Path]] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Build the provenance block stamped into every generated artifact."""
    prov: dict[str, Any] = {
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generator": generator,
        "git": git_info(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "inputs": file_inputs(inputs or {}),
    }
    if extra:
        prov.update(dict(extra))
    return prov


def provenance_markdown(prov: Mapping[str, Any], heading: str = "## Provenance") -> str:
    """Render a provenance block as a markdown section for a generated doc."""
    git = dict(prov.get("git") or {})
    lines: list[str] = ["", heading, ""]
    lines.append(f"- **Generated:** {prov.get('generated_at_utc', 'unknown')} (UTC)")
    lines.append(f"- **Generator:** `{prov.get('generator', 'unknown')}`")
    sha = git.get("commit") or "unknown"
    if git.get("dirty"):
        lines.append(
            f"- **Commit:** `{sha}` — ⚠️ **DIRTY WORKING TREE.** {DIRTY_WARNING}"
        )
    else:
        lines.append(f"- **Commit:** `{sha}` (clean tree)")
    for label, meta in (prov.get("inputs") or {}).items():
        meta = dict(meta)
        digest = meta.get("sha256")
        short = digest[:16] + "…" if digest else "MISSING"
        lines.append(f"- **Input `{label}`:** `{meta.get('path')}` · sha256 `{short}`")
    for key in ("vintage", "as_of", "vintage_date"):
        if key in prov:
            lines.append(f"- **Data vintage pin:** `{prov[key]}`")
    lines.append(f"- **Python:** {prov.get('python')} · {prov.get('platform')}")
    lines.append("")
    return "\n".join(lines)
