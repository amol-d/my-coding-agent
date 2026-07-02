"""Tool definitions for the agentic coding loop.

Tools are built per run via ``make_tools(task_id, tracker)`` so they can record
which files the agent touches (for diffing) and emit progress events. The set is
intentionally small: explore (list/read/grep), edit (create_file/apply_patch),
verify (run_command), and a ``finish`` sentinel the model calls when done.
"""

from langchain_core.tools import StructuredTool

from tools.local_repo import list_repo_files, read_file, write_file, grep_repo
from tools.patch import apply_patch as _apply_patch
from tools.sandbox import run_command as _run_command

# Extensions the agent is allowed to browse when listing without a filter.
_LIST_EXTS = [".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".md", ".css", ".html"]
_MAX_FILE_CHARS = 20000
_MAX_LIST = 200


class Tracker:
    """Records the original content of every file the agent touches, once, so the
    node can build an accurate before/after diff regardless of how many edits a
    file receives during the loop."""

    def __init__(self):
        self.originals: dict[str, str] = {}

    def touch(self, path: str) -> None:
        path = path.lstrip("/")
        if path not in self.originals:
            self.originals[path] = read_file(path) or ""


def make_tools(tracker: Tracker):
    """Build the tool list for one coding run. Returns (tools, tool_map)."""

    def list_files(pattern: str = "") -> str:
        """List repository files. Optional substring/extension filter (e.g. 'src/' or '.tsx')."""
        files = list_repo_files()
        if pattern:
            files = [f for f in files if pattern in f]
        else:
            files = [f for f in files if any(f.endswith(e) for e in _LIST_EXTS)]
        files = files[:_MAX_LIST]
        return "\n".join(files) if files else "No matching files."

    def read_repo_file(path: str) -> str:
        """Read a file's current contents. Use before editing so patches match exactly."""
        content = read_file(path.lstrip("/"))
        if content is None:
            return f"ERROR: file '{path}' does not exist."
        if len(content) > _MAX_FILE_CHARS:
            return content[:_MAX_FILE_CHARS] + "\n… (file truncated; grep for specifics)"
        return content

    def grep(pattern: str) -> str:
        """Search tracked files for a regex/string. Returns path:line:text matches."""
        return grep_repo(pattern)

    def create_file(path: str, content: str) -> str:
        """Create a NEW file with the given full contents. For existing files use apply_patch."""
        path = path.lstrip("/")
        if read_file(path) is not None:
            return f"ERROR: '{path}' already exists. Use apply_patch to modify it."
        tracker.touch(path)
        write_file(path, content)
        return f"Created {path}."

    def apply_patch(path: str, edits: list) -> str:
        """Edit an existing file. 'edits' is a list of {"find","replace"}; each 'find'
        must match the current file exactly once. Read the file first to copy exact text."""
        tracker.touch(path)
        return _apply_patch(path, edits)

    def run_command(command: str) -> str:
        """Run an allowlisted command (pytest, npm/npx, tsc, ruff, read-only git) in the
        repo to verify your changes. No shell operators; output is truncated."""
        return _run_command(command)

    def finish(summary: str) -> str:
        """Call when the task is complete and all intended edits are made. 'summary'
        briefly describes what changed."""
        return "Finishing."

    specs = [
        (list_files, "list_files"),
        (read_repo_file, "read_file"),
        (grep, "grep"),
        (create_file, "create_file"),
        (apply_patch, "apply_patch"),
        (run_command, "run_command"),
        (finish, "finish"),
    ]
    tools = [
        StructuredTool.from_function(func=fn, name=name, description=fn.__doc__)
        for fn, name in specs
    ]
    tool_map = {t.name: t for t in tools}
    return tools, tool_map
