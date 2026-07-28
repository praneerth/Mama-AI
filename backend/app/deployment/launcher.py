"""Production Uvicorn launcher for Mama AI."""

from __future__ import annotations

import uvicorn

from app.config import settings
from app.deployment.validation import validate_runtime_environment


def build_uvicorn_options() -> dict[str, object]:
    """Return the validated single-process server configuration."""

    validate_runtime_environment()
    return {
        "app": "main:app",
        "host": settings.HOST,
        "port": settings.PORT,
        "workers": settings.DEPLOYMENT_WORKERS,
        "proxy_headers": True,
        "forwarded_allow_ips": settings.FORWARDED_ALLOW_IPS,
        "timeout_keep_alive": settings.SERVER_TIMEOUT_KEEP_ALIVE,
        "timeout_graceful_shutdown": settings.SERVER_GRACEFUL_SHUTDOWN_SECONDS,
        "access_log": False,
        "server_header": False,
        "date_header": True,
        "log_config": None,
    }


def main() -> None:
    uvicorn.run(**build_uvicorn_options())


if __name__ == "__main__":
    main()
