import importlib
import importlib.util
import os
import re
import sys
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import cast

from app.notifiers.voice.base import BaseVoiceProvider
from app.settings import Config

PROVIDER_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def normalize_provider_name(provider_name: str | None) -> str:
    """Normalize and validate a voice provider name."""

    name = str(provider_name or "").strip().lower()

    if not name:
        raise RuntimeError("voice provider name is missing")

    if not PROVIDER_NAME_RE.match(name):
        raise RuntimeError(
            "voice provider name must contain only letters, numbers and underscore"
        )

    return name


def _get_providers_dir() -> str:
    """Return custom providers directory."""

    return getattr(
        Config,
        "VOICE_PROVIDERS_DIR",
        "/usr/local/lib/incidentrelay/voice_providers",
    )


def _load_builtin_provider(provider_name: str) -> ModuleType | None:
    """Load a built-in voice provider module."""

    module_path = f"app.notifiers.voice.providers.{provider_name}"

    try:
        return importlib.import_module(module_path)
    except ModuleNotFoundError as exc:
        if exc.name == module_path:
            return None
        raise


def _load_external_provider(provider_name: str) -> ModuleType | None:
    """Load a custom voice provider module from providers_dir."""

    base_dir = Path(_get_providers_dir()).expanduser().resolve()
    provider_path = (base_dir / f"{provider_name}.py").resolve()

    if base_dir not in provider_path.parents:
        raise RuntimeError("voice provider path is outside providers_dir")

    if not provider_path.is_file():
        return None

    module_name = f"incidentrelay_voice_provider_{provider_name}"
    spec = importlib.util.spec_from_file_location(module_name, provider_path)

    if not spec or not spec.loader:
        raise RuntimeError(f"cannot load voice provider: {provider_name}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    return module


@lru_cache(maxsize=128)
def get_voice_provider_class(provider_name: str) -> type[BaseVoiceProvider]:
    """Return Provider class for built-in or custom voice provider."""

    name = normalize_provider_name(provider_name)
    module = _load_builtin_provider(name) or _load_external_provider(name)

    if not module:
        raise RuntimeError(f"voice provider not found: {name}")

    provider_cls = getattr(module, "Provider", None)

    if not isinstance(provider_cls, type) or not issubclass(
        provider_cls,
        BaseVoiceProvider,
    ):
        raise RuntimeError(
            f"voice provider {name} must define Provider(BaseVoiceProvider)"
        )

    return cast(type[BaseVoiceProvider], provider_cls)


def create_voice_provider(
    provider_name: str,
    config: dict | None = None,
) -> BaseVoiceProvider:
    """Create a configured voice provider instance."""
    provider_cls = get_voice_provider_class(provider_name)
    provider_config = resolve_env_values(config or {})
    provider_cls.validate_config(provider_config)
    return provider_cls(provider_config)


def resolve_env_values(value):
    """Resolve ${ENV_NAME} strings inside provider config."""

    if isinstance(value, dict):
        return {key: resolve_env_values(item) for key, item in value.items()}

    if isinstance(value, list):
        return [resolve_env_values(item) for item in value]

    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        env_name = value[2:-1].strip()
        return os.getenv(env_name, "")

    return value
