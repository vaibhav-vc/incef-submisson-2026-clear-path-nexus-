"""Resource bounds for captured JSON, not railway engineering limits.

Each submitted object is limited to 64 KiB of compact UTF-8 JSON, 16 levels
below its root, and 4096 nodes (including object keys). Limits apply before
canonical hashing/database writes; they do not replace HTTP body-size limits.
"""

import json
import math


MAX_JSON_BYTES = 64 * 1024
MAX_JSON_DEPTH = 16
MAX_JSON_NODES = 4096


def bounded_json_object(value: object) -> dict:
    """Validate iteratively, rejecting non-JSON values without coercion."""
    if not isinstance(value, dict):
        raise ValueError("captured JSON must be an object")
    stack = [(value, 0, False)]
    active: set[int] = set()
    nodes = 0
    encoded_bytes = 0
    while stack:
        item, depth, leaving = stack.pop()
        if leaving:
            active.remove(id(item))
            continue
        nodes += 1
        if nodes > MAX_JSON_NODES:
            raise ValueError(f"captured JSON exceeds {MAX_JSON_NODES} nodes")
        if depth > MAX_JSON_DEPTH:
            raise ValueError(f"captured JSON exceeds depth {MAX_JSON_DEPTH}")
        if isinstance(item, (dict, list)):
            if id(item) in active:
                raise ValueError("captured JSON cannot contain cycles")
            child_count = len(item) * (2 if isinstance(item, dict) else 1)
            if nodes + child_count > MAX_JSON_NODES:
                raise ValueError(f"captured JSON exceeds {MAX_JSON_NODES} nodes")
            active.add(id(item))
            stack.append((item, depth, True))
            encoded_bytes += 2 + max(0, len(item) - 1)
            if isinstance(item, dict):
                encoded_bytes += len(item)  # colons
                for key, child in item.items():
                    if not isinstance(key, str):
                        raise ValueError("captured JSON object keys must be strings")
                    stack.append((key, depth + 1, False))
                    stack.append((child, depth + 1, False))
            else:
                stack.extend((child, depth + 1, False) for child in item)
        else:
            if not (item is None or type(item) in (str, int, float, bool)):
                raise ValueError("captured JSON contains a non-JSON value")
            if isinstance(item, float) and not math.isfinite(item):
                raise ValueError("captured JSON numbers must be finite")
            if isinstance(item, str) and len(item) > MAX_JSON_BYTES:
                raise ValueError(f"captured JSON exceeds {MAX_JSON_BYTES} UTF-8 bytes")
            try:
                encoded_bytes += len(json.dumps(
                    item, ensure_ascii=False, allow_nan=False, separators=(",", ":")
                ).encode("utf-8"))
            except (ValueError, UnicodeError) as exc:
                raise ValueError("captured JSON contains an invalid JSON scalar") from exc
        if encoded_bytes > MAX_JSON_BYTES:
            raise ValueError(f"captured JSON exceeds {MAX_JSON_BYTES} UTF-8 bytes")
    return value
