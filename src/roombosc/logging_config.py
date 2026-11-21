"""Configure stderr logging with optional persistent file output."""

import logging
from pathlib import Path

from .config import Config


def configure_logging(config: Config) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if config.log_to_file:
        path = Path(config.log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError("log_file must name a regular file")
        handlers.append(logging.FileHandler(path, mode="a", encoding="utf-8"))
    logging.basicConfig(
        level=config.log_level,
        handlers=handlers,
        format="%(asctime)s %(levelname)s:%(name)s:%(message)s",
        force=True,
    )
