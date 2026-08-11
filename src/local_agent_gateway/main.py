import logging

import uvicorn

from .app import create_app


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    uvicorn.run(create_app(), host="127.0.0.1", port=8642, access_log=False)


if __name__ == "__main__":
    run()
