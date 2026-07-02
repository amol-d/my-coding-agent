# from dotenv import load_dotenv
#
# load_dotenv()
#
# from github import Github, GithubException
# import os
# import json
# import re
#
#
# def _normalize_repo_name(raw: str) -> str:
#     """Accept 'owner/repo' or 'https://github.com/owner/repo(.git)'."""
#     value = raw.strip().rstrip("/")
#     if value.startswith("http://") or value.startswith("https://"):
#         value = value.split("github.com/", 1)[-1]
#     if value.endswith(".git"):
#         value = value[:-4]
#     return value
#
#
# def _repo_access_error(repo_name: str, exc: GithubException) -> str:
#     status = getattr(exc, "status", None)
#     if status == 404:
#         return (
#             f"Could not access repo '{repo_name}' (404). Check that:\n"
#             f"  - GITHUB_REPO is 'owner/repo' (no .git suffix), e.g. amol-d/SSE\n"
#             f"  - The repository exists under your GitHub account/org\n"
#             f"  - GITHUB_TOKEN is valid and has 'repo' scope for private repos"
#         )
#     if status == 401:
#         return (
#             f"GitHub authentication failed for repo '{repo_name}'. "
#             "Regenerate GITHUB_TOKEN with repo scope."
#         )
#     return f"Could not access repo {repo_name}: {exc}"
#
#
# def pr_agent(state: dict) -> dict:
#     token = os.environ.get("GITHUB_TOKEN")
#     repo_name = _normalize_repo_name(os.environ.get("GITHUB_REPO", ""))
#
#     if not token or not repo_name:
#         return {
#             "error": (
#                 "GITHUB_TOKEN or GITHUB_REPO not set. "
#                 "Set GITHUB_REPO to owner/repo, e.g. amol-d/my-coding-agent"
#             ),
#             "current_stage": "error",
#         }
#
#     if not re.fullmatch(r"[^/]+/[^/]+", repo_name):
#         return {
#             "error": (
#                 f"Invalid GITHUB_REPO '{repo_name}'. "
#                 "Use owner/repo format, e.g. amol-d/SSE"
#             ),
#             "current_stage": "error",
#         }
#
#     generated_code = state.get("generated_code", {})
#     review_comments = state.get("review_comments", [])
#     test_results = state.get("test_results", {"passed": False, "output": ""})
#     clarified_spec = (
#             state.get("clarified_spec")
#             or state.get("raw_instructions")
#             or "Agent task"
#     )
#     task_id = state.get("task_id", "unknown")
#
#     g = Github(token)
#
#     try:
#         repo = g.get_repo(repo_name)
#     except GithubException as e:
#         return {
#             "error": _repo_access_error(repo_name, e),
#             "current_stage": "error",
#         }
#
#     branch_name = f"agent/{task_id[:8]}"
#
#     try:
#         base = repo.get_branch("main")
#     except GithubException:
#         try:
#             base = repo.get_branch("master")
#         except GithubException as e:
#             return {
#                 "error": f"Could not find main or master branch: {str(e)}",
#                 "current_stage": "error"
#             }
#
#     # create branch — skip if it already exists
#     try:
#         repo.create_git_ref(f"refs/heads/{branch_name}", base.commit.sha)
#     except GithubException as e:
#         if "already exists" not in str(e).lower():
#             return {
#                 "error": f"Could not create branch: {str(e)}",
#                 "current_stage": "error"
#             }
#
#     # commit each generated file
#     for filepath, content in generated_code.items():
#         filepath = filepath.lstrip("/")
#         if not isinstance(content, str):
#             content = json.dumps(content, indent=2)
#         try:
#             existing = repo.get_contents(filepath, ref=branch_name)
#             repo.update_file(
#                 filepath,
#                 f"agent: update {filepath}",
#                 content,
#                 existing.sha,
#                 branch=branch_name
#             )
#         except GithubException:
#             repo.create_file(
#                 filepath,
#                 f"agent: add {filepath}",
#                 content,
#                 branch=branch_name
#             )
#
#     # build PR body
#     if review_comments:
#         comments_summary = "\n".join(
#             f"- [{c.get('severity', 'suggestion').upper()}] "
#             f"{c.get('file', 'general')}: {c.get('comment', '')}"
#             for c in review_comments
#         )
#     else:
#         comments_summary = "No issues found."
#
#     test_status = "✅ All tests passed" if test_results.get("passed") else "❌ Tests failed"
#     test_output = test_results.get("output", "")[:1000]
#
#     pr_body = f"""## Summary
# {clarified_spec}
#
# ## Review notes
# {comments_summary}
#
# ## Test results
# {test_status}
# {test_output}"""
#     try:
#         pr = repo.create_pull(
#             title=f"[Agent] {clarified_spec[:60]}",
#             body=pr_body,
#             head=branch_name,
#             base=base.name
#         )
#     except GithubException as e:
#         return {
#             "error": f"Could not create PR: {str(e)}",
#             "current_stage": "error"
#         }
#
#     return {
#         "pr_url": pr.html_url,
#         "current_stage": "pr_created"
#     }

from dotenv import load_dotenv

load_dotenv()

from github import Github, GithubException
import os
from events import emit
from tools.local_repo import git_push, git_current_branch

STAGE = "pr_manager"


def pr_agent(state: dict) -> dict:
    task_id = state.get("task_id", "unknown")
    want_pr = bool((state.get("options", {}) or {}).get("create_pr"))
    emit(task_id, "stage_started",
         action="Pushing branch and opening PR" if want_pr else "Pushing branch",
         node=STAGE)

    # branch_name is set by the coding node; for a pure git-ops request there is
    # no coding step, so fall back to the repo's current branch.
    branch_name = state.get("branch_name") or git_current_branch()
    if not branch_name:
        emit(task_id, "error", message="Could not determine branch to push", node=STAGE)
        return {"error": "Could not determine branch to push", "current_stage": "error"}

    clarified_spec = (
            state.get("clarified_spec")
            or state.get("raw_instructions")
            or "Agent task"
    )
    review_comments = state.get("review_comments", [])
    test_results = state.get("test_results", {"passed": False, "output": ""})
    written_files = state.get("written_files", [])

    # push the branch (commit, if any, already happened in the commit node)
    emit(task_id, "stage_progress", action=f"Pushing {branch_name} to origin", node=STAGE)
    ok, msg = git_push(branch_name)
    if not ok:
        emit(task_id, "error", message=f"Push failed: {msg}", node=STAGE)
        return {"error": f"Push failed: {msg}", "current_stage": "error"}

    # push-only request (no PR asked for) — stop here.
    if not want_pr:
        emit(task_id, "node_complete", node=STAGE, action=f"Pushed {branch_name}")
        return {"current_stage": "pushed"}

    token = os.environ.get("GITHUB_TOKEN")
    repo_name = os.environ.get("GITHUB_REPO")
    if not token or not repo_name:
        emit(task_id, "error", message="GITHUB_TOKEN or GITHUB_REPO not set", node=STAGE)
        return {"error": "GITHUB_TOKEN or GITHUB_REPO not set", "current_stage": "error"}

    # create PR via GitHub API
    g = Github(token)
    try:
        repo = g.get_repo(repo_name)
    except GithubException as e:
        return {"error": f"Could not access repo: {str(e)}", "current_stage": "error"}

    # Resolve the PR base branch. The user's natural-language target ("open PR to
    # dev") wins over DEFAULT_BRANCH; master is only a fallback when nothing was
    # specified. If the user explicitly named a branch that doesn't exist, say so
    # rather than silently retargeting the PR somewhere else.
    requested_base = state.get("base_branch")
    base_branch = requested_base or os.environ.get("DEFAULT_BRANCH", "main")
    try:
        repo.get_branch(base_branch)          # validate the base branch exists
    except GithubException:
        if requested_base:
            msg = f"Base branch '{requested_base}' does not exist on {repo_name}."
            emit(task_id, "error", message=msg, node=STAGE)
            return {"error": msg, "current_stage": "error"}
        try:
            repo.get_branch("master")
            base_branch = "master"
        except GithubException as e:
            return {"error": f"Could not find base branch: {str(e)}", "current_stage": "error"}

    # A PR cannot go from a branch into itself — this is the usual cause of
    # GitHub's "422 base invalid" when pushing the current branch.
    if branch_name == base_branch:
        msg = (f"Cannot open a PR from '{branch_name}' into itself — the current "
               f"branch is the same as the target base branch '{base_branch}'. "
               f"Specify a different target (e.g. 'open PR to dev').")
        emit(task_id, "error", message=msg, node=STAGE)
        return {"error": msg, "current_stage": "error"}

    # build PR body
    files_list = "\n".join(f"- `{f}`" for f in written_files)

    if review_comments:
        comments_summary = "\n".join(
            f"- [{c.get('severity', 'suggestion').upper()}] "
            f"`{c.get('file', 'general')}`: {c.get('comment', '')}"
            for c in review_comments
        )
    else:
        comments_summary = "No issues found."

    test_status = "✅ All tests passed" if test_results.get("passed") else "❌ Tests failed"
    test_cmd = test_results.get("test_command", "")
    test_output = test_results.get("output", "")[:1000]
    test_files = test_results.get("test_files", {})
    test_files_list = "\n".join(f"- `{f}`" for f in test_files.keys())

    pr_body = f"""## Summary
{clarified_spec}

## Files changed
{files_list or "None"}

## Unit tests added
{test_files_list or "None"}

## Review notes
{comments_summary}

## Test results
{test_status}
Command: `{test_cmd}`

```
{test_output}
```"""

    try:
        pr = repo.create_pull(
            title=f"[Agent] {clarified_spec[:60]}",
            body=pr_body,
            head=branch_name,
            base=base_branch
        )
    except GithubException as e:
        # GitHub's 422 "base invalid" is opaque; add the concrete head→base context.
        detail = f"Could not create PR ({branch_name} → {base_branch}): {str(e)}"
        emit(task_id, "error", message=detail, node=STAGE)
        return {"error": detail, "current_stage": "error"}

    emit(task_id, "node_complete", node=STAGE, action="Pull request created")
    return {
        "pr_url": pr.html_url,
        "current_stage": "pr_created"
    }
