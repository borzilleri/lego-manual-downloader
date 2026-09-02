import tomllib
from dataclasses import MISSING, dataclass, fields, is_dataclass
from pathlib import Path
from types import UnionType
from typing import Any, TypeVar, Union, cast, get_args, get_origin, get_type_hints

from lego_manual_downloader.log import DEFAULT_LEVEL, LEVELS

_DEFAULT_CONFIG_PATH = Path("~/.config/lego-manual-downloader/config.toml")

T = TypeVar("T")


class ConfigError(Exception):
    pass


def _display(name: str) -> str:
    return name.replace("_", "-")


def _unwrap_optional(annotation: Any) -> Any:
    """`BricksetConfig | None` -> `BricksetConfig`; everything else unchanged."""
    if get_origin(annotation) in (Union, UnionType):
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return annotation


def _bind(cls: type[T], data: dict[str, Any], where: str = "") -> T:
    """Build a dataclass from a TOML table, recursing into nested sections.

    Keys are matched with hyphens normalized to underscores, so `base-url` and
    `base_url` both bind to the `base_url` field.
    """
    hints = get_type_hints(cls)
    known = {f.name: f for f in fields(cast(Any, cls))}
    kwargs: dict[str, Any] = {}

    for key, value in data.items():
        name = key.replace("-", "_")
        location = f"{where}.{key}" if where else key
        if name not in known:
            expected = ", ".join(sorted(_display(k) for k in known))
            raise ConfigError(f"unknown config key '{location}'; expected one of: {expected}")

        target = _unwrap_optional(hints[name])
        if is_dataclass(target):
            if not isinstance(value, dict):
                raise ConfigError(f"'{location}' must be a table")
            kwargs[name] = _bind(cast(type[Any], target), value, location)
        elif get_origin(target) is tuple:
            if not isinstance(value, list):
                raise ConfigError(f"'{location}' must be an array")
            kwargs[name] = tuple(value)
        else:
            kwargs[name] = value

    missing = [
        name
        for name, f in known.items()
        if name not in kwargs and f.default is MISSING and f.default_factory is MISSING
    ]
    if missing:
        listed = ", ".join(_display(name) for name in sorted(missing))
        raise ConfigError(f"[{where or 'config'}] missing required key(s): {listed}")

    return cls(**kwargs)


@dataclass(frozen=True)
class HttpConfig:
    timeout: int = 10


@dataclass(frozen=True)
class ProvidersConfig:
    owned_sets_providers: tuple[str, ...] = ("brickset",)
    manual_providers: tuple[str, ...] = ("brickset", "peeron")

    @property
    def all_providers(self) -> list[str]:
        return list(dict.fromkeys(self.owned_sets_providers + self.manual_providers).keys())


@dataclass(frozen=True)
class LoggingConfig:
    """Defaults for console output; `--log-level` and `--log-file` override these."""

    level: str = DEFAULT_LEVEL
    file: str | None = None

    def __post_init__(self) -> None:
        if self.level not in LEVELS:
            raise ConfigError(
                f"[logging] unknown level '{self.level}'; expected one of: {', '.join(LEVELS)}"
            )

    @property
    def path(self) -> Path | None:
        return Path(self.file) if self.file else None


@dataclass(frozen=True)
class DbConfig:
    file: str = "_lmd_db.json"


@dataclass(frozen=True)
class CredentialedConfig:
    """Shared by every provider section that logs in with a username and password."""

    username: str
    password: str


@dataclass(frozen=True)
class BricksetConfig(CredentialedConfig):
    base_url: str = "https://brickset.com"
    owned_sets_url: str = "/exportscripts/sets/owned/"
    instructions_url: str = "/exportscripts/instructions"


@dataclass(frozen=True)
class PeeronConfig(CredentialedConfig):
    login_url: str = "http://peeron.com/cgi-bin/invcgis/login"
    scans_url: str = "http://peeron.com/scans/"
    thumbs_url: str = "http://belay.peeron.com/thumbs"


@dataclass(frozen=True)
class Config:
    providers: ProvidersConfig = ProvidersConfig()
    db: DbConfig = DbConfig()
    brickset: BricksetConfig | None = None
    peeron: PeeronConfig | None = None
    http: HttpConfig = HttpConfig()
    logging: LoggingConfig = LoggingConfig()

    @staticmethod
    def load(path: Path | None = None) -> "Config":
        source = (path or _DEFAULT_CONFIG_PATH).expanduser()
        try:
            with source.open("rb") as f:
                data = tomllib.load(f)
        except FileNotFoundError:
            if path is not None:
                raise ConfigError(f"config file not found: {source}") from None
            data = {}
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"{source}: {e}") from e
        return _bind(Config, data)
