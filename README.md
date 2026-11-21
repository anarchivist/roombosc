# roombosc

```
         .-----.
       .'       '.
      /  (o) (o)  \
      |   .---.   |
      \  '-----'  /
       '.       .'
         '-----'
   ===~  /roomba  ~===
```

An asynchronous Python 3.11+ OSC/UDP bridge for a Wi-Fi Roomba 960, using
`roombapy` 2 and `python-osc`. Device discovery and credential retrieval are
outside this project; supply your own IP address, BLID, and password.

Install dependencies and run:

```sh
uv sync
cp roombosc.example.yaml roombosc.yaml
# Edit roombosc.yaml with your device credentials, then:
uv run roombosc --config roombosc.yaml
```

Starting the bridge connects to the configured robot. Importing modules, parsing
configuration, and running tests do not connect to a robot.

All settings can also be passed on the command line:

```sh
uv run roombosc --ip 192.168.1.50 --blid YOUR_BLID --password YOUR_PASSWORD \
  --listen-host 127.0.0.1 --listen-port 9000
```

CLI settings override YAML values. YAML uses the flat keys shown in
[roombosc.example.yaml](roombosc.example.yaml); quote credentials so numeric
BLIDs remain strings. Unknown keys, missing credentials, invalid IP addresses,
and ports outside 1–65535 are rejected. Keep the credential file private;
`roombosc.yaml` is ignored by git. CLI passwords may appear in process listings.

The OSC listener defaults to `127.0.0.1:9000`. Set `listen_host` to the computer's
LAN IP to receive from another machine. OSC UDP provides no authentication;
expose the listener only to trusted senders.

## OSC commands

Send a message to `/roomba/<command>` with **zero arguments**. The command
allowlist comes from the upstream [command description](https://github.com/henrythasler/roomba/blob/master/README.md#command-description),
with `home` added as an alias for `dock`:

| Command | Action |
| --- | --- |
| `start`, `clean` | Begin a two-pass cleaning mission |
| `quick` | Begin a single-pass mission |
| `stop` | Abort the mission |
| `pause`, `resume` | Pause or resume the mission |
| `dock`, `home` | Return to the dock (`home` sends `dock`) |
| `fbeep` | Emit one beep |
| `find` | Toggle locator beeping |
| `off` | Power off, including Wi-Fi; requires physical wake-up |
| `sleep`, `wake` | Enter standby or wake up |

The upstream description notes that `fbeep`, `find`, and `wake` do not operate
while charging. Firmware determines actual device behavior.

Example sender:

```python
from pythonosc.udp_client import SimpleUDPClient

SimpleUDPClient("127.0.0.1", 9000).send_message("/roomba/pause", [])
```

Other addresses, address patterns, and all arguments are rejected. Commands
execute sequentially through an async worker with a 100-command queue; overflow
is dropped and logged. Future OSC timetags are processed immediately. Failed
commands are logged without automatic retry. There are no OSC replies or delivery
guarantees. Ctrl-C closes the listener, cancels pending work, and disconnects.
Connection supervision uses the native async
[roombapy 2 API](https://github.com/pschmitt/roombapy#library-usage).

## Tests

```sh
uv run pytest
```

Tests validate CLI/YAML settings, strict OSC command and argument handling,
queue bounds, ordering, and recovery after a failed command using mocks.
No robot connection is made by tests. Hardware behavior has not been verified.

## Forward robot messages to OSC

Enable outbound telemetry by setting `forward_host` to a separate OSC server's
IP address, with optional `forward_port` (default `9001`), in YAML or on the CLI:

```sh
uv run roombosc --config roombosc.yaml --forward-host 127.0.0.1 --forward-port 9001
```

Forwarding is disabled when `forward_host` is omitted. Each decoded message
received by `roombapy` is sent to `/roomba/message` as **one JSON string argument**.
This preserves nested objects, arrays, booleans, and null values for the receiver
to decode and use to trigger actions. Messages are incoming updates, not a
complete accumulated state snapshot. For example, an OSC receiver handler can
use `json.loads(args[0])` to read the original message dictionary.

The async message callback runs in the same event loop as command reception and
uses `python-osc`'s nonblocking UDP client. It is registered before connecting so
initial updates can be forwarded. Shutdown detaches the callback and closes the
client socket. Forwarding is best effort: send errors and oversized UDP messages
are dropped and logged without retries or interrupting command processing.
There is no fragmentation or acknowledgement. Choose a destination separate
from the command listener and keep it on a trusted network; telemetry may include
private device state.

## Code checks

Install development tools with `uv sync --locked --dev`, then run:

```sh
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen mypy
uv run --frozen pytest
```

Use `uv run ruff format .` to apply formatting. Ruff checks imports and common
Python errors; MyPy checks application and test code, requiring annotations for
application function definitions. GitHub Actions runs all four checks.
