"""CLI and safe YAML configuration loading; no device I/O."""

import argparse
from dataclasses import dataclass, field
from ipaddress import ip_address
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Config:
    ip: str
    blid: str
    password: str = field(repr=False)
    listen_host: str = "127.0.0.1"
    listen_port: int = 9000

    forward_host: str | None = None
    forward_port: int = 9001

    def __post_init__(self):
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
                raise ValueError(f"{name} must be a nonempty string (quote YAML credentials)")
        for name in ("listen_port", "forward_port"):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= 65535:
                raise ValueError(f"{name} must be an integer between 1 and 65535")


def parse_config(argv=None) -> Config:
    parser = argparse.ArgumentParser(description="Async OSC bridge for a Roomba 960")
    parser.add_argument("--config", type=Path, help="YAML configuration file")
    parser.add_argument("--ip", help="Roomba IP address")
    parser.add_argument("--blid", help="Roomba BLID")
    parser.add_argument("--password", help="Roomba password")
    parser.add_argument("--listen-host", help="OSC bind IP (default: 127.0.0.1)")
    parser.add_argument("--listen-port", type=int, help="OSC UDP port (default: 9000)")
    parser.add_argument("--forward-host", help="Destination OSC server IP; enables telemetry forwarding")
    parser.add_argument("--forward-port", type=int, help="Destination OSC UDP port (default: 9001)")
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
            parser.error("configuration must be a mapping with only ip, blid, password, listen_host, listen_port, forward_host, forward_port")
    values.update({key: value for key, value in vars(args).items()
                   if key != "config" and value is not None})
    missing = {"ip", "blid", "password"} - values.keys()
    if missing:
        parser.error("missing settings: " + ", ".join(sorted(missing)))
    try:
        return Config(**values)
    except ValueError as exc:
        parser.error(str(exc))
