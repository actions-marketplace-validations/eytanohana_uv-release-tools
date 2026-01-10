#!/usr/bin/env python3
"""
release.py

Handles automatic version bumping, committing, and tagging when a PR with a release label is merged.

Behavior:
- Detects release label from merged PR
- Runs `uv version --bump <type>` to update pyproject.toml
- Commits the version change
- Creates and pushes git tag

If no release label is found, this is a no-op (exit 0, committed=false).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from typing import Any

try:
    import tomllib
except ImportError:
    import tomli as tomllib


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
    """Append outputs to the file pointed to by $GITHUB_OUTPUT."""
    out_path = _env("GITHUB_OUTPUT")
    with open(out_path, "a", encoding="utf-8") as f:
        for k, v in kwargs.items():
            f.write(f"{k}={v}\n")


def _run(cmd: list[str], check: bool = True, capture_output: bool = True) -> subprocess.CompletedProcess:
    """Run a command and return the result."""
    result = subprocess.run(
        cmd,
        check=check,
        capture_output=capture_output,
        text=True,
    )
    return result


def _run_output(cmd: list[str]) -> str:
    """Run a command and return stdout."""
    return _run(cmd).stdout.strip()


# -----------------------------
# Version parsing
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


# -----------------------------
# GitHub API
# -----------------------------


def _get_merged_pr_number() -> int | None:
    """Get the PR number from the push event if it was a merge."""
    event_path = _env("GITHUB_EVENT_PATH")
    with open(event_path, "r", encoding="utf-8") as f:
        event = json.load(f)
    
    # Method 1: Check if the event has head_commit with a merge message
    head_commit = event.get("head_commit")
    if head_commit:
        message = head_commit.get("message", "")
        # Try to extract PR number from merge commit message
        # GitHub merge commits: "Merge pull request #123 from ..."
        match = re.search(r"Merge pull request #(\d+)", message, re.MULTILINE)
        if match:
            return int(match.group(1))
    
    # Method 2: Check commits array
    commits = event.get("commits", [])
    if commits:
        # Check the last commit (usually the merge commit)
        merge_commit = commits[-1]
        message = merge_commit.get("message", "")
        match = re.search(r"Merge pull request #(\d+)", message, re.MULTILINE)
        if match:
            return int(match.group(1))
    
    # Method 3: Try to get PR from commit SHA using GitHub API
    # This is a fallback if commit message parsing fails
    if head_commit:
        commit_sha = head_commit.get("id")
        if commit_sha:
            pr_number = _get_pr_from_commit(commit_sha)
            if pr_number:
                return pr_number
    
    return None


def _get_pr_from_commit(commit_sha: str) -> int | None:
    """Get PR number from commit SHA using GitHub API."""
    token = _env("GITHUB_TOKEN")
    repo = _env("GITHUB_REPOSITORY")
    
    url = f"https://api.github.com/repos/{repo}/commits/{commit_sha}/pulls"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    
    import urllib.request
    
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as response:
            prs = json.loads(response.read())
            if prs and len(prs) > 0:
                # Get the first PR (most recent)
                pr = prs[0]
                return pr.get("number")
    except Exception:
        # Silently fail - this is a fallback method
        pass
    
    return None


def _get_pr_labels(pr_number: int) -> list[str]:
    """Get labels from a PR using GitHub API."""
    token = _env("GITHUB_TOKEN")
    repo = _env("GITHUB_REPOSITORY")
    
    # Use GitHub API to get PR labels
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    
    import urllib.request
    
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as response:
            pr_data = json.loads(response.read())
            labels = pr_data.get("labels", [])
            return [label.get("name", "") for label in labels if isinstance(label, dict)]
    except Exception as e:
        print(f"Warning: Failed to fetch PR labels: {e}", file=sys.stderr)
        return []




# -----------------------------
# Git operations
# -----------------------------


def _git_config() -> None:
    """Configure git user for commits."""
    _run(["git", "config", "user.name", "github-actions[bot]"], check=False)
    _run(
        ["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"],
        check=False,
    )


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


def _get_current_branch() -> str:
    """Get the current branch name."""
    try:
        # Try to get branch from GITHUB_REF
        ref = _env("GITHUB_REF", "")
        if ref.startswith("refs/heads/"):
            return ref.replace("refs/heads/", "")
        
        # Fallback: get from git
        return _run_output(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    except Exception:
        # Final fallback
        return _env("DEFAULT_BRANCH", "main")


def _commit_and_push(file_path: str, message: str) -> bool:
    """Commit a file and push to origin."""
    try:
        branch = _get_current_branch()
        _run(["git", "add", file_path], check=True)
        _run(["git", "commit", "-m", message], check=True)
        _run(["git", "push", "origin", branch], check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error committing/pushing: {e}", file=sys.stderr)
        return False


# -----------------------------
# Main
# -----------------------------


def main() -> int:
    """Main release logic."""
    # Initialize outputs
    _write_output(
        version="",
        previous_version="",
        release_type="",
        tag="",
        created_tag="false",
        committed="false",
    )
    
    pyproject_path = _env("PYPROJECT_PATH", "pyproject.toml")
    release_label_prefix = _env("RELEASE_LABEL_PREFIX", "release:")
    tag_prefix = _env("TAG_PREFIX", "v")
    commit_message_template = _env("COMMIT_MESSAGE", "Release {version}")
    
    # Get merged PR number
    pr_number = _get_merged_pr_number()
    if not pr_number:
        print("No merged PR detected. This is a no-op - no release will be created.")
        return 0
    
    # Get PR labels
    labels = _get_pr_labels(pr_number)
    release_labels = [lbl for lbl in labels if lbl.startswith(release_label_prefix)]
    
    # No release label: no-op
    if len(release_labels) == 0:
        print(f"No release label found with prefix {release_label_prefix!r}. No release will be created.")
        return 0
    
    # Multiple release labels: should not happen if validate mode was used, but handle gracefully
    if len(release_labels) > 1:
        print(
            f"Warning: Found {len(release_labels)} release labels. Using the first one: {release_labels[0]!r}",
            file=sys.stderr,
        )
    
    # Extract release type
    release_label = release_labels[0]
    release_type = release_label[len(release_label_prefix):].strip()
    
    if release_type not in {"patch", "minor", "major"}:
        print(
            f"ERROR: Invalid release label {release_label!r}. "
            f"Expected {release_label_prefix}patch, {release_label_prefix}minor, or {release_label_prefix}major.",
            file=sys.stderr,
        )
        _write_output(release_type=release_type)
        return 1
    
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
            print(f"ERROR: uv version --bump failed: {result.stderr}", file=sys.stderr)
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
    commit_message = commit_message_template.format(version=new_version, release_type=release_type)
    if not _commit_and_push(pyproject_path, commit_message):
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
        if _create_and_push_tag(tag, tag_message):
            _write_output(created_tag="true")
            print(f"✓ Created and pushed tag: {tag}")
        else:
            print(f"ERROR: Failed to create/push tag {tag}", file=sys.stderr)
            return 1
    
    print(f"\n✓ Release complete: {previous_version} -> {new_version} ({release_type})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
