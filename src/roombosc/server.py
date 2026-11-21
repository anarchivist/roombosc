"""Asynchronous OSC reception and serialized Roomba command delivery."""

import asyncio
import json
import logging
from collections.abc import Callable
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
ADDRESSES["/roomba/home"] = "home"


def validate_message(address: str, args: tuple[object, ...]) -> str:
    if address not in ADDRESSES:
        raise ValueError("unsupported OSC address")
    if args:
        raise ValueError("commands take no OSC arguments")
    return ADDRESSES[address]


class Robot(Protocol):
    def register_on_message_callback(
        self, callback: Callable[[RoombaMessage], None]
    ) -> Callable[[], None]: ...

    async def send_command(self, command: str) -> None: ...


class Bridge:
    def __init__(
        self,
        robot: Robot,
        listen_address: tuple[str, int] = ("127.0.0.1", 9000),
        *,
        robot_host: str = "unknown",
        stop_retries: int = 3,
        stop_timeout: float = 5.0,
        stop_retry_backoff: float = 1.0,
    ) -> None:
        self.stop_retries = stop_retries
        self.stop_timeout = stop_timeout
        self.stop_retry_backoff = stop_retry_backoff
        self.robot = robot
        self.robot_host = robot_host
        self.listen_address = listen_address
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
        # Route every packet through exact validation: OSC patterns must not
        # expand into multiple robot actions. Disable blocking timetag sleeps.
        self.dispatcher = Dispatcher(strict_timing=False)
        self.dispatcher.set_default_handler(self.receive_from, needs_reply_address=True)

    def receive_from(
        self, sender: tuple[str, int], address: str, *args: object
    ) -> None:
        self.receive(address, *args, sender=sender)

    def receive(
        self, address: str, *args: object, sender: tuple[str, int] | None = None
    ) -> None:
        try:
            command = validate_message(address, args)
        except ValueError as exc:
            LOG.warning("Rejected OSC message at %r: %s", address, exc)
            return
        if sender is not None:
            LOG.info(
                "Received OSC command %s from [%s]:%s on [%s]:%s",
                address,
                sender[0],
                sender[1],
                self.listen_address[0],
                self.listen_address[1],
            )
        try:
            self.queue.put_nowait(command)
        except asyncio.QueueFull:
            LOG.warning("Command queue full; command dropped")

    async def send_command(self, command: str) -> None:
        LOG.debug("Sending Roomba command %s to %s", command, self.robot_host)
        await self.robot.send_command(command)
        LOG.debug("Published Roomba command %s to %s", command, self.robot_host)

    async def stop(self) -> bool:
        stopped = asyncio.Event()

        def on_message(message: RoombaMessage) -> None:
            phase = (
                message.get("state", {})
                .get("reported", {})
                .get("cleanMissionStatus", {})
                .get("phase")
            )
            if phase == "stop":
                stopped.set()

        # Subscribe before publishing: even an immediate confirmation must be seen.
        detach = self.robot.register_on_message_callback(on_message)
        try:
            async with asyncio.timeout(self.stop_timeout):
                delay = self.stop_retry_backoff
                for attempt in range(self.stop_retries + 1):
                    if stopped.is_set():
                        break
                    await self.send_command("stop")
                    if attempt == self.stop_retries:
                        await stopped.wait()
                        break
                    try:
                        await asyncio.wait_for(stopped.wait(), timeout=delay)
                        break
                    except TimeoutError:
                        LOG.warning(
                            "Stop confirmation missing; retry %s/%s",
                            attempt + 1,
                            self.stop_retries,
                        )
                        delay *= 2
        except TimeoutError:
            LOG.error(
                "Stop failed: stopped state not confirmed within %s seconds",
                self.stop_timeout,
            )
            return False
        finally:
            detach()
        LOG.info("Roomba confirmed stopped state")
        return True

    async def run(self) -> None:
        while True:
            command = await self.queue.get()
            try:
                if command == "home":
                    if await self.stop():
                        await self.send_command("dock")
                elif command == "stop":
                    await self.stop()
                else:
                    await self.send_command(command)
            except Exception:
                # Do not retry movement commands or expose credentials in errors.
                LOG.error("Roomba command %s failed", command)
            finally:
                self.queue.task_done()


class TelemetryForwarder:
    """Log decoded Roomba messages and optionally forward them over OSC."""

    def __init__(self, client: SimpleUDPClient | None = None) -> None:
        self.client = client

    async def receive(self, message: RoombaMessage) -> None:
        LOG.debug("Received Roomba event: %r", message)
        if self.client is None:
            return
        try:
            payload = json.dumps(message, separators=(",", ":"), allow_nan=False)
            self.client.send_message("/roomba/message", payload)
        except (OSError, ValueError, TypeError):
            # UDP is best effort; keep robot reception alive after send failures.
            LOG.warning("Could not forward Roomba message")


async def serve(config: Config) -> None:
    with ExitStack() as resources:
        robot = RoombaClient(config.ip, config.blid, config.password)
        client = None
        if config.forward_host is not None:
            client = SimpleUDPClient(config.forward_host, config.forward_port)
            resources.callback(client.close)
        forwarder = TelemetryForwarder(client)
        detach = robot.register_on_message_callback(forwarder.receive)
        resources.callback(detach)
        async with robot:
            bridge = Bridge(
                robot,
                (config.listen_host, config.listen_port),
                robot_host=config.ip,
                stop_retries=config.stop_retries,
                stop_timeout=config.stop_timeout,
                stop_retry_backoff=config.stop_retry_backoff,
            )
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
