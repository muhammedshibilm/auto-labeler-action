# Auto Labeler Action

A free, open-source GitHub Action that automatically labels pull requests —
by size, by changed file type, and (as a fallback) by an AI-suggested type —
with proper colors and descriptions, not plain gray defaults.

## Usage

```yaml
# .github/workflows/auto-label.yml
name: Auto Label PR

on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  contents: read
  pull-requests: write
  issues: write      # required to create/apply labels
  models: read        # required only if AI fallback is enabled

jobs:
  label:
    runs-on: ubuntu-latest
    steps:
      - uses: muhammedshibilm/auto-labeler-action@v1.0.0
        # optional inputs:
        # with:
        #   model: openai/gpt-4o-mini
        #   enable_ai_fallback: "true"
```

No secrets required — uses the built-in `GITHUB_TOKEN`.

## What it labels

**Size** (based on total lines changed):
`size/XS`, `size/S`, `size/M`, `size/L`, `size/XL`

**File type** (based on which files changed):
`tests`, `documentation`, `ci/cd`, `dependencies`, `frontend`, `backend`

**Fallback type label** — only applied if none of the file-type labels above
matched anything. Uses free GitHub Models to read the PR title/description
and suggest one of: `bug`, `feature`, `enhancement`, `refactor`, `chore`.
Set `enable_ai_fallback: "false"` to disable this and keep labeling 100%
rule-based (no API calls at all).

All labels are auto-created on first use with real colors and short
descriptions — see `scripts/auto_label.py` for the full color/description
table. Labels you've already customized manually are left untouched on
later runs.

## Inputs

| Input                | Required | Default              | Description                                    |
|-----------------------|----------|------------------------|-------------------------------------------------|
| `model`               | No       | `openai/gpt-4o-mini`  | Model used only for the fallback type label     |
| `enable_ai_fallback`  | No       | `"true"`              | Set to `"false"` to disable AI calls entirely   |
| `github_token`        | No       | `${{ github.token }}` | Override only if you need a different token     |

## Rate limits

GitHub Models' free tier is rate-limited. Since this action only calls it as
a fallback (not for every PR), usage stays low. If you hit a limit anyway,
the fallback is skipped gracefully and rule-based labels still apply.

## Contributing

Ideas welcome — configurable path rules via input, issue support (not just
PRs), or additional size/label presets.

## License

MIT — see [LICENSE](./LICENSE).
