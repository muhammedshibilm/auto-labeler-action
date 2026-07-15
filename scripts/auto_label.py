import os
import sys
import requests

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
PR_NUMBER = os.environ["PR_NUMBER"]
REPO = os.environ["REPO"]
MODEL = os.environ.get("MODEL", "openai/gpt-4o-mini")
ENABLE_AI_FALLBACK = os.environ.get("ENABLE_AI_FALLBACK", "true").lower() == "true"

GITHUB_API = "https://api.github.com"
MODELS_API = "https://models.github.ai/inference/chat/completions"
REQUEST_TIMEOUT = 30

HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

# --- Label definitions: name -> (hex color without '#', description) ---
LABEL_DEFINITIONS = {
    "size/XS": ("c2e0c6", "Tiny change (≤10 lines)"),
    "size/S": ("7bc47f", "Small change (≤50 lines)"),
    "size/M": ("ffd966", "Medium change (≤200 lines)"),
    "size/L": ("f4b183", "Large change (≤500 lines)"),
    "size/XL": ("e06666", "Very large change (>500 lines) — consider splitting"),
    "tests": ("0e8a16", "Adds or modifies tests"),
    "documentation": ("0075ca", "Documentation-only or docs-heavy change"),
    "ci/cd": ("5319e7", "Workflow, pipeline, or build config change"),
    "dependencies": ("d4c5f9", "Dependency or package manifest change"),
    "frontend": ("fbca04", "Frontend / UI code change"),
    "backend": ("1d76db", "Backend / server / API code change"),
    "bug": ("d73a4a", "Fixes a bug"),
    "feature": ("a2eeef", "Adds a new feature"),
    "enhancement": ("84b6eb", "Improves existing functionality"),
    "refactor": ("c5def5", "Code restructuring with no behavior change"),
    "chore": ("ededed", "Maintenance task, no user-facing change"),
}

# path substring -> label
PATH_LABEL_RULES = [
    (("test/", "tests/", "__tests__/", "spec/", "_test.", ".test."), "tests"),
    (("docs/", "README", ".md"), "documentation"),
    ((".github/workflows/", "Dockerfile", ".yml", ".yaml"), "ci/cd"),
    (
        ("package.json", "package-lock.json", "requirements.txt", "Gemfile",
         "go.mod", "go.sum", "pom.xml", "Cargo.toml"),
        "dependencies",
    ),
    (("frontend/", "client/", "ui/", ".css", ".scss", ".jsx", ".tsx"), "frontend"),
    (("backend/", "server/", "api/"), "backend"),
]

SIZE_THRESHOLDS = [
    (10, "size/XS"),
    (50, "size/S"),
    (200, "size/M"),
    (500, "size/L"),
]

AI_ALLOWED_LABELS = {"bug", "feature", "enhancement", "refactor", "chore"}


def gh_get(path, **kwargs):
    resp = requests.get(f"{GITHUB_API}{path}", headers=HEADERS, timeout=REQUEST_TIMEOUT, **kwargs)
    resp.raise_for_status()
    return resp


def gh_post(path, json_body):
    resp = requests.post(f"{GITHUB_API}{path}", headers=HEADERS, json=json_body, timeout=REQUEST_TIMEOUT)
    return resp


def get_pr_info() -> dict:
    return gh_get(f"/repos/{REPO}/pulls/{PR_NUMBER}").json()


def get_pr_files() -> list:
    files = []
    page = 1
    while True:
        resp = gh_get(f"/repos/{REPO}/pulls/{PR_NUMBER}/files", params={"per_page": 100, "page": page})
        batch = resp.json()
        files.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return files


def get_existing_label_names() -> set:
    names = set()
    page = 1
    while True:
        resp = gh_get(f"/repos/{REPO}/labels", params={"per_page": 100, "page": page})
        batch = resp.json()
        names |= {label["name"] for label in batch}
        if len(batch) < 100:
            break
        page += 1
    return names


def ensure_labels_exist(needed_labels: set) -> None:
    """Create any needed labels that don't already exist yet, with color + description.
    Does not touch labels that already exist, so manual customization is preserved."""
    existing = get_existing_label_names()
    for label in needed_labels:
        if label in existing:
            continue
        color, description = LABEL_DEFINITIONS.get(label, ("ededed", ""))
        resp = gh_post(
            f"/repos/{REPO}/labels",
            {"name": label, "color": color, "description": description},
        )
        if resp.status_code == 201:
            print(f"Created label: {label}")
        elif resp.status_code == 422:
            # Race condition: created by a concurrent run between our check and now. Fine.
            pass
        else:
            print(f"Warning: could not create label '{label}': {resp.status_code} {resp.text}", file=sys.stderr)


def size_label(total_changes: int) -> str:
    for limit, label in SIZE_THRESHOLDS:
        if total_changes <= limit:
            return label
    return "size/XL"


def path_based_labels(files: list) -> set:
    labels = set()
    for f in files:
        path = f.get("filename", "")
        for patterns, label in PATH_LABEL_RULES:
            if any(p in path for p in patterns):
                labels.add(label)
    return labels


def ai_type_label(title: str, body: str) -> str | None:
    prompt = f"""Given this pull request title and description, respond with exactly
ONE word from this list that best fits, and nothing else: bug, feature,
enhancement, refactor, chore.

Title: {title}
Description: {body or "(none)"}
"""
    try:
        resp = requests.post(
            MODELS_API,
            headers={
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Content-Type": "application/json",
            },
            json={
                "model": MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 10,
            },
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code == 429:
            print("AI fallback skipped: rate limited by GitHub Models free tier.", file=sys.stderr)
            return None
        resp.raise_for_status()
        label = resp.json()["choices"][0]["message"]["content"].strip().lower().strip(".")
        return label if label in AI_ALLOWED_LABELS else None
    except Exception as e:
        print(f"AI fallback skipped: {e}", file=sys.stderr)
        return None


def apply_labels(labels: set) -> None:
    if not labels:
        print("No labels to apply.")
        return
    resp = gh_post(f"/repos/{REPO}/issues/{PR_NUMBER}/labels", {"labels": sorted(labels)})
    resp.raise_for_status()
    print(f"Applied labels: {sorted(labels)}")


def main():
    pr = get_pr_info()
    files = get_pr_files()

    total_changes = pr.get("additions", 0) + pr.get("deletions", 0)
    labels = {size_label(total_changes)}
    labels |= path_based_labels(files)

    content_type_labels = {"documentation", "ci/cd", "dependencies", "frontend", "backend"}
    if ENABLE_AI_FALLBACK and not (labels & content_type_labels):
        suggestion = ai_type_label(pr.get("title", ""), pr.get("body", ""))
        if suggestion:
            labels.add(suggestion)

    ensure_labels_exist(labels)
    apply_labels(labels)


if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as e:
        body = e.response.text if e.response is not None else ""
        print(f"Auto-labeler failed: {e} — {body}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Auto-labeler failed: {e}", file=sys.stderr)
        sys.exit(1)
