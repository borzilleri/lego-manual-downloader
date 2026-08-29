from pathlib import Path

import pytest

from lego_manual_downloader.lego import LegoSet

FALCON_ENTRY = {
    "number": "10179",
    "variant": "1",
    "name": "Millennium Falcon",
    "year": "2007",
    "file": "10179-1 Millennium Falcon (2007).pdf",
}


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


class TestRecordedFileName:
    """`file_name` is where the manual belongs; `current_file_name` is where it is."""

    def test_it_does_not_change_the_derived_name(self) -> None:
        lego_set = LegoSet("10179", "1", "Millennium Falcon", "2007", "legacy name.pdf")
        assert lego_set.file_name == "10179-1 Millennium Falcon (2007).pdf"

    def test_it_is_the_current_name(self) -> None:
        lego_set = LegoSet("10179", "1", "Millennium Falcon", "2007", "legacy name.pdf")
        assert lego_set.current_file_name == "legacy name.pdf"

    def test_the_current_name_falls_back_to_the_derived_one(self) -> None:
        lego_set = LegoSet("10179", "1", "Millennium Falcon", "2007")
        assert lego_set.current_file_name == lego_set.file_name
        assert lego_set.current_file_name == "10179-1 Millennium Falcon (2007).pdf"

    @pytest.mark.parametrize("recorded", ["../escape.pdf", "..\\escape.pdf", "/etc/passwd"])
    def test_the_current_name_is_sanitised_like_a_derived_one(self, recorded: str) -> None:
        """The database is not a trusted source of paths."""
        file_name = LegoSet("1234", "1", "Whatever", "1999", recorded).current_file_name
        assert "/" not in file_name
        assert "\\" not in file_name
        assert Path(file_name).name == file_name
        assert not Path(file_name).is_absolute()

    def test_it_is_ignored_by_equality(self) -> None:
        """One set is one set, however its manual happens to be named on disk."""
        assert LegoSet("1", "1", "a", "2", "x.pdf") == LegoSet("1", "1", "a", "2")


class TestFromDict:
    def test_it_reads_every_field(self) -> None:
        lego_set = LegoSet.from_dict(FALCON_ENTRY)
        assert lego_set == LegoSet("10179", "1", "Millennium Falcon", "2007")
        assert lego_set is not None
        assert lego_set.recorded_file_name == "10179-1 Millennium Falcon (2007).pdf"

    def test_the_recorded_file_name_is_optional(self) -> None:
        lego_set = LegoSet.from_dict({k: v for k, v in FALCON_ENTRY.items() if k != "file"})
        assert lego_set is not None
        assert lego_set.recorded_file_name is None

    @pytest.mark.parametrize("missing", ["number", "variant", "name", "year"])
    def test_a_missing_required_field_yields_none(self, missing: str) -> None:
        assert LegoSet.from_dict({k: v for k, v in FALCON_ENTRY.items() if k != missing}) is None

    def test_an_empty_entry_yields_none(self) -> None:
        assert LegoSet.from_dict({}) is None


class TestToDict:
    def test_it_writes_the_persisted_schema(self) -> None:
        assert LegoSet("10179", "1", "Millennium Falcon", "2007").to_dict() == {
            "number": "10179",
            "variant": "1",
            "name": "Millennium Falcon",
            "year": "2007",
            "file": "10179-1 Millennium Falcon (2007).pdf",
        }

    def test_it_records_where_the_file_is_not_where_it_belongs(self) -> None:
        """A rename that never happened must not be written as though it had."""
        lego_set = LegoSet("10179", "1", "Millennium Falcon", "2007", "legacy name.pdf")
        assert lego_set.to_dict()["file"] == "legacy name.pdf"

    def test_it_round_trips_through_from_dict(self) -> None:
        original = LegoSet("10179", "1", "Millennium Falcon", "2007", "legacy name.pdf")
        restored = LegoSet.from_dict(original.to_dict())
        assert restored == original
        assert restored is not None
        assert restored.current_file_name == original.current_file_name
