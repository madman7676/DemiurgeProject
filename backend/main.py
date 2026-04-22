"""Backend entry point for the minimal exploration-mode API."""

from __future__ import annotations

import logging

import uvicorn
from backend.config import load_settings


def main() -> None:
    """Start the local backend server."""

    logging.basicConfig(level=logging.INFO)
    settings = load_settings()
    uvicorn.run(
        "backend.api.app:create_app",
        host=settings.host,
        port=settings.port,
        factory=True,
        reload=False,
    )


if __name__ == "__main__":
    main()
