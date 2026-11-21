"""CLI and safe YAML configuration loading; no device I/O."""

import argparse
import math
from dataclasses import dataclass, field
from ipaddress import ip_address
from pathlib import Path

import yaml

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


@dataclass(frozen=True)
class Config:
    ip: str
    blid: str
    password: str = field(repr=False)
    listen_host: str = "127.0.0.1"
    listen_port: int = 9000

    forward_host: str | None = None
    forward_port: int = 9001
    log_level: str = "INFO"
    stop_retries: int = 3
    stop_timeout: float = 5.0
    stop_retry_backoff: float = 0.25
    log_to_file: bool = False
    log_file: str = "log/roombosc.log"

    def __post_init__(self) -> None:
        if type(self.stop_retries) is not int or self.stop_retries < 0:
            raise ValueError("stop_retries must be a nonnegative integer")
        for name in ("stop_timeout", "stop_retry_backoff"):
            value = getattr(self, name)
            if (
                type(value) not in (int, float)
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"{name} must be a positive finite number")
        if type(self.log_to_file) is not bool:
            raise ValueError("log_to_file must be a boolean")
        if (
            not isinstance(self.log_file, str)
            or not self.log_file.strip()
            or any(ord(char) < 32 for char in self.log_file)
        ):
            raise ValueError(
                "log_file must be a nonempty path without control characters"
            )
        path = Path(self.log_file)
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError(
                "log_file must name a regular file, not a directory or symlink"
            )
        if self.log_level not in LOG_LEVELS:
            raise ValueError(
                "log_level must be DEBUG, INFO, WARNING, ERROR, or CRITICAL"
            )
        for name in ("ip", "listen_host", "forward_host"):
            if name == "forward_host" and self.forward_host is None:
                continue
            value = getattr(self, name)
            if not isinstance(value, str):
                raise ValueError(f"{name} must be an IP address string")
            try:
                ip_address(value)
            except ValueError:
                raise ValueError(f"{name} must be an IPv4 or IPv6 address") from None
        for name in ("blid", "password"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"{name} must be a nonempty string (quote YAML credentials)"
                )
        for name in ("listen_port", "forward_port"):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= 65535:
                raise ValueError(f"{name} must be an integer between 1 and 65535")


def parse_config(argv: list[str] | None = None) -> Config:
    parser = argparse.ArgumentParser(description="Async OSC bridge for a Roomba 960")
    parser.add_argument("--config", type=Path, help="YAML configuration file")
    parser.add_argument("--ip", help="Roomba IP address")
    parser.add_argument("--blid", help="Roomba BLID")
    parser.add_argument("--password", help="Roomba password")
    parser.add_argument("--listen-host", help="OSC bind IP (default: 127.0.0.1)")
    parser.add_argument("--listen-port", type=int, help="OSC UDP port (default: 9000)")
    parser.add_argument(
        "--forward-host", help="Destination OSC server IP; enables telemetry forwarding"
    )
    parser.add_argument(
        "--forward-port", type=int, help="Destination OSC UDP port (default: 9001)"
    )
    parser.add_argument(
        "--log-level",
        type=str.upper,
        choices=LOG_LEVELS,
        help="Application log level (default: INFO)",
    )
    parser.add_argument(
        "--log-to-file",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Also write logs to a file (default: disabled)",
    )
    parser.add_argument(
        "--log-file",
        help="Log path (default: log/roombosc.log); requires --log-to-file",
    )
    parser.add_argument(
        "--stop-retries", type=int, help="Additional stop attempts (default: 3)"
    )
    parser.add_argument(
        "--stop-timeout",
        type=float,
        help="Total stop confirmation timeout in seconds (default: 5)",
    )
    parser.add_argument(
        "--stop-retry-backoff",
        type=float,
        help="Initial confirmation wait in seconds, doubled per retry (default: 0.25)",
    )
    args = parser.parse_args(argv)
    values = {}
    if args.config:
        try:
            values = yaml.safe_load(args.config.read_text(encoding="utf-8"))
        except OSError:
            parser.error("cannot read configuration file")
        except yaml.YAMLError:
            parser.error("invalid YAML configuration")
        if not isinstance(values, dict) or any(
            key not in Config.__dataclass_fields__ for key in values
        ):
            parser.error(
                "configuration must be a mapping with only ip, blid, password, listen_host, listen_port, forward_host, forward_port, log_level, log_to_file, log_file, stop_retries, stop_timeout, stop_retry_backoff"
            )
    values.update(
        {
            key: value
            for key, value in vars(args).items()
            if key != "config" and value is not None
        }
    )
    missing = {"ip", "blid", "password"} - values.keys()
    if missing:
        parser.error("missing settings: " + ", ".join(sorted(missing)))
    try:
        return Config(**values)
    except ValueError as exc:
        parser.error(str(exc))
