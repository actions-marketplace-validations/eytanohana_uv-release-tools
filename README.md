# uv-release-tools

A GitHub Action that automates semantic versioning and release tagging for Python projects using [uv](https://github.com/astral-sh/uv). Simply add a release label to your PR, and the action handles version bumping, committing, and tagging automatically.

## Features

- 🏷️ **Label-based releases** - Add `release:patch`, `release:minor`, or `release:major` labels to trigger releases
- ✅ **Automatic validation** - Validates labels on PR open/update to catch issues early
- 🚀 **Zero configuration** - Auto-detects context and handles both validation and release
- 📦 **uv integration** - Uses `uv version --bump` for reliable version management
- 🏷️ **Git tags** - Automatically creates and pushes version tags (e.g., `v1.2.3`)
- 🔒 **Safe defaults** - No-op if no release label, fails loudly on invalid configurations

## How It Works

The action automatically detects the context and behaves accordingly:

1. **PR Open/Update** → Validates release labels
   - Ensures exactly one valid release label exists
   - Fails if multiple labels or invalid label found
   - No-op if no release label (allows non-release PRs)

2. **PR Merged** → Performs release
   - Validates labels again (for safety)
   - Runs `uv version --bump <type>` to update `pyproject.toml` and `uv.lock`
   - Commits the version change
   - Creates and pushes a git tag

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
2. Add exactly one release label (`release:patch`, `release:minor`, or `release:major`)
3. Merge the PR
4. The action automatically bumps the version, commits it, and creates a tag!

## Requirements

- Python project with `pyproject.toml` using [PEP 621](https://peps.python.org/pep-0621/) format
- Version must be defined in `[project].version` (e.g., `version = "1.2.3"`)
- Semantic versioning (X.Y.Z format)
- `uv` installed (the action sets this up automatically)

## Inputs

| Input | Description | Default | Required |
|-------|-------------|---------|----------|
| `pyproject_path` | Path to `pyproject.toml` | `pyproject.toml` | No |
| `release_label_prefix` | PR label prefix for release labels | `release:` | No |
| `tag_prefix` | Prefix for git tags | `v` | No |
| `commit_message` | Commit message template | `Release {tag_prefix}{version}` | No |
| `default_branch` | Default branch name (fallback) | `main` | No |

### Commit Message Template

The `commit_message` input supports placeholders:
- `{version}` - The new version (e.g., `1.2.3`)
- `{tag_prefix}` - The tag prefix (e.g., `v`)
- `{release_type}` - The release type (`patch`, `minor`, or `major`)

Example: `"chore: bump version to {version} ({release_type})"` → `"chore: bump version to 1.2.3 (minor)"`

## Outputs

### Validation Outputs (PR open/update)

| Output | Description |
|--------|-------------|
| `valid` | `true` if exactly one valid release label exists, `false` otherwise |
| `release_type` | `patch`, `minor`, `major`, or empty string |

### Release Outputs (PR merged)

| Output | Description |
|--------|-------------|
| `version` | New version after bump |
| `previous_version` | Version before bump |
| `release_type` | Release type (`patch`, `minor`, or `major`) |
| `tag` | Full tag name (e.g., `v1.2.3`) |
| `created_tag` | `true` if a new tag was created |
| `committed` | `true` if version was committed |

## Examples

### Basic Usage

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

### Custom Configuration

```yaml
- uses: eytanohana/uv-release-tools@v1
  with:
    pyproject_path: "pyproject.toml"
    release_label_prefix: "version:"
    tag_prefix: ""
    commit_message: "chore: release {version}"
    default_branch: "master"
```

### Using Outputs

```yaml
- uses: your-username/uv-release-tools@main
  id: release

- name: Publish to PyPI
  if: steps.release.outputs.committed == 'true'
  run: |
    echo "Released version: ${{ steps.release.outputs.version }}"
    echo "Tag: ${{ steps.release.outputs.tag }}"
    # Your publish commands here
```

### Trigger Downstream Workflows

Create a separate workflow that triggers on tags:

```yaml
# .github/workflows/publish.yml
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

### Validation Phase (PR Open/Update)

- ✅ **No label** → No-op (exits 0, `valid=false`)
- ❌ **Multiple labels** → Fails (exits 1) with clear error message
- ❌ **Invalid label** → Fails (exits 1) if label is not `patch`, `minor`, or `major`
- ✅ **One valid label** → Passes (exits 0, `valid=true`, `release_type` set)

### Release Phase (PR Merged)

- ✅ **No label** → No-op (exits 0, no release created)
- ❌ **Multiple labels** → Fails (exits 1) - validation runs first
- ❌ **Invalid label** → Fails (exits 1) - validation runs first
- ✅ **One valid label** → Performs release:
  1. Reads current version from `pyproject.toml`
  2. Runs `uv version --bump <type>`
  3. Commits the version change
  4. Creates and pushes git tag
  5. Idempotent: skips if tag already exists

### PR Closed (Not Merged)

- No-op (exits 0) - no action taken

## Version Bumping Rules

The action uses `uv version --bump` which follows semantic versioning:

- **patch**: `1.2.3` → `1.2.4`
- **minor**: `1.2.3` → `1.3.0`
- **major**: `1.2.3` → `2.0.0`

## Troubleshooting

### Action fails with "uv not found"

The action automatically sets up `uv` using `astral-sh/setup-uv@v4`. If you see this error, ensure you're using the latest version of the action.

### "Could not find [project].version in pyproject.toml"

Ensure your `pyproject.toml` follows PEP 621 format:

```toml
[project]
name = "my-package"
version = "1.2.3"
```

### Tag already exists

The action is idempotent - if a tag already exists, it will skip tag creation and continue. This is safe and allows re-running workflows.

### Multiple release labels error

Remove all but one release label from your PR. The action requires exactly one release label to avoid ambiguity.

### Version not bumped after merge

Check:
1. PR was actually merged (not just closed)
2. PR has exactly one release label
3. Workflow has `contents: write` permission
4. Checkout step includes `token: ${{ secrets.GITHUB_TOKEN }}`

## Limitations

- Only supports PEP 621 `pyproject.toml` format
- Requires semantic versioning (X.Y.Z format)
- Does not support pre-release versions (e.g., `1.2.3.dev1`)
- Does not create GitHub Releases (only git tags)

## License

[Add your license here]

## Contributing

Contributions welcome! Please open an issue or PR.
