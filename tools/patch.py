"""Patch-based file editing for the agentic coding loop.

Instead of regenerating whole files (which truncates at the model's token
ceiling and can silently corrupt large files), the agent proposes small
search/replace edits. Each edit's ``find`` string must match the current file
content **exactly once** — 0 matches or >1 matches are rejected so the model
must disambiguate rather than guess.
"""

from tools.local_repo import read_file, write_file


def apply_patch(path: str, edits: list) -> str:
    """Apply a list of {find, replace} edits to an existing file.

    Returns a human/agent-readable result string (success or a specific error
    the model can act on). The file is only written if every edit applies
    cleanly, so a bad patch never leaves the file half-edited.
    """
    path = path.lstrip("/")
    content = read_file(path)
    if content is None:
        return f"ERROR: file '{path}' does not exist. Use create_file for new files."

    if not isinstance(edits, list) or not edits:
        return "ERROR: 'edits' must be a non-empty list of {find, replace} objects."

    new_content = content
    for i, edit in enumerate(edits):
        if not isinstance(edit, dict) or "find" not in edit or "replace" not in edit:
            return f"ERROR: edit #{i} must be an object with 'find' and 'replace'."
        find = edit["find"]
        replace = edit["replace"]
        if find == "":
            return f"ERROR: edit #{i} has an empty 'find'."
        count = new_content.count(find)
        if count == 0:
            return (
                f"ERROR: edit #{i} 'find' text was not found in {path}. "
                "Read the file again and copy the exact current text."
            )
        if count > 1:
            return (
                f"ERROR: edit #{i} 'find' text matches {count} times in {path}. "
                "Include more surrounding context so it matches exactly once."
            )
        new_content = new_content.replace(find, replace, 1)

    write_file(path, new_content)
    return f"Applied {len(edits)} edit(s) to {path}."
