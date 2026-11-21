"""OSC to Roomba bridge."""


def main() -> None:
    import asyncio
    import logging

    from .config import parse_config
    from .logging_config import configure_logging
    from .server import serve

    config = parse_config()
    try:
        configure_logging(config)
    except (OSError, ValueError):
        logging.basicConfig(level=config.log_level)
        logging.getLogger(__name__).error("Cannot open configured log file")
        raise SystemExit(1) from None
    try:
        asyncio.run(serve(config))
    except KeyboardInterrupt:
        pass
    except Exception:
        logging.getLogger(__name__).error(
            "Bridge stopped: connection or server failure"
        )
        raise SystemExit(1) from None
    finally:
        logging.shutdown()
