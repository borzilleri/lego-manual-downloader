import logging
from pathlib import Path

import pytest

from conftest import ONE, FakeBoth, FakeManualOnly, SetsOnlyProvider, UnbuiltProvider, records_at
from lego_manual_downloader.lego import LegoSet
from lego_manual_downloader.provider_chain import InstructionsProviderChain, SetsProviderChain
from lego_manual_downloader.providers import BaseProvider, ProviderUnavailableError


def a_set(n: int) -> LegoSet:
    return LegoSet(str(n), "1", "S", "2001")


class Boom(UnbuiltProvider):
    """Fails generically: a transient error, not a retirement."""

    def get_owned_sets(self) -> list[LegoSet]:
        raise RuntimeError("network down")

    def download_manual(self, lego_set: LegoSet, output_path: Path, dry_run: bool) -> bool:
        raise RuntimeError("timeout")


class Unavailable(UnbuiltProvider):
    """Reports itself permanently unusable, as a dead login does."""

    def __init__(self) -> None:
        self.sets_calls = 0
        self.manual_calls = 0

    def get_owned_sets(self) -> list[LegoSet]:
        self.sets_calls += 1
        raise ProviderUnavailableError("brickset login failed")

    def download_manual(self, lego_set: LegoSet, output_path: Path, dry_run: bool) -> bool:
        self.manual_calls += 1
        raise ProviderUnavailableError("brickset login failed")


class Transient(UnbuiltProvider):
    """Fails per-set without implying anything about the next set."""

    def __init__(self) -> None:
        self.calls = 0

    def download_manual(self, lego_set: LegoSet, output_path: Path, dry_run: bool) -> bool:
        self.calls += 1
        raise RuntimeError("404 for this set")


class TestRoleSelection:
    """The roles are protocols, so membership is structural."""

    def test_a_both_roles_provider_fills_either_role(self) -> None:
        assert InstructionsProviderChain._is_valid_provider(FakeBoth())
        assert SetsProviderChain._is_valid_provider(FakeBoth())

    def test_a_manual_only_provider_does_not_fill_the_sets_role(self) -> None:
        assert InstructionsProviderChain._is_valid_provider(FakeManualOnly())
        assert not SetsProviderChain._is_valid_provider(FakeManualOnly())

    def test_wrong_role_warns_once(self, caplog: pytest.LogCaptureFixture) -> None:
        instances: dict[str, BaseProvider] = {"both": FakeBoth(), "manualonly": FakeManualOnly()}
        chain = SetsProviderChain.create(["both", "manualonly"], instances)

        assert len(records_at(caplog, logging.WARNING, "not a valid owned sets provider")) == 1
        assert [type(p) for p in chain.providers] == [FakeBoth]

    def test_a_sets_only_provider_is_rejected_by_the_manual_chain(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The mirror of the above: each chain names its own role in the warning."""
        instances: dict[str, BaseProvider] = {"sets": SetsOnlyProvider(), "both": FakeBoth()}
        chain = InstructionsProviderChain.create(["sets", "both"], instances)

        assert records_at(caplog, logging.WARNING, "not a valid manual provider")
        assert [type(p) for p in chain.providers] == [FakeBoth]

    def test_an_unbuilt_provider_is_skipped_silently(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A provider that failed to build was already reported by the builder."""
        chain = SetsProviderChain.create(["absent"], {})
        assert chain.providers == []
        assert caplog.records == []


class TestGetOwnedSets:
    def test_returns_the_first_providers_result(self) -> None:
        chain = SetsProviderChain([FakeBoth()])
        assert chain.get_owned_sets() == [ONE]

    def test_an_empty_result_is_returned_rather_than_falling_through(self) -> None:
        """Owning no sets is a valid answer, not a provider failure."""

        class Empty(UnbuiltProvider):
            def get_owned_sets(self) -> list[LegoSet]:
                return []

        chain = SetsProviderChain([Empty(), FakeBoth()])
        assert chain.get_owned_sets() == []

    def test_falls_through_a_raising_provider(self, caplog: pytest.LogCaptureFixture) -> None:
        chain = SetsProviderChain([Boom(), FakeBoth()])
        assert chain.get_owned_sets() == [ONE]
        assert records_at(caplog, logging.WARNING, "network down")

    def test_returns_empty_when_every_provider_fails(self) -> None:
        assert SetsProviderChain([Boom()]).get_owned_sets() == []

    def test_returns_empty_with_no_providers(self) -> None:
        assert SetsProviderChain([]).get_owned_sets() == []


class TestDownloadManual:
    def test_stops_at_the_first_success(self, tmp_path: Path) -> None:
        winner, loser = FakeBoth(), FakeBoth()
        chain = InstructionsProviderChain([winner, loser])
        assert chain.download_manual(ONE, tmp_path / "x.pdf", dry_run=False)
        assert winner.downloads == ["1"]
        assert loser.downloads == []

    def test_falls_through_a_provider_returning_false(self, tmp_path: Path) -> None:
        succeeding = FakeBoth()
        chain = InstructionsProviderChain([FakeManualOnly(), succeeding])
        assert chain.download_manual(ONE, tmp_path / "x.pdf", dry_run=False)
        assert succeeding.downloads == ["1"]

    def test_falls_through_a_raising_provider(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        chain = InstructionsProviderChain([Boom(), FakeBoth()])
        assert chain.download_manual(ONE, tmp_path / "x.pdf", dry_run=False)
        assert records_at(caplog, logging.WARNING, "timeout")

    def test_error_message_names_the_provider_class(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        InstructionsProviderChain([Boom()]).download_manual(ONE, tmp_path / "x", dry_run=False)
        assert records_at(caplog, logging.WARNING, "Boom")
        assert "object at 0x" not in caplog.text

    def test_returns_false_when_nothing_succeeds(self, tmp_path: Path) -> None:
        assert not InstructionsProviderChain([FakeManualOnly()]).download_manual(
            ONE, tmp_path / "x.pdf", dry_run=False
        )

    def test_returns_false_with_no_providers(self, tmp_path: Path) -> None:
        assert not InstructionsProviderChain([]).download_manual(
            ONE, tmp_path / "x.pdf", dry_run=False
        )

    @pytest.mark.parametrize("dry_run", [True, False])
    def test_dry_run_reaches_the_provider(self, tmp_path: Path, dry_run: bool) -> None:
        provider = FakeBoth()
        InstructionsProviderChain([provider]).download_manual(
            ONE, tmp_path / "x.pdf", dry_run=dry_run
        )
        assert provider.dry_runs == [dry_run]

    def test_dry_run_still_stops_at_the_first_success(self, tmp_path: Path) -> None:
        winner, loser = FakeBoth(), FakeBoth()
        chain = InstructionsProviderChain([winner, loser])
        assert chain.download_manual(ONE, tmp_path / "x.pdf", dry_run=True)
        assert winner.dry_runs == [True]
        assert loser.dry_runs == []


class TestRetiresUnavailableProviders:
    def test_unavailable_provider_is_called_once_across_many_sets(self, tmp_path: Path) -> None:
        dead = Unavailable()
        chain = InstructionsProviderChain([dead])
        for n in range(5):
            assert not chain.download_manual(a_set(n), tmp_path / "x.pdf", dry_run=False)
        assert dead.manual_calls == 1

    def test_unavailable_provider_is_reported_once(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        chain = InstructionsProviderChain([Unavailable()])
        for n in range(5):
            chain.download_manual(a_set(n), tmp_path / "x.pdf", dry_run=False)
        assert len(records_at(caplog, logging.WARNING, "Dropping Unavailable for this run")) == 1

    def test_transient_failures_do_not_retire_the_provider(self, tmp_path: Path) -> None:
        flaky = Transient()
        chain = InstructionsProviderChain([flaky])
        for n in range(5):
            assert not chain.download_manual(a_set(n), tmp_path / "x.pdf", dry_run=False)
        assert flaky.calls == 5

    def test_retiring_a_provider_removes_it_from_both_roles(self, tmp_path: Path) -> None:
        """Retirement is a property of the provider, so every chain sees it at once."""
        dead = Unavailable()
        sets_chain = SetsProviderChain([dead])
        manual_chain = InstructionsProviderChain([dead])

        manual_chain.download_manual(ONE, tmp_path / "x.pdf", dry_run=False)

        assert not manual_chain.has_providers()
        assert not sets_chain.has_providers()

    def test_a_healthy_provider_in_another_chain_survives(self, tmp_path: Path) -> None:
        dead, healthy = Unavailable(), FakeManualOnly()
        sets_chain = SetsProviderChain([dead])
        manual_chain = InstructionsProviderChain([dead, healthy])

        manual_chain.download_manual(ONE, tmp_path / "x.pdf", dry_run=False)

        assert not sets_chain.has_providers()
        assert manual_chain.has_providers()

    def test_healthy_provider_still_serves_after_one_is_retired(self, tmp_path: Path) -> None:
        dead, healthy = Unavailable(), FakeBoth()
        chain = InstructionsProviderChain([dead, healthy])
        for n in range(3):
            assert chain.download_manual(a_set(n), tmp_path / "x.pdf", dry_run=False)
        assert dead.manual_calls == 1
        assert healthy.downloads == ["0", "1", "2"]

    def test_unavailable_sets_provider_is_retired(self) -> None:
        dead = Unavailable()
        chain = SetsProviderChain([dead, FakeBoth()])
        assert chain.get_owned_sets() == [ONE]
        chain.get_owned_sets()
        assert dead.sets_calls == 1


class TestHasProviders:
    def test_availability_needs_no_constructor_cooperation(self) -> None:
        """`_available` is a class attribute, so a provider that never calls
        super().__init__() is still usable."""

        class NoSuperInit(UnbuiltProvider):
            def __init__(self) -> None:
                self.thing = 1

            def download_manual(self, lego_set: LegoSet, output_path: Path, dry_run: bool) -> bool:
                return True

        assert InstructionsProviderChain([NoSuperInit()]).has_providers()

    def test_true_while_a_provider_remains(self) -> None:
        assert InstructionsProviderChain([FakeBoth()]).has_providers()

    def test_false_once_empty(self) -> None:
        assert not InstructionsProviderChain([]).has_providers()

    def test_flips_when_the_last_provider_retires(self, tmp_path: Path) -> None:
        chain = InstructionsProviderChain([Unavailable()])
        assert chain.has_providers()
        chain.download_manual(ONE, tmp_path / "x.pdf", dry_run=False)
        assert not chain.has_providers()
