#!/usr/bin/env python3
"""
validate_version.py

Validates that:
1) Exactly one PR label exists with prefix RELEASE_LABEL_PREFIX (default: "release:")
   - release:patch | release:minor | release:major

Behavior:
- If no release label: no-op (exit 0, valid=false, release_type="")
- If multiple release labels: fail loudly (exit 1)
- If exactly one release label: validate it's valid (patch/minor/major) and pass

This script is intended to run in a GitHub Actions workflow triggered by pull_request events.

It writes step outputs to $GITHUB_OUTPUT:
- valid         ("true" if exactly one valid release label exists, "false" otherwise)
- release_type  ("patch"|"minor"|"major" or empty string if no label)
"""

from __future__ import annotations

import json
import os
import sys


# -----------------------------
# Utilities
# -----------------------------


def _env(name: str, default: str | None = None) -> str:
    v = os.environ.get(name)
    if v is None:
        if default is None:
            raise RuntimeError(f"Missing required environment variable: {name}")
        return default
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


# -----------------------------
# GitHub event parsing (PR labels)
# -----------------------------


def _load_event() -> dict:
    event_path = _env("GITHUB_EVENT_PATH")
    with open(event_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _extract_pr_labels(event: dict) -> list[str]:
    pr = event.get("pull_request")
    if not pr:
        raise RuntimeError(
            "This script expects to run on a pull_request event (event.pull_request missing)."
        )
    labels = pr.get("labels", [])
    return [lbl.get("name", "") for lbl in labels if isinstance(lbl, dict)]


# -----------------------------
# Main
# -----------------------------


def main() -> int:
    release_label_prefix = _env("RELEASE_LABEL_PREFIX", "release:")

    # Initialize outputs with defaults
    _write_output(valid="false", release_type="")

    event = _load_event()
    labels = _extract_pr_labels(event)

    # Find all release labels
    release_labels = [lbl for lbl in labels if lbl.startswith(release_label_prefix)]

    # No release labels: no-op (exit 0, but valid=false)
    if len(release_labels) == 0:
        print(
            f"No release label found with prefix {release_label_prefix!r}. "
            "No release will be created when this PR is merged."
        )
        return 0

    # Multiple release labels: fail loudly
    if len(release_labels) > 1:
        msg = (
            f"ERROR: Found {len(release_labels)} release labels, but exactly one is required.\n"
            f"Release labels found: {release_labels!r}\n"
            f"All labels on PR: {labels!r}\n"
            f"Please remove all but one release label ({release_label_prefix}patch, "
            f"{release_label_prefix}minor, or {release_label_prefix}major)."
        )
        print(msg, file=sys.stderr)
        return 1

    # Exactly one release label: validate it is patch/minor/major
    release_label = release_labels[0]
    release_type = release_label[len(release_label_prefix):].strip()

    if release_type not in {"patch", "minor", "major"}:
        msg = (
            f"ERROR: Invalid release label {release_label!r}.\n"
            f"Expected one of: {release_label_prefix}patch, {release_label_prefix}minor, "
            f"or {release_label_prefix}major.\n"
            f"Found: {release_label_prefix}{release_type!r}"
        )
        print(msg, file=sys.stderr)
        _write_output(release_type=release_type)
        return 1

    # Valid: exactly one valid release label
    _write_output(valid="true", release_type=release_type)
    print(
        f"✓ Valid release label found: {release_label!r} "
        f"(release type: {release_type})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
