from pathlib import Path

import pytest

from lego_manual_downloader.lego import LegoSet


def test_set_number_joins_number_and_variant() -> None:
    assert LegoSet("10179", "2", "Millennium Falcon", "2007").set_number == "10179-2"


def test_file_name_format() -> None:
    assert LegoSet("10179", "1", "Millennium Falcon", "2007").file_name == (
        "10179-1 Millennium Falcon (2007).pdf"
    )


def test_file_name_carries_the_variant() -> None:
    """Two variants of one set number must not claim the same file."""
    first = LegoSet("10179", "1", "Millennium Falcon", "2007").file_name
    second = LegoSet("10179", "2", "Millennium Falcon", "2007").file_name
    assert first != second
    assert second.startswith("10179-2 ")


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
    file_name = LegoSet("1234", "1", name, "1999").file_name
    assert "/" not in file_name
    assert "\\" not in file_name
    assert Path(file_name).name == file_name
    assert Path(file_name).parent == Path(".")


@pytest.mark.parametrize("variant", ["../1", "1/2", "..\\1"])
def test_variant_is_sanitised_too(variant: str) -> None:
    """The variant comes from the same untrusted CSV as the name."""
    file_name = LegoSet("1234", variant, "Whatever", "1999").file_name
    assert "/" not in file_name
    assert "\\" not in file_name
    assert Path(file_name).name == file_name


def test_file_name_is_not_absolute() -> None:
    file_name = LegoSet("1234", "1", "/etc/passwd", "1999").file_name
    assert not Path(file_name).is_absolute()


def test_file_name_preserves_unicode() -> None:
    assert "Ärger" in LegoSet("1234", "1", "Ärger", "1999").file_name


def test_file_name_keeps_pdf_extension() -> None:
    assert LegoSet("1234", "1", "Whatever", "1999").file_name.endswith(".pdf")


def test_lego_set_is_frozen() -> None:
    lego_set = LegoSet("1234", "1", "Name", "1999")
    with pytest.raises(AttributeError):
        lego_set.number = "9999"  # type: ignore[misc]


def test_lego_set_equality() -> None:
    assert LegoSet("1", "1", "a", "2") == LegoSet("1", "1", "a", "2")
    assert LegoSet("1", "1", "a", "2") != LegoSet("1", "1", "a", "3")
    assert LegoSet("1", "1", "a", "2") != LegoSet("1", "2", "a", "2")


def test_str_describes_the_set() -> None:
    assert str(LegoSet("10179", "1", "Millennium Falcon", "2007")) == (
        "10179-1 - Millennium Falcon (2007)"
    )
