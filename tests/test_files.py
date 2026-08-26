import stat
from pathlib import Path

import pytest

from lego_manual_downloader.files import atomic_write


class TestAtomicWrite:
    def test_completed_write_lands_at_the_destination(self, tmp_path: Path) -> None:
        output = tmp_path / "manual.pdf"
        with atomic_write(output) as f:
            f.write(b"%PDF-1.4 payload")
            assert not output.exists()  # nothing is visible until the write completes

        assert output.read_bytes() == b"%PDF-1.4 payload"
        assert list(tmp_path.iterdir()) == [output]

    @pytest.mark.parametrize(
        "error", [RuntimeError, KeyboardInterrupt], ids=["failed", "interrupted"]
    )
    def test_incomplete_write_leaves_no_destination_and_no_leftovers(
        self, tmp_path: Path, error: type[BaseException]
    ) -> None:
        output = tmp_path / "manual.pdf"
        with pytest.raises(error), atomic_write(output) as f:
            f.write(b"partial")
            raise error

        assert not list(tmp_path.iterdir())

    def test_existing_destination_is_replaced(self, tmp_path: Path) -> None:
        output = tmp_path / "manual.pdf"
        output.write_bytes(b"stale")
        with atomic_write(output) as f:
            f.write(b"fresh")

        assert output.read_bytes() == b"fresh"
        assert list(tmp_path.iterdir()) == [output]

    def test_failed_write_leaves_an_existing_destination_untouched(self, tmp_path: Path) -> None:
        output = tmp_path / "manual.pdf"
        output.write_bytes(b"previously downloaded")
        with pytest.raises(RuntimeError), atomic_write(output) as f:
            f.write(b"partial")
            raise RuntimeError

        assert output.read_bytes() == b"previously downloaded"
        assert list(tmp_path.iterdir()) == [output]

    def test_destination_is_readable_not_just_owner_only(self, tmp_path: Path) -> None:
        output = tmp_path / "manual.pdf"
        with atomic_write(output) as f:
            f.write(b"payload")

        assert stat.S_IMODE(output.stat().st_mode) == 0o644
