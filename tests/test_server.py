import asyncio
from unittest.mock import AsyncMock

import pytest
from pythonosc.osc_message_builder import OscMessageBuilder

from roombosc.server import ADDRESSES, Bridge, validate_message


@pytest.mark.parametrize(
    "command",
    [
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
    ],
)
def test_supported_commands(command):
    assert validate_message(f"/roomba/{command}", ()) == command


@pytest.mark.parametrize(
    "address",
    [
        "/roomba/reset",
        "/roomba/start/",
        "/roomba/START",
        "/start",
        "/roomba/*",
        "/roomba/{start,stop}",
        "/roomba/sta?t",
    ],
)
def test_reject_addresses(address):
    bridge = Bridge(AsyncMock())
    packet = OscMessageBuilder(address=address).build()
    bridge.dispatcher.call_handlers_for_packet(packet.dgram, ("127.0.0.1", 1234))
    assert bridge.queue.empty()


@pytest.mark.parametrize("args", [(1,), (True,), ("start",), (None,), ([],), (1, 2)])
@pytest.mark.parametrize("address", ADDRESSES)
def test_reject_parameters(address, args):
    with pytest.raises(ValueError):
        validate_message(address, args)


def test_order_failure_recovery_and_shutdown():
    async def scenario():
        robot = AsyncMock()
        robot.send_command.side_effect = [RuntimeError("failure"), None]
        bridge = Bridge(robot)
        bridge.receive("/roomba/start")
        bridge.receive("/roomba/stop")
        worker = asyncio.create_task(bridge.run())
        await asyncio.wait_for(bridge.queue.join(), timeout=1)
        assert [call.args[0] for call in robot.send_command.await_args_list] == [
            "start",
            "stop",
        ]
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker

    asyncio.run(scenario())


def test_queue_bounded():
    bridge = Bridge(AsyncMock())
    for _ in range(101):
        bridge.receive("/roomba/pause")
    assert bridge.queue.qsize() == 100


def test_forward_message_and_recover():
    import json
    from unittest.mock import Mock

    from roombosc.server import TelemetryForwarder

    async def scenario():
        client = Mock()
        forwarder = TelemetryForwarder(client)
        message = {
            "state": {"reported": {"batPct": 75, "ready": True}},
            "items": [None, "é"],
        }
        await forwarder.receive(message)
        address, payload = client.send_message.call_args.args
        assert address == "/roomba/message"
        assert json.loads(payload) == message
        client.send_message.side_effect = OSError("unavailable")
        await forwarder.receive(message)
        client.send_message.side_effect = None
        await forwarder.receive(message)
        assert client.send_message.call_count == 3

    asyncio.run(scenario())


@pytest.mark.parametrize("forward_host", [None, "127.0.0.2"])
def test_serve_forwarding_lifecycle(monkeypatch, forward_host):
    from unittest.mock import Mock

    import roombosc.server as server
    from roombosc.config import Config

    async def scenario():
        robot = AsyncMock()
        robot.__aenter__.return_value = robot
        detach = Mock()
        robot.register_on_message_callback = Mock(return_value=detach)
        monkeypatch.setattr(server, "RoombaClient", Mock(return_value=robot))
        client = Mock()
        factory = Mock(return_value=client)
        monkeypatch.setattr(server, "SimpleUDPClient", factory)
        transport = Mock()
        endpoint = AsyncMock(return_value=(transport, Mock()))
        monkeypatch.setattr(
            server,
            "AsyncIOOSCUDPServer",
            Mock(return_value=Mock(create_serve_endpoint=endpoint)),
        )
        task = asyncio.create_task(
            server.serve(Config("127.0.0.1", "fake", "fake", forward_host=forward_host))
        )
        for _ in range(10):
            if endpoint.await_count:
                break
            await asyncio.sleep(0)
        callback = robot.register_on_message_callback.call_args.args[0]
        await callback({"battery": 42})
        if forward_host is not None:
            client.send_message.assert_called_once_with(
                "/roomba/message", '{"battery":42}'
            )
            factory.assert_called_once_with(forward_host, 9001)
        else:
            factory.assert_not_called()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        detach.assert_called_once()
        if forward_host is not None:
            client.close.assert_called_once()
        transport.close.assert_called_once()
        robot.__aexit__.assert_awaited_once()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("address", "expected"),
    [("/roomba/dock", ["dock"]), ("/roomba/home", ["stop", "dock"])],
)
def test_docking_dispatch(address, expected):
    async def scenario():
        robot = AsyncMock()
        bridge = Bridge(robot)
        packet = OscMessageBuilder(address=address).build()
        bridge.dispatcher.call_handlers_for_packet(packet.dgram, ("127.0.0.1", 1234))
        worker = asyncio.create_task(bridge.run())
        await asyncio.wait_for(bridge.queue.join(), timeout=1)
        assert [call.args[0] for call in robot.send_command.await_args_list] == expected
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker

    asyncio.run(scenario())


@pytest.mark.parametrize("fail_stop", [False, True])
def test_home_sequence_and_failure_recovery(fail_stop):
    async def scenario():
        robot = AsyncMock()
        if fail_stop:
            robot.send_command.side_effect = [RuntimeError("stop failed"), None]
        bridge = Bridge(robot)
        bridge.receive("/roomba/home")
        bridge.receive("/roomba/pause")
        worker = asyncio.create_task(bridge.run())
        await asyncio.wait_for(bridge.queue.join(), timeout=1)
        expected = ["stop", "pause"] if fail_stop else ["stop", "dock", "pause"]
        assert [call.args[0] for call in robot.send_command.await_args_list] == expected
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker

    asyncio.run(scenario())


@pytest.mark.parametrize("host", ["127.0.0.1", "::1"])
def test_incoming_command_logs_endpoints(caplog, host):
    import logging

    bridge = Bridge(AsyncMock(), (host, 9002))
    packet = OscMessageBuilder(address="/roomba/home").build()
    with caplog.at_level(logging.INFO, logger="roombosc.server"):
        bridge.dispatcher.call_handlers_for_packet(packet.dgram, (host, 4567))
    assert (
        f"Received OSC command /roomba/home from [{host}]:4567 on [{host}]:9002"
        in caplog.text
    )
    assert bridge.queue.get_nowait() == "home"


def test_rejected_command_does_not_log_arguments(caplog):
    import logging

    bridge = Bridge(AsyncMock())
    builder = OscMessageBuilder(address="/roomba/start")
    builder.add_arg("FAKE_PRIVATE_ARGUMENT")
    with caplog.at_level(logging.INFO, logger="roombosc.server"):
        bridge.dispatcher.call_handlers_for_packet(
            builder.build().dgram, ("127.0.0.1", 4567)
        )
    assert "FAKE_PRIVATE_ARGUMENT" not in caplog.text
    assert "Received OSC command" not in caplog.text
    assert bridge.queue.empty()


@pytest.mark.parametrize("level, logged", [(10, True), (20, False)])
def test_outgoing_command_logging(caplog, level, logged):
    async def scenario():
        robot = AsyncMock()
        bridge = Bridge(robot, robot_host="192.0.2.50")
        bridge.receive("/roomba/home")
        worker = asyncio.create_task(bridge.run())
        with caplog.at_level(level, logger="roombosc.server"):
            await asyncio.wait_for(bridge.queue.join(), timeout=1)
        messages = [r.getMessage() for r in caplog.records if r.levelno == 10]
        expected = [
            "Sending Roomba command stop to 192.0.2.50",
            "Sending Roomba command dock to 192.0.2.50",
        ]
        assert messages == (expected if logged else [])
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker

    asyncio.run(scenario())


@pytest.mark.parametrize("address", ["/roomba/unknown", "/roomba/*", "/bad\naddress"])
def test_unsupported_address_logged(caplog, address):
    bridge = Bridge(AsyncMock())
    builder = OscMessageBuilder(address=address)
    builder.add_arg("FAKE_PRIVATE_ARGUMENT")
    bridge.dispatcher.call_handlers_for_packet(
        builder.build().dgram, ("127.0.0.1", 4567)
    )
    assert (
        f"Rejected OSC message at {address!r}: unsupported OSC address" in caplog.text
    )
    assert "FAKE_PRIVATE_ARGUMENT" not in caplog.text
    assert bridge.queue.empty()


@pytest.mark.parametrize("level, expected", [(10, True), (20, False)])
@pytest.mark.parametrize("forward", [False, True])
def test_incoming_event_debug_logging(caplog, level, expected, forward):
    from unittest.mock import Mock

    from roombosc.server import TelemetryForwarder

    client = Mock() if forward else None
    if client is not None:
        client.send_message.side_effect = OSError("send failed")
    message = {"state": {"reported": {"batPct": 75}}, "text": "line\nnext"}
    with caplog.at_level(level, logger="roombosc.server"):
        asyncio.run(TelemetryForwarder(client).receive(message))
    events = [r.getMessage() for r in caplog.records if r.levelno == 10]
    assert events == ([f"Received Roomba event: {message!r}"] if expected else [])
    if client is not None:
        client.send_message.assert_called_once()
