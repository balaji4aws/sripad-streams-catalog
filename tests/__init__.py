"""Test package.

The scripts in `src/` are standalone command line tools rather than an
installed package, so `src/` is put on the import path here. Importing this
package is the first thing `unittest discover` does, which makes this the one
place that needs to know about the layout.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
