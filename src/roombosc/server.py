"""Asynchronous OSC reception and serialized Roomba command delivery."""

import asyncio
import json
import logging
from contextlib import ExitStack, suppress
from typing import Protocol, cast

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import AsyncIOOSCUDPServer
from pythonosc.udp_client import SimpleUDPClient
from roombapy import RoombaClient, RoombaMessage

from .config import Config

LOG = logging.getLogger(__name__)
COMMANDS = frozenset(
    {
        "start",
        "clean",
        "quick",
        "stop",
        "pause",
        "resume",
        "dock",
        "fbeep",
        "find",
        "off",
        "sleep",
        "wake",
    }
)
ADDRESSES = {f"/roomba/{command}": command for command in COMMANDS}


def validate_message(address: str, args: tuple[object, ...]) -> str:
    if address not in ADDRESSES:
        raise ValueError("unsupported OSC address")
    if args:
        raise ValueError("commands take no OSC arguments")
    return ADDRESSES[address]


class Robot(Protocol):
    async def send_command(self, command: str) -> None: ...


class Bridge:
    def __init__(self, robot: Robot) -> None:
        self.robot = robot
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
        # Route every packet through exact validation: OSC patterns must not
        # expand into multiple robot actions. Disable blocking timetag sleeps.
        self.dispatcher = Dispatcher(strict_timing=False)
        self.dispatcher.set_default_handler(self.receive)

    def receive(self, address: str, *args: object) -> None:
        try:
            command = validate_message(address, args)
        except ValueError as exc:
            LOG.warning("Rejected OSC message: %s", exc)
            return
        try:
            self.queue.put_nowait(command)
        except asyncio.QueueFull:
            LOG.warning("Command queue full; command dropped")

    async def run(self) -> None:
        while True:
            command = await self.queue.get()
            try:
                await self.robot.send_command(command)
            except Exception:
                # Do not retry movement commands or expose credentials in errors.
                LOG.error("Roomba command %s failed", command)
            finally:
                self.queue.task_done()


class TelemetryForwarder:
    """Forward each decoded Roomba message as one JSON OSC string argument."""

    def __init__(self, client: SimpleUDPClient) -> None:
        self.client = client

    async def receive(self, message: RoombaMessage) -> None:
        try:
            payload = json.dumps(message, separators=(",", ":"), allow_nan=False)
            self.client.send_message("/roomba/message", payload)
        except (OSError, ValueError, TypeError):
            # UDP is best effort; keep robot reception alive after send failures.
            LOG.warning("Could not forward Roomba message")


async def serve(config: Config) -> None:
    with ExitStack() as resources:
        robot = RoombaClient(config.ip, config.blid, config.password)
        if config.forward_host is not None:
            client = SimpleUDPClient(config.forward_host, config.forward_port)
            resources.callback(client.close)
            forwarder = TelemetryForwarder(client)
            detach = robot.register_on_message_callback(forwarder.receive)
            resources.callback(detach)
        async with robot:
            bridge = Bridge(robot)
            server = AsyncIOOSCUDPServer(
                (config.listen_host, config.listen_port),
                bridge.dispatcher,
                # python-osc annotates the concrete loop rather than its interface.
                cast(asyncio.BaseEventLoop, asyncio.get_running_loop()),
            )
            transport, _ = await server.create_serve_endpoint()
            worker = asyncio.create_task(bridge.run())
            LOG.info("Listening on %s:%s", config.listen_host, config.listen_port)
            try:
                await asyncio.Future()
            finally:
                transport.close()
                worker.cancel()
                with suppress(asyncio.CancelledError):
                    await worker
