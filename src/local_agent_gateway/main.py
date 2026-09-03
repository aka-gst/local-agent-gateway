import logging

import uvicorn

from .app import create_app
from .config import get_settings


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    settings = get_settings()
    uvicorn.run(
        create_app(settings),
        host="127.0.0.1",
        port=settings.port,
        access_log=False,
        timeout_graceful_shutdown=5,
    )


if __name__ == "__main__":
    run()
