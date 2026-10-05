"""All harness writes are confined to this directory; no project imports."""
from pathlib import Path
import json
import math
import re

ROOT = Path(__file__).resolve().parent

def strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("DUPLICATE_JSON_KEY:" + key)
            result[key] = value
        return result
    def constant(value):
        raise ValueError("NONFINITE_JSON:" + value)
    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)

def read_json(path):
    path = Path(path)
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("JSON_TOO_LARGE")
    return strict_json(path.read_text(encoding="utf-8"))

def output_path(path):
    path = Path(path).expanduser().resolve()
    if ROOT not in path.parents:
        raise ValueError("WRITE_OUTSIDE_HARNESS")
    return path

def new_run(path):
    path = output_path(path)
    path.mkdir(parents=True, exist_ok=False)
    return path

def write_json(path, value):
    path = output_path(path)
    with path.open("x", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")

def number(value):
    return type(value) in (int, float) and math.isfinite(value)

def vector(value, length):
    return isinstance(value, list) and len(value) == length and all(number(v) for v in value)

def identifier(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value) is not None
