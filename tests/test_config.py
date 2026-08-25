import re
from pathlib import Path

import pytest

from lego_manual_downloader.config import (
    BricksetConfig,
    Config,
    ConfigError,
    DbConfig,
    PeeronConfig,
    ProvidersConfig,
)


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text)
    return path


class TestDefaults:
    def test_no_file_at_default_path_yields_defaults(self) -> None:
        config = Config.load()
        assert config.providers == ProvidersConfig()
        assert config.db == DbConfig()
        assert config.brickset is None
        assert config.peeron is None

    def test_provider_defaults_are_tuples(self) -> None:
        """Tuples, not lists -- a mutable default raises at class creation."""
        providers = ProvidersConfig()
        assert providers.owned_sets_providers == ("brickset",)
        assert providers.manual_providers == ("brickset", "peeron")

    def test_config_is_hashable(self) -> None:
        """frozen=True only means something if the fields are immutable too."""
        assert hash(Config()) == hash(Config())

    def test_db_default_filename(self) -> None:
        assert DbConfig().file == "_lmd_db.json"


class TestBinding:
    def test_nested_sections_become_dataclasses(self, tmp_path: Path) -> None:
        path = write(
            tmp_path,
            """
            [brickset]
            username = "u"
            password = "p"
            """,
        )
        config = Config.load(path)
        assert isinstance(config.brickset, BricksetConfig)
        assert config.brickset.username == "u"
        assert config.brickset.password == "p"

    def test_hyphenated_and_underscored_keys_are_equivalent(self, tmp_path: Path) -> None:
        hyphen = write(
            tmp_path,
            """
            [brickset]
            username = "u"
            password = "p"
            base-url = "https://example.test"
            """,
        )
        loaded_hyphen = Config.load(hyphen)

        underscore = tmp_path / "under.toml"
        underscore.write_text(
            '[brickset]\nusername = "u"\npassword = "p"\nbase_url = "https://example.test"\n'
        )
        loaded_underscore = Config.load(underscore)

        assert loaded_hyphen == loaded_underscore
        assert loaded_hyphen.brickset is not None
        assert loaded_hyphen.brickset.base_url == "https://example.test"

    def test_unspecified_keys_keep_their_defaults(self, tmp_path: Path) -> None:
        path = write(tmp_path, '[brickset]\nusername = "u"\npassword = "p"\n')
        config = Config.load(path)
        assert config.brickset is not None
        assert config.brickset.base_url == "https://brickset.com"
        assert config.brickset.owned_sets_url == "/exportscripts/sets/owned/"

    def test_array_becomes_tuple(self, tmp_path: Path) -> None:
        path = write(tmp_path, '[providers]\nmanual-providers = ["peeron"]\n')
        config = Config.load(path)
        assert config.providers.manual_providers == ("peeron",)

    def test_peeron_section_binds(self, tmp_path: Path) -> None:
        path = write(tmp_path, '[peeron]\nusername = "u"\npassword = "p"\n')
        config = Config.load(path)
        assert isinstance(config.peeron, PeeronConfig)


class TestErrors:
    def test_unknown_top_level_key(self, tmp_path: Path) -> None:
        path = write(tmp_path, '[nope]\nfoo = "bar"\n')
        with pytest.raises(ConfigError) as excinfo:
            Config.load(path)
        message = str(excinfo.value)
        assert "nope" in message
        assert "brickset" in message  # lists what was expected

    def test_unknown_nested_key_reports_full_path(self, tmp_path: Path) -> None:
        path = write(tmp_path, '[brickset]\nusername = "u"\npassword = "p"\nbogus = 1\n')
        with pytest.raises(ConfigError, match=re.escape("brickset.bogus")):
            Config.load(path)

    def test_missing_required_key_names_it(self, tmp_path: Path) -> None:
        path = write(tmp_path, '[brickset]\nusername = "u"\n')
        with pytest.raises(ConfigError, match="password"):
            Config.load(path)

    def test_scalar_where_array_expected(self, tmp_path: Path) -> None:
        path = write(tmp_path, '[providers]\nmanual-providers = "brickset"\n')
        with pytest.raises(ConfigError, match="must be an array"):
            Config.load(path)

    def test_scalar_where_table_expected(self, tmp_path: Path) -> None:
        path = write(tmp_path, 'brickset = "nope"\n')
        with pytest.raises(ConfigError, match="must be a table"):
            Config.load(path)

    def test_malformed_toml_is_wrapped(self, tmp_path: Path) -> None:
        path = write(tmp_path, "this is = = not toml [[[\n")
        with pytest.raises(ConfigError) as excinfo:
            Config.load(path)
        assert str(path) in str(excinfo.value)

    def test_explicitly_named_missing_file_is_an_error(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="config file not found"):
            Config.load(tmp_path / "absent.toml")

    def test_missing_default_file_is_not_an_error(self) -> None:
        assert Config.load() == Config()
