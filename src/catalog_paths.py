#!/usr/bin/env python3
"""Shared path helpers.

Every script in this project takes its input and output locations as command
line arguments, and the defaults are expressed relative to the repository
root rather than the current working directory. That means the scripts behave
the same whether they are run as ``python3 src/categorize.py`` from the
repository root or as ``python3 categorize.py`` from inside ``src/``.
"""

from pathlib import Path

#: Repository root, i.e. the directory containing ``src/``, ``data/`` and ``output/``.
REPO_ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = REPO_ROOT / "data"
OUTPUT_DIR = REPO_ROOT / "output"

RAW_PLAYLIST = DATA_DIR / "raw_playlist.json"
KNOWN_UPLOAD_DATES = DATA_DIR / "known_upload_dates.json"
STREAMS_MASTER_JSON = OUTPUT_DIR / "streams_master.json"
CATALOG_META_JSON = OUTPUT_DIR / "catalog_meta.json"
SEQUENCES_JSON = OUTPUT_DIR / "sequences.json"


def resolve(path_arg: str) -> Path:
    """Resolve a user-supplied path.

    Absolute paths are used as given. Relative paths are interpreted relative
    to the repository root, not the current working directory, so that the
    documented commands work from any directory.
    """
    path = Path(path_arg).expanduser()
    return path if path.is_absolute() else (REPO_ROOT / path)
