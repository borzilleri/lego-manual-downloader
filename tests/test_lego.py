from pathlib import Path

import pytest

from lego_manual_downloader.lego import LegoSet


def test_file_name_format() -> None:
    assert LegoSet("10179", "Millennium Falcon", "2007").file_name == (
        "10179 Millennium Falcon (2007).pdf"
    )


@pytest.mark.parametrize(
    "name",
    [
        "King's Castle / Fort",
        "Robot: Mark II",
        "Space<>Ship",
        "Back\\Slash",
        "Pipe|Name",
        'Quote"Name',
        "Star*Wars?",
    ],
)
def test_file_name_stays_a_single_path_component(name: str) -> None:
    """A separator in a set name must not redirect the write into a subdirectory."""
    file_name = LegoSet("1234", name, "1999").file_name
    assert "/" not in file_name
    assert "\\" not in file_name
    assert Path(file_name).name == file_name
    assert Path(file_name).parent == Path(".")


def test_file_name_is_not_absolute() -> None:
    file_name = LegoSet("1234", "/etc/passwd", "1999").file_name
    assert not Path(file_name).is_absolute()


def test_file_name_preserves_unicode() -> None:
    assert "Ärger" in LegoSet("1234", "Ärger", "1999").file_name


def test_file_name_keeps_pdf_extension() -> None:
    assert LegoSet("1234", "Whatever", "1999").file_name.endswith(".pdf")


def test_lego_set_is_frozen() -> None:
    lego_set = LegoSet("1234", "Name", "1999")
    with pytest.raises(AttributeError):
        lego_set.number = "9999"  # type: ignore[misc]


def test_lego_set_equality() -> None:
    assert LegoSet("1", "a", "2") == LegoSet("1", "a", "2")
    assert LegoSet("1", "a", "2") != LegoSet("1", "a", "3")
