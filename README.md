# uv-release-tools

> **Automated semantic versioning for Python projects using uv**  
> Add a label, merge a PR, get a release. That's it.

A GitHub Action that eliminates the manual work of version management. Simply add a `release:{type}` label to your pull request, and the action handles version bumping, committing, and tagging automatically.

## Why This Exists

Managing versions manually is error-prone:
- ❌ Forgetting to bump versions
- ❌ Version drift between `pyproject.toml` and git tags
- ❌ Inconsistent version formats
- ❌ Manual git operations that can fail

This action solves all of that by:
- ✅ **Single source of truth** - `pyproject.toml` is the authoritative version
- ✅ **Zero manual steps** - Everything happens automatically on merge
- ✅ **Early validation** - Catches label mistakes before merge
- ✅ **Idempotent** - Safe to re-run, won't create duplicate tags

## How It Works

The action is **context-aware** and automatically detects what to do:

```
PR Opened/Updated → Validates labels
PR Merged         → Bumps version, commits, creates tag
PR Closed         → No-op (nothing to do)
```

### The Flow

1. **You open a PR** → Action validates that you have exactly one valid release label
2. **You merge the PR** → Action:
   - Validates labels again (defense in depth)
   - Runs `uv version --bump <type>` to update `pyproject.toml` and `uv.lock`
   - Commits the changes with a customizable message
   - Creates and pushes a git tag (e.g., `v1.2.3`)

That's it. No manual version bumping. No manual tagging. No mistakes.

## Quick Start

### 1. Create a workflow file

Create `.github/workflows/release.yml`:

```yaml
name: Release

on:
  pull_request:
    branches: [ "main" ]
    types: [opened, synchronize, labeled, unlabeled, closed]

jobs:
  release:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: read
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
          token: ${{ secrets.GITHUB_TOKEN }}

      - uses: eytanohana/uv-release-tools@v1
```

### 2. Add release labels to your repository

Create three labels in your repository:
- `release:patch` - For bug fixes and patches
- `release:minor` - For new features (backward compatible)
- `release:major` - For breaking changes

### 3. Use it

1. Open a PR with your changes
2. Add **exactly one** release label
3. Merge the PR
4. ✨ Version bumped, committed, and tagged automatically!

## Requirements

- Python project with `pyproject.toml` using [PEP 621](https://peps.python.org/pep-0621/) format
- Version defined in `[project].version` (e.g., `version = "1.2.3"`)
- Semantic versioning (X.Y.Z format)
- `uv` installed (the action sets this up automatically)

## Inputs

| Input | Description | Default | Required |
|-------|-------------|---------|----------|
| `pyproject_path` | Path to `pyproject.toml` | `pyproject.toml` | No |
| `release_label_prefix` | Prefix for release labels | `release:` | No |
| `tag_prefix` | Prefix for git tags | `v` | No |
| `commit_message` | Commit message template | `Release {tag_prefix}{version}` | No |
| `default_branch` | Default branch name (fallback) | `main` | No |

### Commit Message Template

The `commit_message` input supports these placeholders:
- `{version}` - the new version (e.g., `1.2.3`)
- `{tag_prefix}` - the tag prefix (e.g., `v`)
- `{release_type}` - the release type (`patch`, `minor`, `major`)

**Examples:**
- `"Release {tag_prefix}{version}"` → `"Release v1.2.3"`
- `"chore: bump to {version} ({release_type})"` → `"chore: bump to 1.2.3 (minor)"`

## Outputs

### Validation Outputs (PR opened/updated)

| Output | Description |
|--------|-------------|
| `valid` | `true` if exactly one valid release label exists, `false` otherwise |
| `release_type` | `patch`, `minor`, `major`, or empty string |

### Release Outputs (PR merged)

| Output | Description |
|--------|-------------|
| `version` | New version after bump |
| `previous_version` | Version before bump |
| `release_type` | Release type used |
| `tag` | Full tag name (e.g., `v1.2.3`) |
| `created_tag` | `true` if tag was created |
| `committed` | `true` if version was committed |

## Examples

### Basic Usage

```yaml
- uses: eytanohana/uv-release-tools@v1
```

### Custom Label Prefix

```yaml
- uses: eytanohana/uv-release-tools@v1
  with:
    release_label_prefix: "version:"
```

This expects labels like `version:patch`, `version:minor`, `version:major`.

### Custom Commit Message

```yaml
- uses: eytanohana/uv-release-tools@v1
  with:
    commit_message: "chore: release {version} ({release_type})"
```

### No Tag Prefix

```yaml
- uses: eytanohana/uv-release-tools@v1
  with:
    tag_prefix: ""
```

This creates tags like `1.2.3` instead of `v1.2.3`.

### Using Outputs for Downstream Actions

```yaml
- uses: eytanohana/uv-release-tools@v1
  id: release

- name: Publish to PyPI
  if: steps.release.outputs.committed == 'true'
  run: |
    echo "Released: ${{ steps.release.outputs.version }}"
    echo "Tag: ${{ steps.release.outputs.tag }}"
    # Your publish commands here
```

### Trigger PyPI Publishing on Tag

Create `.github/workflows/publish.yml`:

```yaml
name: Publish

on:
  push:
    tags:
      - "v*"

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv build
      - run: uv publish
        env:
          UV_PUBLISH_TOKEN: ${{ secrets.PYPI_API_TOKEN }}
```

## Behavior Details

### Validation (PR Open/Update)

The action validates labels to catch mistakes early:

- ✅ **No label** → No-op (exits successfully, `valid=false`)
  - Allows PRs without release labels
  - No release will be created when merged
  
- ❌ **Multiple labels** → Fails with clear error
  - Example: PR has both `release:patch` and `release:minor`
  - Error message lists all release labels found
  
- ❌ **Invalid label** → Fails with clear error
  - Example: `release:invalid` or `release:hotfix`
  - Only `patch`, `minor`, `major` are valid
  
- ✅ **One valid label** → Passes (`valid=true`, `release_type` set)

### Release (PR Merged)

When a PR is merged, the action:

1. **Validates again** - Same validation as PR open (defense in depth)
2. **Reads current version** - From `pyproject.toml`
3. **Bumps version** - Runs `uv version --bump <type>`
   - Updates both `pyproject.toml` and `uv.lock`
4. **Commits changes** - Uses `git add .` to commit all changes
5. **Creates tag** - Creates annotated tag and pushes it
6. **Idempotent** - If tag exists, skips creation (safe to re-run)

### Version Bumping

Uses `uv version --bump` which follows semantic versioning:

- **patch**: `1.2.3` → `1.2.4` (bug fixes)
- **minor**: `1.2.3` → `1.3.0` (new features, backward compatible)
- **major**: `1.2.3` → `2.0.0` (breaking changes)

## Troubleshooting

### "Could not find [project].version in pyproject.toml"

Your `pyproject.toml` must use PEP 621 format:

```toml
[project]
name = "my-package"
version = "1.2.3"
```

**Not supported:**
- `setup.py` with version
- `__version__` in Python files
- Other version formats

### "ERROR: Found 2 release labels"

You have multiple release labels on your PR. Remove all but one:
- Keep: `release:patch` OR `release:minor` OR `release:major`
- Remove: All other release labels

### "ERROR: Invalid release label"

The label must be exactly:
- `release:patch`
- `release:minor`
- `release:major`

Case-sensitive, no typos.

### Version not bumped after merge

Checklist:
1. ✅ PR was **merged** (not just closed)
2. ✅ PR has **exactly one** release label
3. ✅ Workflow has `contents: write` permission
4. ✅ Checkout step includes `token: ${{ secrets.GITHUB_TOKEN }}` (required for git push operations)
5. ✅ `pyproject.toml` has valid version in `[project].version`

### Tag already exists

This is **safe** - the action is idempotent. If a tag exists, it skips creation and continues. This allows you to re-run workflows without errors.

### Action fails silently

Check the workflow logs. The action prints clear messages:
- `"PR merged - performing release..."` - Release in progress
- `"No release label found..."` - No-op (expected if no label)
- `"✓ Release complete..."` - Success

## Design Philosophy

This action is designed to be **boring** - and that's a feature:

- **Predictable** - Same input always produces same output
- **Safe** - Fails loudly on errors, no-op on edge cases
- **Simple** - No configuration needed for most cases
- **Reliable** - Idempotent operations, no race conditions

It follows the principle: **Humans decide when to release, automation handles the mechanics.**

## Limitations

- **PEP 621 only** - Requires `[project].version` in `pyproject.toml`
- **Semantic versioning** - Only supports X.Y.Z format
- **No pre-releases** - Doesn't support `1.2.3.dev1`, `1.2.3-rc1`, etc.
- **Git tags only** - Doesn't create GitHub Releases (use downstream workflows)

## License

[Add your license here]

## Contributing

Contributions welcome! Please open an issue or pull request.
