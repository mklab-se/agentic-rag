"""Backend registry: the three backends by name, each built on first use."""

import logging
from collections.abc import Callable

from app.backends.base import Backend, BackendUnavailable
from app.backends.hosted import build_hosted_backend
from app.backends.loop import build_loop_backend
from app.backends.prompt import build_prompt_backend
from app.settings import Settings

logger = logging.getLogger(__name__)

BackendFactory = Callable[[Settings], Backend]

# A factory raises BackendUnavailable when the deployment lacks what its backend needs.
BACKEND_FACTORIES: dict[str, BackendFactory] = {
    "loop": build_loop_backend,
    "prompt": build_prompt_backend,
    "hosted": build_hosted_backend,
}
BACKEND_NAMES = tuple(BACKEND_FACTORIES)


class BackendRegistry:
    """Builds each backend once, on first request."""

    def __init__(self, settings: Settings, factories: dict[str, BackendFactory] | None = None):
        self._settings = settings
        self._factories = dict(BACKEND_FACTORIES if factories is None else factories)
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
