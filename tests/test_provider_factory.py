from pathlib import Path
from typing import ClassVar

import pytest

from lego_manual_downloader import provider_factory
from lego_manual_downloader.config import (
    BricksetConfig,
    Config,
    ConfigError,
    PeeronConfig,
    ProvidersConfig,
)
from lego_manual_downloader.http import SessionBuilder
from lego_manual_downloader.lego import LegoSet
from lego_manual_downloader.provider_factory import (
    ManualProviderChain,
    ProviderManager,
    SetProviderChain,
    create_provider_manager,
)
from lego_manual_downloader.providers import (
    ManualProvider,
    OwnedSetsProvider,
    ProviderBase,
    ProviderBuilder,
    ProviderConfigError,
    ProviderUnavailable,
    require_credentials,
)

ONE = LegoSet("1", "1", "One", "2001")


class _FakeBuilder(ProviderBuilder):
    """Mirrors the real builders; the fakes need no config of their own."""

    provider_class: ClassVar[type[ProviderBase]]

    def build(self) -> ProviderBase:
        return self.provider_class()


class FakeBoth(ProviderBase):
    """Stands in for Brickset: serves both roles."""

    instances_created = 0

    def __init__(self) -> None:
        self.downloads: list[str] = []
        self.dry_runs: list[bool] = []
        FakeBoth.instances_created += 1

    def get_owned_sets(self) -> list[LegoSet]:
        return [ONE]

    def download_manual(self, lego_set: LegoSet, output_path: Path, dry_run: bool) -> bool:
        self.downloads.append(lego_set.number)
        self.dry_runs.append(dry_run)
        return True

    @staticmethod
    def builder(config: Config, session_builder: SessionBuilder) -> ProviderBuilder:
        return BothBuilder(config, session_builder)


class BothBuilder(_FakeBuilder):
    provider_class = FakeBoth


class FakeManualOnly(ProviderBase):
    def download_manual(self, lego_set: LegoSet, output_path: Path, dry_run: bool) -> bool:
        return False

    @staticmethod
    def builder(config: Config, session_builder: SessionBuilder) -> ProviderBuilder:
        return ManualOnlyBuilder(config, session_builder)


class ManualOnlyBuilder(_FakeBuilder):
    provider_class = FakeManualOnly


class FakeUnconfigurable(ProviderBase):
    def download_manual(self, lego_set: LegoSet, output_path: Path, dry_run: bool) -> bool:
        return True

    @staticmethod
    def builder(config: Config, session_builder: SessionBuilder) -> ProviderBuilder:
        return UnconfigurableBuilder(config, session_builder)


class UnconfigurableBuilder(ProviderBuilder):
    def build(self) -> ProviderBase:
        raise ProviderConfigError("requires a [fake] section in config")


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
class TestCreateProviderManager:
    def test_builds_both_roles(self, session_builder: SessionBuilder) -> None:
        manager = create_provider_manager(config_with(("both",), ("both",)), session_builder)
        assert len(manager.sets_provider_chain.providers) == 1
        assert len(manager.manual_provider_chain.providers) == 1

    def test_provider_in_both_roles_is_instantiated_once(
        self, session_builder: SessionBuilder
    ) -> None:
        manager = create_provider_manager(config_with(("both",), ("both",)), session_builder)
        assert FakeBoth.instances_created == 1
        sets_provider: object = manager.sets_provider_chain.providers[0]
        assert sets_provider is manager.manual_provider_chain.providers[0]

    def test_unknown_name_warns_and_is_skipped(
        self, session_builder: SessionBuilder, capsys: pytest.CaptureFixture[str]
    ) -> None:
        create_provider_manager(config_with(("both",), ("both", "nosuch")), session_builder)
        assert "Unknown provider 'nosuch'" in capsys.readouterr().out

    def test_wrong_role_warns_once(
        self, session_builder: SessionBuilder, capsys: pytest.CaptureFixture[str]
    ) -> None:
        manager = create_provider_manager(
            config_with(("both", "manualonly"), ("manualonly", "both")), session_builder
        )
        sets_providers = manager.sets_provider_chain.providers
        output = capsys.readouterr().out
        assert output.count("not a valid owned sets provider") == 1
        assert [type(p) for p in sets_providers] == [FakeBoth]

    def test_unconfigurable_provider_is_skipped_not_fatal(
        self, session_builder: SessionBuilder, capsys: pytest.CaptureFixture[str]
    ) -> None:
        manager = create_provider_manager(
            config_with(("both",), ("both", "broken")), session_builder
        )
        assert "Provider 'broken' is unavailable" in capsys.readouterr().out
        assert len(manager.manual_provider_chain.providers) == 1

    def test_no_usable_provider_at_all_raises(self, session_builder: SessionBuilder) -> None:
        with pytest.raises(ConfigError, match="no usable providers"):
            create_provider_manager(config_with(("nosuch",), ("nosuch",)), session_builder)

    def test_duplicate_names_build_one_instance(self, session_builder: SessionBuilder) -> None:
        create_provider_manager(config_with(("both", "both"), ("both",)), session_builder)
        assert FakeBoth.instances_created == 1

    def test_chains_are_built_once_and_cached(self, session_builder: SessionBuilder) -> None:
        manager = create_provider_manager(config_with(("both",), ("both",)), session_builder)
        assert manager.sets_provider_chain is manager.sets_provider_chain


class TestRoleSelection:
    """The roles are protocols, so membership is structural."""

    def test_a_both_roles_provider_fills_either_role(self) -> None:
        provider = FakeBoth()
        assert provider_factory._is_manual(provider)
        assert provider_factory._is_owned_sets(provider)

    def test_a_manual_only_provider_does_not_fill_the_sets_role(self) -> None:
        provider = FakeManualOnly()
        assert provider_factory._is_manual(provider)
        assert not provider_factory._is_owned_sets(provider)


class TestGetOwnedSets:
    def test_returns_the_first_providers_result(self) -> None:
        chain = SetProviderChain([FakeBoth()])
        assert chain.get_owned_sets() == [ONE]

    def test_an_empty_result_is_returned_rather_than_falling_through(self) -> None:
        """Owning no sets is a valid answer, not a provider failure."""

        class Empty(ProviderBase):
            def get_owned_sets(self) -> list[LegoSet]:
                return []

            @staticmethod
            def builder(config: Config, session_builder: SessionBuilder) -> ProviderBuilder:
                raise NotImplementedError

        chain = SetProviderChain([Empty(), FakeBoth()])
        assert chain.get_owned_sets() == []

    def test_falls_through_a_raising_provider(self, capsys: pytest.CaptureFixture[str]) -> None:
        chain = SetProviderChain([Boom(), FakeBoth()])
        assert chain.get_owned_sets() == [ONE]
        assert "network down" in capsys.readouterr().out

    def test_returns_empty_when_every_provider_fails(self) -> None:
        assert SetProviderChain([Boom()]).get_owned_sets() == []

    def test_returns_empty_with_no_providers(self) -> None:
        assert SetProviderChain([]).get_owned_sets() == []


class Boom(ProviderBase):
    def get_owned_sets(self) -> list[LegoSet]:
        raise RuntimeError("network down")

    def download_manual(self, lego_set: LegoSet, output_path: Path, dry_run: bool) -> bool:
        raise RuntimeError("timeout")

    @staticmethod
    def builder(config: Config, session_builder: SessionBuilder) -> ProviderBuilder:
        raise NotImplementedError


class TestDownloadManual:
    def test_stops_at_the_first_success(self, tmp_path: Path) -> None:
        winner, loser = FakeBoth(), FakeBoth()
        chain = ManualProviderChain([winner, loser])
        assert chain.download_manual(ONE, tmp_path / "x.pdf", dry_run=False)
        assert winner.downloads == ["1"]
        assert loser.downloads == []

    def test_falls_through_a_provider_returning_false(self, tmp_path: Path) -> None:
        succeeding = FakeBoth()
        chain = ManualProviderChain([FakeManualOnly(), succeeding])
        assert chain.download_manual(ONE, tmp_path / "x.pdf", dry_run=False)
        assert succeeding.downloads == ["1"]

    def test_falls_through_a_raising_provider(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        chain = ManualProviderChain([Boom(), FakeBoth()])
        assert chain.download_manual(ONE, tmp_path / "x.pdf", dry_run=False)
        assert "timeout" in capsys.readouterr().out

    def test_error_message_names_the_provider_class(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        ManualProviderChain([Boom()]).download_manual(ONE, tmp_path / "x", dry_run=False)
        output = capsys.readouterr().out
        assert "Boom" in output
        assert "object at 0x" not in output

    def test_returns_false_when_nothing_succeeds(self, tmp_path: Path) -> None:
        assert not ManualProviderChain([FakeManualOnly()]).download_manual(
            ONE, tmp_path / "x.pdf", dry_run=False
        )

    def test_returns_false_with_no_providers(self, tmp_path: Path) -> None:
        assert not ManualProviderChain([]).download_manual(ONE, tmp_path / "x.pdf", dry_run=False)

    @pytest.mark.parametrize("dry_run", [True, False])
    def test_dry_run_reaches_the_provider(self, tmp_path: Path, dry_run: bool) -> None:
        provider = FakeBoth()
        ManualProviderChain([provider]).download_manual(ONE, tmp_path / "x.pdf", dry_run=dry_run)
        assert provider.dry_runs == [dry_run]

    def test_dry_run_still_stops_at_the_first_success(self, tmp_path: Path) -> None:
        winner, loser = FakeBoth(), FakeBoth()
        chain = ManualProviderChain([winner, loser])
        assert chain.download_manual(ONE, tmp_path / "x.pdf", dry_run=True)
        assert winner.dry_runs == [True]
        assert loser.dry_runs == []


class Unavailable(ProviderBase):
    """Reports itself permanently unusable, as a dead login does."""

    def __init__(self) -> None:
        self.sets_calls = 0
        self.manual_calls = 0

    def get_owned_sets(self) -> list[LegoSet]:
        self.sets_calls += 1
        raise ProviderUnavailable("brickset login failed")

    def download_manual(self, lego_set: LegoSet, output_path: Path, dry_run: bool) -> bool:
        self.manual_calls += 1
        raise ProviderUnavailable("brickset login failed")

    @staticmethod
    def builder(config: Config, session_builder: SessionBuilder) -> ProviderBuilder:
        raise NotImplementedError


class Transient(ProviderBase):
    """Fails per-set without implying anything about the next set."""

    def __init__(self) -> None:
        self.calls = 0

    def download_manual(self, lego_set: LegoSet, output_path: Path, dry_run: bool) -> bool:
        self.calls += 1
        raise RuntimeError("404 for this set")

    @staticmethod
    def builder(config: Config, session_builder: SessionBuilder) -> ProviderBuilder:
        raise NotImplementedError


class TestRetiresUnavailableProviders:
    def test_unavailable_provider_is_called_once_across_many_sets(self, tmp_path: Path) -> None:
        dead = Unavailable()
        chain = ManualProviderChain([dead])
        for n in range(5):
            assert not chain.download_manual(
                LegoSet(str(n), "1", "S", "2001"), tmp_path / "x.pdf", dry_run=False
            )
        assert dead.manual_calls == 1

    def test_unavailable_provider_is_reported_once(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        chain = ManualProviderChain([Unavailable()])
        for n in range(5):
            chain.download_manual(LegoSet(str(n), "1", "S", "2001"), tmp_path / "x.pdf", False)
        assert capsys.readouterr().out.count("Dropping Unavailable for this run") == 1

    def test_transient_failures_do_not_retire_the_provider(self, tmp_path: Path) -> None:
        flaky = Transient()
        chain = ManualProviderChain([flaky])
        for n in range(5):
            assert not chain.download_manual(
                LegoSet(str(n), "1", "S", "2001"), tmp_path / "x.pdf", dry_run=False
            )
        assert flaky.calls == 5

    def test_retiring_a_provider_removes_it_from_both_roles(self, tmp_path: Path) -> None:
        """Retirement is a property of the provider, so every chain sees it at once."""
        dead = Unavailable()
        sets_chain, manual_chain = SetProviderChain([dead]), ManualProviderChain([dead])

        manual_chain.download_manual(ONE, tmp_path / "x.pdf", dry_run=False)

        assert not manual_chain.has_providers()
        assert not sets_chain.has_providers()

    def test_a_healthy_provider_in_another_chain_survives(self, tmp_path: Path) -> None:
        dead, healthy = Unavailable(), FakeManualOnly()
        sets_chain = SetProviderChain([dead])
        manual_chain = ManualProviderChain([dead, healthy])

        manual_chain.download_manual(ONE, tmp_path / "x.pdf", dry_run=False)

        assert not sets_chain.has_providers()
        assert manual_chain.has_providers()

    def test_healthy_provider_still_serves_after_one_is_retired(self, tmp_path: Path) -> None:
        dead, healthy = Unavailable(), FakeBoth()
        chain = ManualProviderChain([dead, healthy])
        for n in range(3):
            assert chain.download_manual(
                LegoSet(str(n), "1", "S", "2001"), tmp_path / "x.pdf", dry_run=False
            )
        assert dead.manual_calls == 1
        assert healthy.downloads == ["0", "1", "2"]

    def test_unavailable_sets_provider_is_retired(self) -> None:
        dead = Unavailable()
        chain = SetProviderChain([dead, FakeBoth()])
        assert chain.get_owned_sets() == [ONE]
        chain.get_owned_sets()
        assert dead.sets_calls == 1

    def test_retirement_is_per_instance(self) -> None:
        """Two equal-but-distinct providers must not both be dropped."""
        first, second = FakeManualOnly(), FakeManualOnly()
        first.retire(RuntimeError("dead"))
        assert not first.is_available()
        assert second.is_available()


class TestHasProviders:
    def test_availability_needs_no_constructor_cooperation(self) -> None:
        """`_available` is a class attribute, so a provider that never calls
        super().__init__() is still usable."""

        class NoSuperInit(ProviderBase):
            def __init__(self) -> None:
                self.thing = 1

            def download_manual(self, lego_set: LegoSet, output_path: Path, dry_run: bool) -> bool:
                return True

            @staticmethod
            def builder(config: Config, session_builder: SessionBuilder) -> ProviderBuilder:
                raise NotImplementedError

        assert ManualProviderChain([NoSuperInit()]).has_providers()

    def test_true_while_a_provider_remains(self) -> None:
        assert ManualProviderChain([FakeBoth()]).has_providers()

    def test_false_once_empty(self) -> None:
        assert not ManualProviderChain([]).has_providers()

    def test_flips_when_the_last_provider_retires(self, tmp_path: Path) -> None:
        chain = ManualProviderChain([Unavailable()])
        assert chain.has_providers()
        chain.download_manual(ONE, tmp_path / "x.pdf", dry_run=False)
        assert not chain.has_providers()


class TestRequireCredentials:
    def test_an_absent_section_is_rejected(self) -> None:
        with pytest.raises(ProviderConfigError, match=r"\[brickset\] section"):
            require_credentials("brickset", None)

    @pytest.mark.parametrize(
        "username,password", [("", "p"), ("u", ""), ("", "")], ids=["user", "pass", "both"]
    )
    def test_blank_credentials_are_rejected(self, username: str, password: str) -> None:
        with pytest.raises(ProviderConfigError, match="username"):
            require_credentials("peeron", PeeronConfig(username=username, password=password))

    def test_a_complete_section_is_returned_unchanged(self) -> None:
        config = BricksetConfig(username="u", password="p")
        assert require_credentials("brickset", config) is config


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


def test_a_manager_can_be_built_from_the_real_providers(session_builder: SessionBuilder) -> None:
    config = Config(
        brickset=BricksetConfig(username="u", password="p"),
        peeron=PeeronConfig(username="u", password="p"),
    )
    manager = create_provider_manager(config, session_builder)

    assert isinstance(manager, ProviderManager)
    assert [type(p).__name__ for p in manager.sets_provider_chain.providers] == ["Brickset"]
    assert [type(p).__name__ for p in manager.manual_provider_chain.providers] == [
        "Brickset",
        "Peeron",
    ]


def test_a_provider_missing_its_section_is_skipped_with_a_warning(
    session_builder: SessionBuilder, capsys: pytest.CaptureFixture[str]
) -> None:
    config = Config(brickset=BricksetConfig(username="u", password="p"))
    manager = create_provider_manager(config, session_builder)

    assert "Provider 'peeron' is unavailable" in capsys.readouterr().out
    assert [type(p).__name__ for p in manager.manual_provider_chain.providers] == ["Brickset"]
