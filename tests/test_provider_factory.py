from pathlib import Path

import pytest

from lego_manual_downloader import provider_factory
from lego_manual_downloader.config import BricksetConfig, Config, ConfigError, ProvidersConfig
from lego_manual_downloader.lego import LegoSet
from lego_manual_downloader.provider_factory import ProviderFactory
from lego_manual_downloader.providers import ManualProvider, OwnedSetsProvider


class FakeBoth(OwnedSetsProvider, ManualProvider):
    """Stands in for Brickset: serves both roles."""

    instances_created = 0

    def __init__(self, config: Config) -> None:
        self.config = config
        self.downloads: list[str] = []
        FakeBoth.instances_created += 1

    def get_owned_sets(self) -> list[LegoSet]:
        return [LegoSet("1", "One", "2001")]

    def download_manual(self, lego_set: LegoSet, output_path: Path) -> bool:
        self.downloads.append(lego_set.number)
        return True


class FakeManualOnly(ManualProvider):
    def __init__(self, config: Config) -> None:
        self.config = config

    def download_manual(self, lego_set: LegoSet, output_path: Path) -> bool:
        return False


class FakeUnconfigurable(ManualProvider):
    def __init__(self, config: Config) -> None:
        raise ValueError("needs a 'fake' section in config")

    def download_manual(self, lego_set: LegoSet, output_path: Path) -> bool:
        return True


@pytest.fixture
def fake_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeBoth.instances_created = 0
    monkeypatch.setattr(
        provider_factory,
        "_provider_registry",
        {"both": FakeBoth, "manualonly": FakeManualOnly, "broken": FakeUnconfigurable},
    )


def config_with(owned: tuple[str, ...], manual: tuple[str, ...]) -> Config:
    return Config(providers=ProvidersConfig(owned_sets_providers=owned, manual_providers=manual))


@pytest.mark.usefixtures("fake_registry")
class TestCreate:
    def test_builds_both_roles(self) -> None:
        factory = ProviderFactory.create(config_with(("both",), ("both",)))
        assert len(factory.sets_providers) == 1
        assert len(factory.manual_providers) == 1

    def test_provider_in_both_roles_is_instantiated_once(self) -> None:
        factory = ProviderFactory.create(config_with(("both",), ("both",)))
        assert FakeBoth.instances_created == 1
        assert id(factory.sets_providers[0]) == id(factory.manual_providers[0])

    def test_names_are_case_insensitive(self) -> None:
        factory = ProviderFactory.create(config_with(("BOTH",), ("Both",)))
        assert len(factory.sets_providers) == 1

    def test_unknown_name_warns_and_is_skipped(self, capsys: pytest.CaptureFixture[str]) -> None:
        ProviderFactory.create(config_with(("both",), ("both", "nosuch")))
        assert "Unknown provider 'nosuch'" in capsys.readouterr().out

    def test_wrong_role_warns_once(self, capsys: pytest.CaptureFixture[str]) -> None:
        factory = ProviderFactory.create(
            config_with(("both", "manualonly"), ("manualonly", "both"))
        )
        output = capsys.readouterr().out
        assert output.count("not a valid owned sets provider") == 1
        assert [type(p) for p in factory.sets_providers] == [FakeBoth]

    def test_unconfigurable_provider_is_skipped_not_fatal(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        factory = ProviderFactory.create(config_with(("both",), ("both", "broken")))
        assert "Provider 'broken' is unavailable" in capsys.readouterr().out
        assert len(factory.manual_providers) == 1

    def test_no_usable_sets_provider_raises(self) -> None:
        with pytest.raises(ConfigError, match="owned sets"):
            ProviderFactory.create(config_with(("nosuch",), ("both",)))

    def test_no_usable_manual_provider_raises(self) -> None:
        with pytest.raises(ConfigError, match="manual"):
            ProviderFactory.create(config_with(("both",), ("nosuch",)))

    def test_duplicate_names_build_one_instance(self) -> None:
        ProviderFactory.create(config_with(("both", "both"), ("both",)))
        assert FakeBoth.instances_created == 1


class TestGetOwnedSets:
    def test_returns_first_non_empty_result(self) -> None:
        class Empty(OwnedSetsProvider):
            def get_owned_sets(self) -> list[LegoSet]:
                return []

        expected = [LegoSet("1", "One", "2001")]
        factory = ProviderFactory([Empty(), FakeBoth(Config())], [])
        assert factory.get_owned_sets() == expected

    def test_falls_through_a_raising_provider(self, capsys: pytest.CaptureFixture[str]) -> None:
        class Boom(OwnedSetsProvider):
            def get_owned_sets(self) -> list[LegoSet]:
                raise RuntimeError("network down")

        factory = ProviderFactory([Boom(), FakeBoth(Config())], [])
        assert factory.get_owned_sets() == [LegoSet("1", "One", "2001")]
        assert "network down" in capsys.readouterr().out

    def test_returns_empty_when_every_provider_fails(self) -> None:
        class Boom(OwnedSetsProvider):
            def get_owned_sets(self) -> list[LegoSet]:
                raise RuntimeError("nope")

        assert ProviderFactory([Boom()], []).get_owned_sets() == []

    def test_returns_empty_with_no_providers(self) -> None:
        assert ProviderFactory([], []).get_owned_sets() == []


class TestDownloadManual:
    def test_stops_at_the_first_success(self, tmp_path: Path) -> None:
        winner = FakeBoth(Config())
        loser = FakeBoth(Config())
        factory = ProviderFactory([], [winner, loser])
        assert factory.download_manual(LegoSet("1", "One", "2001"), tmp_path / "x.pdf")
        assert winner.downloads == ["1"]
        assert loser.downloads == []

    def test_falls_through_a_provider_returning_false(self, tmp_path: Path) -> None:
        succeeding = FakeBoth(Config())
        factory = ProviderFactory([], [FakeManualOnly(Config()), succeeding])
        assert factory.download_manual(LegoSet("1", "One", "2001"), tmp_path / "x.pdf")
        assert succeeding.downloads == ["1"]

    def test_falls_through_a_raising_provider(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        class Boom(ManualProvider):
            def download_manual(self, lego_set: LegoSet, output_path: Path) -> bool:
                raise RuntimeError("timeout")

        factory = ProviderFactory([], [Boom(), FakeBoth(Config())])
        assert factory.download_manual(LegoSet("1", "One", "2001"), tmp_path / "x.pdf")
        assert "timeout" in capsys.readouterr().out

    def test_error_message_names_the_provider_class(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        class Boom(ManualProvider):
            def download_manual(self, lego_set: LegoSet, output_path: Path) -> bool:
                raise RuntimeError("timeout")

        ProviderFactory([], [Boom()]).download_manual(LegoSet("1", "a", "b"), tmp_path / "x")
        output = capsys.readouterr().out
        assert "Boom" in output
        assert "object at 0x" not in output

    def test_returns_false_when_nothing_succeeds(self, tmp_path: Path) -> None:
        factory = ProviderFactory([], [FakeManualOnly(Config())])
        assert not factory.download_manual(LegoSet("1", "One", "2001"), tmp_path / "x.pdf")


def test_real_registry_maps_the_shipped_providers() -> None:
    from lego_manual_downloader.brickset import Brickset
    from lego_manual_downloader.peeron import Peeron

    assert provider_factory._provider_registry == {"brickset": Brickset, "peeron": Peeron}


def test_brickset_serves_both_roles_and_peeron_only_manuals() -> None:
    from lego_manual_downloader.brickset import Brickset
    from lego_manual_downloader.peeron import Peeron

    assert issubclass(Brickset, OwnedSetsProvider)
    assert issubclass(Brickset, ManualProvider)
    assert issubclass(Peeron, ManualProvider)
    assert not issubclass(Peeron, OwnedSetsProvider)


def test_brickset_requires_its_config_section() -> None:
    from lego_manual_downloader.brickset import Brickset

    with pytest.raises(ValueError, match="brickset"):
        Brickset(Config())


def test_peeron_requires_its_config_section() -> None:
    from lego_manual_downloader.peeron import Peeron

    with pytest.raises(ValueError, match="peeron"):
        Peeron(Config(brickset=BricksetConfig(username="u", password="p")))
