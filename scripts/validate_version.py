#!/usr/bin/env python3
"""
validate_version.py

Validates that:
1) Exactly one PR label exists with prefix RELEASE_LABEL_PREFIX (default: "release:")
   - release:patch | release:minor | release:major
2) The version in pyproject.toml changed from base -> head
3) The semantic bump implied by that change matches the label

This script is intended to run in a GitHub Actions workflow triggered by pull_request events.

It writes step outputs to $GITHUB_OUTPUT:
- version           (head version)
- valid             ("true" if validation passes, otherwise "false")
- expected_bump     ("patch"|"minor"|"major")
- actual_bump       ("patch"|"minor"|"major")
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass


# -----------------------------
# Utilities
# -----------------------------


def _env(name: str, default: str | None = None) -> str:
    v = os.environ.get(name, default)
    if not v:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return v


def _write_output(**kwargs: str) -> None:
    """
    Append outputs to the file pointed to by $GITHUB_OUTPUT.
    """
    out_path = _env("GITHUB_OUTPUT")
    with open(out_path, "a", encoding="utf-8") as f:
        for k, v in kwargs.items():
            # GitHub output format is "key=value" per line.
            f.write(f"{k}={v}\n")


def _run(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, text=True).strip()


# -----------------------------
# Version parsing / bump logic
# -----------------------------


@dataclass(frozen=True, order=True)
class Ver:
    major: int
    minor: int
    patch: int

    @staticmethod
    def parse(s: str) -> "Ver":
        m = re.fullmatch(r"\s*(\d+)\.(\d+)\.(\d+)\s*", s)
        if not m:
            raise ValueError(
                f"Unsupported version format: {s!r}. Expected strict semver X.Y.Z"
            )
        return Ver(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


def _semver_bump(base: Ver, head: Ver) -> str:
    """
    Determine bump type under strict rules:
      patch: X.Y.Z -> X.Y.(Z+1)
      minor: X.Y.Z -> X.(Y+1).0
      major: X.Y.Z -> (X+1).0.0
    """
    if head <= base:
        raise ValueError(f"Version must increase (base={base}, head={head})")

    if head.major == base.major and head.minor == base.minor and head.patch == base.patch + 1:
        return "patch"

    if head.major == base.major and head.minor == base.minor + 1 and head.patch == 0:
        return "minor"

    if head.major == base.major + 1 and head.minor == 0 and head.patch == 0:
        return "major"

    raise ValueError(
        "Version change does not match strict semver bump rules "
        f"(base={base}, head={head}). "
        "Expected patch (Z+1), minor (Y+1, patch=0), or major (X+1, minor=0, patch=0)."
    )


# -----------------------------
# pyproject reading
# -----------------------------


def _tomllib():
    # Prefer stdlib tomllib (py3.11+); fall back to tomli if needed.
    try:
        import tomllib  # type: ignore[attr-defined]
        return tomllib
    except Exception:
        import tomli  # type: ignore[import-not-found]
        return tomli


def _version_from_pyproject_content(content: str) -> Ver:
    toml = _tomllib().loads(content.encode() if hasattr(_tomllib(), "loads") else content)
    # Note: tomllib.loads expects str (py3.11+). tomli.loads expects str too.
    # The above encode trick isn't necessary; keep it simple:
    # We'll re-parse properly below.

    # Re-parse correctly for both tomllib/tomli
    tl = _tomllib()
    data = tl.loads(content)
    try:
        version = data["project"]["version"]
    except KeyError as e:
        raise KeyError(
            "Could not find [project].version in pyproject.toml. "
            "This action currently supports PEP 621 versions only."
        ) from e
    return Ver.parse(str(version))


def _pyproject_version_at_ref(ref: str, pyproject_path: str) -> Ver:
    """
    Read pyproject.toml at a given git ref using `git show`.
    """
    content = _run(["git", "show", f"{ref}:{pyproject_path}"])
    return _version_from_pyproject_content(content)


# -----------------------------
# GitHub event parsing (PR labels + SHAs)
# -----------------------------


def _load_event() -> dict:
    event_path = _env("GITHUB_EVENT_PATH")
    with open(event_path, "r", encoding="utf-8") as f:
        result = json.load(f)
        print(json.dumps(result, indent=4))
        return result


def _extract_pr_labels(event: dict) -> list[str]:
    pr = event.get("pull_request")
    if not pr:
        raise RuntimeError(
            "This script expects to run on a pull_request event (event.pull_request missing)."
        )
    labels = pr.get("labels", [])
    return [l.get("name", "") for l in labels if isinstance(l, dict)]


def _extract_base_head_shas(event: dict) -> tuple[str, str]:
    pr = event["pull_request"]
    base_sha = pr["base"]["sha"]
    head_sha = pr["head"]["sha"]
    return base_sha, head_sha


# -----------------------------
# Main
# -----------------------------


def main() -> int:
    release_label_prefix = _env("RELEASE_LABEL_PREFIX", "release:")
    pyproject_path = _env("PYPROJECT_PATH", "pyproject.toml")

    # Sensible defaults for outputs (so callers can always read them)
    _write_output(version="", valid="false", expected_bump="", actual_bump="")

    event = _load_event()
    labels = _extract_pr_labels(event)
    base_sha, head_sha = _extract_base_head_shas(event)

    release_labels = [l for l in labels if l.startswith(release_label_prefix)]
    if len(release_labels) != 1:
        msg = (
            f"Expected exactly one release label with prefix {release_label_prefix!r}, "
            f"found: {release_labels!r} (all labels: {labels!r})"
        )
        print(msg, file=sys.stderr)
        return 1

    expected_bump = release_labels[0][len(release_label_prefix):].strip()
    if expected_bump not in {"patch", "minor", "major"}:
        msg = (
            f"Invalid release label {release_labels[0]!r}. "
            f"Expected one of: {release_label_prefix}patch|minor|major"
        )
        print(msg, file=sys.stderr)
        _write_output(expected_bump=expected_bump)
        return 1

    try:
        base_ver = _pyproject_version_at_ref(base_sha, pyproject_path)
        head_ver = _pyproject_version_at_ref(head_sha, pyproject_path)
    except subprocess.CalledProcessError as e:
        print(
            "Failed to read pyproject.toml from git refs. "
            "Make sure you used actions/checkout with fetch-depth: 0.",
            file=sys.stderr,
        )
        raise
    except Exception as e:
        print(str(e), file=sys.stderr)
        raise

    # Write head version output early for visibility
    _write_output(version=str(head_ver), expected_bump=expected_bump)

    try:
        actual_bump = _semver_bump(base_ver, head_ver)
    except Exception as e:
        print(str(e), file=sys.stderr)
        _write_output(actual_bump="")
        return 1

    _write_output(actual_bump=actual_bump)

    if actual_bump != expected_bump:
        print(
            f"Release label expects {expected_bump!r} but version bump is {actual_bump!r}. "
            f"(base={base_ver}, head={head_ver})",
            file=sys.stderr,
        )
        return 1

    _write_output(valid="true")
    print(
        f"OK: {expected_bump} bump matches label ({release_labels[0]!r}). "
        f"(base={base_ver} -> head={head_ver})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
