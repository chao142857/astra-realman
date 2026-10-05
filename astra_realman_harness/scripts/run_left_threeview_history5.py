#!/usr/bin/env python3
"""Separate three-view/history5 profile using the unmodified existing runner."""
import importlib.util
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from io_utils import ROOT, write_json
from history5_context import History5ContextBuilder

def main():
    spec = importlib.util.spec_from_file_location("history5_threeview_runner", ROOT/"scripts/run_left_terminal.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    runner.model_input = History5ContextBuilder(runner.model_input)
    original_new_run = runner.new_run
    def profile_run(path):
        path = Path(path)
        top = path.parent == ROOT/"logs" and path.name.startswith("left-terminal-")
        if top:
            path = path.with_name(path.name.replace("left-terminal-", "left-threeview-history5-", 1))
        created = original_new_run(path)
        if top:
            write_json(created/"history_profile.json", {
                "profile": "threeview_history5", "max_previous_rounds": 5,
                "order": "oldest_to_newest", "contents": "original action and result",
                "historical_images": False, "existing_previous_retained": True
            })
        return created
    runner.new_run = profile_run
    return runner.main()

if __name__ == "__main__":
    sys.exit(main())
