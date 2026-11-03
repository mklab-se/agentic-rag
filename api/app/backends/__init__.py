"""Backend registry. Tasks adding a backend call `register_backend` below."""

import logging
from collections.abc import Callable

from app.backends.base import Backend, BackendUnavailable
from app.backends.hosted import build_hosted_backend
from app.backends.loop import build_loop_backend
from app.backends.prompt import build_prompt_backend
from app.settings import Settings

logger = logging.getLogger(__name__)

BACKEND_NAMES = ("loop", "prompt", "hosted")
BackendFactory = Callable[[Settings], Backend]

_DEFAULT_FACTORIES: dict[str, BackendFactory] = {}


def register_backend(name: str, factory: BackendFactory) -> None:
    """Register how to build a backend. The factory runs on first use, not at import, and
    raises BackendUnavailable when the deployment lacks what it needs."""
    if name not in BACKEND_NAMES:
        raise ValueError(f"Unknown backend name {name!r}")
    _DEFAULT_FACTORIES[name] = factory


register_backend("loop", build_loop_backend)
register_backend("prompt", build_prompt_backend)
register_backend("hosted", build_hosted_backend)


class BackendRegistry:
    """Builds each backend once, on first request."""

    def __init__(self, settings: Settings, factories: dict[str, BackendFactory] | None = None):
        self._settings = settings
        self._factories = dict(_DEFAULT_FACTORIES if factories is None else factories)
        self._instances: dict[str, Backend] = {}

    def get_backend(self, name: str) -> Backend:
        if name not in BACKEND_NAMES:
            raise BackendUnavailable(
                f"Unknown backend '{name[:40]}'. Use one of: {', '.join(BACKEND_NAMES)}."
            )
        if name not in self._instances:
            factory = self._factories.get(name)
            if factory is None:
                raise BackendUnavailable(f"Backend '{name}' is not configured in this deployment.")
            try:
                self._instances[name] = factory(self._settings)
            except BackendUnavailable:
                raise
            except Exception as exc:
                logger.exception("Backend %s failed to start", name)
                raise BackendUnavailable(f"Backend '{name}' could not be started.") from exc
        return self._instances[name]

    async def close(self) -> None:
        for name, backend in self._instances.items():
            try:
                await backend.close()
            except Exception:
                logger.exception("Closing backend %s failed", name)
