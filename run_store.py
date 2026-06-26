import json
import os
from datetime import datetime

STORE_PATH = "./run_history.json"

def _load() -> list:
    if not os.path.exists(STORE_PATH):
        return []
    with open(STORE_PATH) as f:
        return json.load(f)

def _save(runs: list):
    with open(STORE_PATH, "w") as f:
        json.dump(runs, f, indent=2)

def create_run(task_id: str, instructions: str, file_names: list) -> dict:
    run = {
        "task_id": task_id,
        "instructions": instructions[:200],
        "file_names": file_names,
        "status": "running",
        "outcome": None,
        "pr_url": None,
        "error": None,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat()
    }
    runs = _load()
    runs.insert(0, run)
    _save(runs)
    return run

def update_run(task_id: str, **kwargs):
    runs = _load()
    for run in runs:
        if run["task_id"] == task_id:
            run.update(kwargs)
            run["updated_at"] = datetime.utcnow().isoformat()
            break
    _save(runs)

def get_runs() -> list:
    return _load()

def get_run(task_id: str) -> dict | None:
    for run in _load():
        if run["task_id"] == task_id:
            return run
    return None