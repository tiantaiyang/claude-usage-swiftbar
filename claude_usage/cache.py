"""Owner-only, atomically written snapshot of the last good usage payload.

Credentials must never reach disk, so save() refuses any record containing a
credential-shaped key at any depth.
"""

import json
import os
import re
import tempfile
from typing import Any, Dict, Optional

VERSION = 1
FORBIDDEN_KEY = re.compile(r"token|secret|password|credential", re.IGNORECASE)
FILE_MODE = 0o600


def _assert_no_credentials(value: Any, path: str = "") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str) and FORBIDDEN_KEY.search(key):
                raise ValueError(
                    "refusing to persist credential-like key at {}{}".format(
                        path, key))
            _assert_no_credentials(item, "{}{}.".format(path, key))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_no_credentials(item, "{}[{}].".format(path, index))


def save(path: str, record: Dict[str, Any]) -> None:
    """Write the record atomically with owner-only permissions."""
    _assert_no_credentials(record)
    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True)
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=directory, prefix=".snapshot-",
        suffix=".tmp", delete=False)
    try:
        with handle:
            handle.write(encoded)
        os.chmod(handle.name, FILE_MODE)
        os.replace(handle.name, path)
    except BaseException:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


def load(path: str) -> Optional[Dict[str, Any]]:
    """Return the stored record, or None if absent or unusable."""
    try:
        with open(path, encoding="utf-8") as handle:
            record = json.load(handle)
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None
