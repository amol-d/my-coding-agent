from dotenv import load_dotenv

load_dotenv()

from github import Github, GithubException
import os
import json
import re


def _normalize_repo_name(raw: str) -> str:
    """Accept 'owner/repo' or 'https://github.com/owner/repo(.git)'."""
    value = raw.strip().rstrip("/")
    if value.startswith("http://") or value.startswith("https://"):
        value = value.split("github.com/", 1)[-1]
    if value.endswith(".git"):
        value = value[:-4]
    return value


def _repo_access_error(repo_name: str, exc: GithubException) -> str:
    status = getattr(exc, "status", None)
    if status == 404:
        return (
            f"Could not access repo '{repo_name}' (404). Check that:\n"
            f"  - GITHUB_REPO is 'owner/repo' (no .git suffix), e.g. amol-d/SSE\n"
            f"  - The repository exists under your GitHub account/org\n"
            f"  - GITHUB_TOKEN is valid and has 'repo' scope for private repos"
        )
    if status == 401:
        return (
            f"GitHub authentication failed for repo '{repo_name}'. "
            "Regenerate GITHUB_TOKEN with repo scope."
        )
    return f"Could not access repo {repo_name}: {exc}"


def pr_agent(state: dict) -> dict:
    token = os.environ.get("GITHUB_TOKEN")
    repo_name = _normalize_repo_name(os.environ.get("GITHUB_REPO", ""))

    if not token or not repo_name:
        return {
            "error": (
                "GITHUB_TOKEN or GITHUB_REPO not set. "
                "Set GITHUB_REPO to owner/repo, e.g. amol-d/my-coding-agent"
            ),
            "current_stage": "error",
        }

    if not re.fullmatch(r"[^/]+/[^/]+", repo_name):
        return {
            "error": (
                f"Invalid GITHUB_REPO '{repo_name}'. "
                "Use owner/repo format, e.g. amol-d/SSE"
            ),
            "current_stage": "error",
        }

    generated_code = state.get("generated_code", {})
    review_comments = state.get("review_comments", [])
    test_results = state.get("test_results", {"passed": False, "output": ""})
    clarified_spec = (
            state.get("clarified_spec")
            or state.get("raw_instructions")
            or "Agent task"
    )
    task_id = state.get("task_id", "unknown")

    g = Github(token)

    try:
        repo = g.get_repo(repo_name)
    except GithubException as e:
        return {
            "error": _repo_access_error(repo_name, e),
            "current_stage": "error",
        }

    branch_name = f"agent/{task_id[:8]}"

    try:
        base = repo.get_branch("main")
    except GithubException:
        try:
            base = repo.get_branch("master")
        except GithubException as e:
            return {
                "error": f"Could not find main or master branch: {str(e)}",
                "current_stage": "error"
            }

    # create branch — skip if it already exists
    try:
        repo.create_git_ref(f"refs/heads/{branch_name}", base.commit.sha)
    except GithubException as e:
        if "already exists" not in str(e).lower():
            return {
                "error": f"Could not create branch: {str(e)}",
                "current_stage": "error"
            }

    # commit each generated file
    for filepath, content in generated_code.items():
        filepath = filepath.lstrip("/")
        if not isinstance(content, str):
            content = json.dumps(content, indent=2)
        try:
            existing = repo.get_contents(filepath, ref=branch_name)
            repo.update_file(
                filepath,
                f"agent: update {filepath}",
                content,
                existing.sha,
                branch=branch_name
            )
        except GithubException:
            repo.create_file(
                filepath,
                f"agent: add {filepath}",
                content,
                branch=branch_name
            )

    # build PR body
    if review_comments:
        comments_summary = "\n".join(
            f"- [{c.get('severity', 'suggestion').upper()}] "
            f"{c.get('file', 'general')}: {c.get('comment', '')}"
            for c in review_comments
        )
    else:
        comments_summary = "No issues found."

    test_status = "✅ All tests passed" if test_results.get("passed") else "❌ Tests failed"
    test_output = test_results.get("output", "")[:1000]

    pr_body = f"""## Summary
{clarified_spec}

## Review notes
{comments_summary}

## Test results
{test_status}
{test_output}"""
    try:
        pr = repo.create_pull(
            title=f"[Agent] {clarified_spec[:60]}",
            body=pr_body,
            head=branch_name,
            base=base.name
        )
    except GithubException as e:
        return {
            "error": f"Could not create PR: {str(e)}",
            "current_stage": "error"
        }

    return {
        "pr_url": pr.html_url,
        "current_stage": "pr_created"
    }
