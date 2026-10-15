"""Atomic file writes shared by the editors of rules.yaml, budgets.yaml and the encrypted files."""

import os
import stat
import tempfile
from pathlib import Path

NEW_FILE_MODE = 0o600  # personal finance files: private by default


def write_bytes_atomic(path: Path, data: bytes) -> None:
    """Replace `path` with `data` so readers never see a half-written file.

    An existing file keeps its permissions (mkstemp would silently make it 0600).
    """
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else NEW_FILE_MODE
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_text_atomic(path: Path, text: str) -> None:
    write_bytes_atomic(path, text.encode("utf-8"))
