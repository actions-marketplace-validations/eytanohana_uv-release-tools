#!/usr/bin/env python3
"""
main.py

Unified script that handles both validation and release based on PR state.

Behavior:
- PR open/update: Validates release labels
- PR merged: Bumps version, commits, and creates tag

Auto-detects context from GitHub event.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import tomllib


# -----------------------------
# Constants
# -----------------------------

VALID_RELEASE_TYPES = {"patch", "minor", "major"}


# -----------------------------
# Utilities
# -----------------------------


def _env(name: str, default: str | None = None) -> str:
    """Get environment variable with optional default."""
    v = os.environ.get(name)
    if v is None:
        if default is None:
            raise RuntimeError(f"Missing required environment variable: {name}")
        return default
    return v


def _write_output(**kwargs: str) -> None:
    """Append outputs to the file pointed to by $GITHUB_OUTPUT."""
    out_path = _env("GITHUB_OUTPUT")
    with open(out_path, "a", encoding="utf-8") as f:
        for k, v in kwargs.items():
            f.write(f"{k}={v}\n")


def _run(cmd: list[str], check: bool = True, capture_output: bool = True) -> subprocess.CompletedProcess:
    """Run a command and return the result."""
    return subprocess.run(
        cmd,
        check=check,
        capture_output=capture_output,
        text=True,
    )


def _run_output(cmd: list[str]) -> str:
    """Run a command and return stdout."""
    return _run(cmd).stdout.strip()


# -----------------------------
# GitHub event parsing
# -----------------------------


def _load_event() -> dict:
    """Load GitHub event JSON."""
    event_path = _env("GITHUB_EVENT_PATH")
    with open(event_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_pr_merged(pull_request: dict) -> bool:
    """Check if PR is merged."""
    return bool(pull_request and pull_request.get("merged", False))


def _extract_pr_labels(pr: dict) -> list[str]:
    """Extract labels from PR."""
    labels = pr.get("labels", [])
    return [lbl.get("name", "") for lbl in labels if isinstance(lbl, dict)]


def _extract_release_type(
    labels: list[str],
    release_label_prefix: str,
) -> tuple[str | None, str | None]:
    """
    Extract release type from labels.
    Returns (release_type, error_message).
    """
    release_labels = [lbl for lbl in labels if lbl.startswith(release_label_prefix)]

    if len(release_labels) == 0:
        return None, None

    if len(release_labels) > 1:
        error_msg = (
            f"ERROR: Found {len(release_labels)} release labels, but exactly one is required.\n"
            f"Release labels found: {release_labels!r}\n"
            f"All labels on PR: {labels!r}\n"
            f"Please remove all but one release label."
        )
        return None, error_msg

    release_label = release_labels[0]
    release_type = release_label[len(release_label_prefix):].strip()

    if release_type not in VALID_RELEASE_TYPES:
        error_msg = (
            f"ERROR: Invalid release label {release_label!r}.\n"
            f"Expected one of: {release_label_prefix}patch, {release_label_prefix}minor, "
            f"or {release_label_prefix}major.\n"
            f"Found: {release_label_prefix}{release_type!r}"
        )
        return None, error_msg

    return release_type, None


# -----------------------------
# Validation logic
# -----------------------------


def validate_labels(pr: dict, release_label_prefix: str) -> tuple[int, str]:
    """
    Validate release labels on PR.
    Returns (exit_code, release_type).
    """
    _write_output(valid="false", release_type="")

    labels = _extract_pr_labels(pr)
    release_type, error_msg = _extract_release_type(labels, release_label_prefix)

    if error_msg:
        print(error_msg, file=sys.stderr)
        return 1, ""

    if release_type is None:
        print(
            f"No release label found with prefix {release_label_prefix!r}. "
            "No release will be created when this PR is merged."
        )
        return 0, ""

    _write_output(valid="true", release_type=release_type)
    print(f'✓ Valid release label found: "{release_label_prefix}{release_type}"')
    return 0, release_type


# -----------------------------
# Release logic
# -----------------------------


def _read_version_from_pyproject(pyproject_path: str) -> str:
    """Read version from pyproject.toml."""
    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)
    try:
        return str(data["project"]["version"])
    except KeyError as e:
        raise KeyError(
            "Could not find [project].version in pyproject.toml. "
            "This action currently supports PEP 621 versions only."
        ) from e


def _git_config() -> None:
    """Configure git user for commits."""
    _run(["git", "config", "user.name", "github-actions[bot]"], check=False)
    _run(
        ["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"],
        check=False,
    )


def _get_current_branch() -> str:
    """Get the current branch name."""
    try:
        ref = _env("GITHUB_REF", "")
        if ref.startswith("refs/heads/"):
            return ref.replace("refs/heads/", "")
        return _run_output(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    except Exception:
        return _env("DEFAULT_BRANCH", "main")


def _tag_exists(tag: str) -> bool:
    """Check if a git tag exists."""
    try:
        _run(["git", "rev-parse", "--verify", f"refs/tags/{tag}"], check=True)
        return True
    except subprocess.CalledProcessError:
        return False


def _create_and_push_tag(tag: str, message: str) -> bool:
    """Create an annotated tag and push it."""
    try:
        _run(["git", "tag", "-a", tag, "-m", message], check=True)
        _run(["git", "push", "origin", tag], check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error creating/pushing tag: {e}", file=sys.stderr)
        return False


def _commit_and_push(message: str) -> bool:
    """Commit a file and push to origin."""
    try:
        branch = _get_current_branch()
        _run(["git", "add", "."], check=True)
        _run(["git", "commit", "-m", message], check=True)
        _run(["git", "push", "origin", branch], check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error committing/pushing: {e}", file=sys.stderr)
        return False


def release(release_type: str) -> int:
    """
    Perform release: bump version, commit, and tag.
    Returns exit code.
    """
    _write_output(
        version="",
        previous_version="",
        release_type=release_type,
        tag="",
        created_tag="false",
        committed="false",
    )

    pyproject_path = _env("PYPROJECT_PATH", "pyproject.toml")
    tag_prefix = _env("TAG_PREFIX", "v")
    commit_message_template = _env("COMMIT_MESSAGE", "Release {tag_prefix}{version}")

    # Read current version
    try:
        previous_version = _read_version_from_pyproject(pyproject_path)
    except Exception as e:
        print(f"ERROR: Failed to read version from {pyproject_path}: {e}", file=sys.stderr)
        return 1

    _write_output(previous_version=previous_version, release_type=release_type)

    # Configure git
    _git_config()

    # Run uv version --bump
    try:
        print(f"Running: uv version --bump {release_type}")
        result = _run(["uv", "version", "--bump", release_type], check=False)
        if result.returncode != 0:
            print(f"ERROR: uv version --bump {release_type} failed: {result.stderr}", file=sys.stderr)
            return 1
        print(result.stdout.strip())
    except FileNotFoundError:
        print("ERROR: uv not found. Please install uv or use actions/setup-uv.", file=sys.stderr)
        return 1

    # Read new version
    try:
        new_version = _read_version_from_pyproject(pyproject_path)
    except Exception as e:
        print(f"ERROR: Failed to read new version: {e}", file=sys.stderr)
        return 1

    _write_output(version=new_version)

    # Commit the change
    commit_message = commit_message_template.format(tag_prefix=tag_prefix, version=new_version, release_type=release_type)
    if not _commit_and_push(commit_message):
        print("ERROR: Failed to commit and push version change", file=sys.stderr)
        return 1

    _write_output(committed="true")
    print(f"✓ Committed version change: {previous_version} -> {new_version}")

    # Create tag
    tag = f"{tag_prefix}{new_version}"
    _write_output(tag=tag)

    if _tag_exists(tag):
        print(f"Tag {tag} already exists. Skipping tag creation.")
    else:
        tag_message = f"Release {tag}"
        if not _create_and_push_tag(tag, tag_message):
            print(f"ERROR: Failed to create/push tag {tag}", file=sys.stderr)
            return 1
        _write_output(created_tag="true")
        print(f"✓ Created and pushed tag: {tag}")

    print(f"\n✓ Release complete: {previous_version} -> {new_version} ({release_type})")
    return 0


# -----------------------------
# Main
# -----------------------------


def main() -> int:
    """Main entry point - auto-detects context and runs appropriate logic."""
    release_label_prefix = _env("RELEASE_LABEL_PREFIX", "release:")
    event = _load_event()
    pr = event.get("pull_request")
    action = event.get("action", "")

    # PR was closed but not merged - no-op
    if action == "closed" and not _is_pr_merged(pr):
        print("PR was closed but not merged. No action needed.")
        return 0

    # PR was merged - perform release
    if _is_pr_merged(pr):
        print("PR merged - performing release...")
        # Validate labels first (same validation as open/update)
        exit_code, release_type = validate_labels(pr, release_label_prefix)

        if exit_code != 0:
            # Validation failed (multiple labels or invalid label)
            return exit_code

        if not release_type:
            # No release label found - no-op
            print("No release label found. Release will not be created.")
            return 0

        return release(release_type)

    # PR is open/updated - validate labels
    print("PR open/updated - validating labels...")
    exit_code, _ = validate_labels(pr, release_label_prefix)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
