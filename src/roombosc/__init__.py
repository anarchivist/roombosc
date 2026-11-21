"""OSC to Roomba bridge."""


def main() -> None:
    import asyncio
    import logging

    from .config import parse_config
    from .server import serve

    config = parse_config()
    logging.basicConfig(level=config.log_level)
    try:
        asyncio.run(serve(config))
    except KeyboardInterrupt:
        pass
    except Exception:
        logging.getLogger(__name__).error(
            "Bridge stopped: connection or server failure"
        )
        raise SystemExit(1) from None
