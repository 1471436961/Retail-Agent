"""Test-only temporary directories compatible with Windows inherited ACLs."""

import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4


@contextmanager
def temporary_directory():
    """Avoid Windows mkdir(0o700); retain standard behavior elsewhere.

    Windows treats 0o700 specially, replacing inherited access controls.
    Ordinary directory creation retains the temporary parent's ACL instead.
    No global mkdir patch or permission change is applied.
    """
    if os.name != "nt":
        with tempfile.TemporaryDirectory() as directory:
            yield directory
        return

    parent = Path(tempfile.gettempdir()).resolve(strict=True)
    directory = parent / ("retail-test-" + uuid4().hex)
    # Atomic creation: a collision fails rather than reusing someone else's path.
    os.mkdir(directory, 0o777)
    try:
        yield str(directory)
    finally:
        # Only recursively delete this run's ordinary child of the known parent.
        if (directory.is_symlink() or directory.is_junction()
                or directory.resolve(strict=True) != directory
                or directory.parent != parent):
            raise RuntimeError("Refusing cleanup outside the ordinary test temporary directory")
        shutil.rmtree(directory)
