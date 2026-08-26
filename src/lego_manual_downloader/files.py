import os
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import IO


@contextmanager
def atomic_write(output_path: Path) -> Generator[IO[bytes], None, None]:
    """Yield a temp file beside output_path, renamed into place only on a
    complete write.

    The temp file shares a filesystem with the destination so the rename is
    atomic: failure or other interruption does not leave a partial file behind.
    """
    tmp_fd, tmp_name = tempfile.mkstemp(dir=output_path.parent, suffix=".part")
    try:
        with os.fdopen(tmp_fd, "wb") as tmp_file:
            yield tmp_file
        os.chmod(tmp_name, 0o644)
        os.replace(tmp_name, output_path)
    finally:
        Path(tmp_name).unlink(missing_ok=True)
