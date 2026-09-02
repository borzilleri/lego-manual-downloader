import logging

from lego_manual_downloader.brickset import Brickset
from lego_manual_downloader.config import Config
from lego_manual_downloader.http import ConnectionManager
from lego_manual_downloader.peeron import Peeron
from lego_manual_downloader.providers import BaseProvider, ProviderConfigError

logger = logging.getLogger(__name__)

_provider_registry: dict[str, type[BaseProvider]] = {
    "brickset": Brickset,
    "peeron": Peeron,
}


def _build_providers(
    provider_names: list[str], config: Config, connection_manager: ConnectionManager
) -> dict[str, BaseProvider]:
    """Instantiate each named provider once, skipping any that cannot be configured."""
    instances: dict[str, BaseProvider] = {}
    for name in provider_names:
        provider_class = _provider_registry.get(name)
        if provider_class is None:
            logger.warning("Unknown provider '%s' specified in config.", name)
            continue
        try:
            instances[name] = provider_class.builder(config, connection_manager).build()
        except ProviderConfigError as e:
            logger.warning("Failed to build provider '%s': %s", name, e)
    return instances


def create_providers(
    config: Config, connection_manager: ConnectionManager
) -> dict[str, BaseProvider]:
    instances = _build_providers(config.providers.all_providers, config, connection_manager)
    if not instances:
        raise ProviderConfigError("no usable providers configured")
    return instances
