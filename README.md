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
`roombapy` 2 and `python-osc`. Supply your own IP address, BLID, and password;
the included `roombapy` CLI can help retrieve them as described below.

Install dependencies and run:

```sh
uv sync
cp config/roombosc.example.yaml roombosc.yaml
# Edit roombosc.yaml with your device credentials, then:
uv run roombosc --config roombosc.yaml
```

Starting the bridge connects to the configured robot. Importing modules, parsing
configuration, and running tests do not connect to a robot.

## Configuration

CLI settings override the flat YAML values in
[roombosc.example.yaml](config/roombosc.example.yaml). Omitted settings use these defaults:

| CLI option | YAML key | Default | Purpose / validation |
| --- | --- | --- | --- |
| `--config PATH` | — | No file | Load a YAML configuration file. |
| `--ip IP` | `ip` | Required | Roomba IPv4 or IPv6 address. |
| `--blid TEXT` | `blid` | Required | Nonempty BLID; quote it in YAML. |
| `--password TEXT` | `password` | Required | Nonempty password; quote it in YAML. |
| `--listen-host IP` | `listen_host` | `127.0.0.1` | Local OSC bind IP; use a LAN IP for remote clients. |
| `--listen-port PORT` | `listen_port` | `9000` | OSC UDP port, 1–65535. |
| `--forward-host IP` | `forward_host` | Disabled | Destination OSC server IP; setting it enables telemetry forwarding. |
| `--forward-port PORT` | `forward_port` | `9001` | Telemetry destination UDP port, 1–65535. |
| `--log-level LEVEL` | `log_level` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`; CLI is case insensitive. |
| `--log-to-file` / `--no-log-to-file` | `log_to_file` | `false` | Enable or disable file output in addition to stderr. YAML requires a boolean. |
| `--log-file PATH` | `log_file` | `log/roombosc.log` | Append UTF-8 logs here when file output is enabled; relative to the working directory. Rejects directories, symlinks, empty paths, and control characters. |
| `--stop-retries COUNT` | `stop_retries` | `3` | Additional stop attempts without state confirmation; nonnegative integer (up to four publishes by default). |
| `--stop-timeout SECONDS` | `stop_timeout` | `5.0` | Positive finite total timeout for stop publication, retries, and state confirmation. |
| `--stop-retry-backoff SECONDS` | `stop_retry_backoff` | `1.0` | Positive finite initial confirmation wait; doubles before each retry. |
| `--help` | — | — | Show command-line usage and exit. |

Example without YAML:

```sh
uv run roombosc --ip 192.168.1.50 --blid YOUR_BLID --password YOUR_PASSWORD \
  --listen-host 127.0.0.1 --listen-port 9000
```

The tracked example lives in `config/`; other files in that directory are ignored
so private configurations can be kept there.

Unknown YAML keys and invalid values are rejected. Keep real credentials in your
private, ignored `roombosc.yaml`; CLI passwords may appear in process listings.
OSC UDP has no authentication, so expose the listener only to trusted senders.

## Retrieve device credentials

The `roombapy[cli]` dependency includes discovery commands. After `uv sync`, run
these yourself on the same local network as the robot:

```sh
# Discover robots and attempt to retrieve their BLIDs and passwords:
uv run roombapy discover --raw
# Or target a known robot IP:
uv run roombapy discover --raw 192.168.1.50
```

The pinned CLI marks `--raw` as required, so these examples include it.
For local password retrieval, `roombapy` instructs you to leave the robot powered
on at its dock, hold HOME until a series of tones plays, then release it; the
Wi-Fi light flashes. Run discovery while the robot is in this mode. If discovery
reports that the password could not be obtained, it has not retrieved usable
credentials; prepare the robot again and retry.

Copy the reported IP, BLID, and password into your private `roombosc.yaml`, keeping
BLID and password quoted. Discovery output contains credentials: do not commit or
share it. The bridge does not run discovery automatically.

## OSC commands

Send a message to `/roomba/<command>` with **zero arguments**. The command
allowlist comes from the upstream [command description](https://github.com/henrythasler/roomba/blob/master/README.md#command-description),
with `home` added to stop the current mission and then dock:

| Command | Action |
| --- | --- |
| `start`, `clean` | Begin a two-pass cleaning mission |
| `quick` | Begin a single-pass mission |
| `stop` | Abort the mission and await a stopped-state report, retrying within the configured limits |
| `pause`, `resume` | Pause or resume the mission |
| `dock` | Return to the dock |
| `home` | Confirm stopped state using the same retry policy, then send `dock` |
| `fbeep` | Emit one beep |
| `find` | Toggle locator beeping |
| `off` | Power off, including Wi-Fi; requires physical wake-up |
| `sleep`, `wake` | Enter standby or wake up |

Both `stop` and `home` subscribe to robot updates before publishing `stop` and
require a fresh `cleanMissionStatus.phase: stop` report. A `lastCommand: stop`
echo or a cached stopped state is insufficient. `home` sends `dock` only after
both stop publication and stopped-state confirmation complete. Direct `dock`
continues to send docking immediately.

Without confirmation, the bridge republishes `stop` up to `stop_retries` times.
By default the confirmation waits start at 1 second and double to 2 seconds,
then 4 seconds. The five-second total deadline takes precedence: normally this
allows the initial publish and two retries (around 1 and 3 seconds), followed by
waiting until the deadline. Increasing the total timeout allows the third retry
after the 4-second wait. After the last allowed attempt, the bridge waits for
confirmation until the deadline. Publication time also counts toward that limit. Set `stop_retries: 0` for a single attempt that waits until the
deadline. No retries occur after confirmation; docking is never retried.

If confirmation times out, the failure is logged and `home` skips docking.
Publication errors also abort the operation without further retries. The temporary
state listener is removed on success, failure, or cancellation. Other commands
remain queued during this operation, while OSC reception and telemetry continue.
Confirmation reflects the robot's reported state, not independent motion sensing.

The upstream description notes that `fbeep`, `find`, and `wake` do not operate
while charging. Firmware determines actual device behavior.

Example sender:

```python
from pythonosc.udp_client import SimpleUDPClient

SimpleUDPClient("127.0.0.1", 9000).send_message("/roomba/pause", [])
```

Each accepted incoming command is logged at INFO level with its OSC address,
sender IP/port, and local listener bind IP/port. A wildcard listener such as
`0.0.0.0` is logged as that bind address. Receipt does not confirm successful
robot execution; queue overflow or send failures are logged separately.

Other addresses, address patterns, and all arguments are rejected. Commands
execute sequentially through an async worker with a 100-command queue; overflow
is dropped and logged. Future OSC timetags are processed immediately. Failed
commands are logged; only missing stop confirmations trigger the retries described above. There are no OSC replies or delivery
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

## Logging

Use `--log-level DEBUG` to show outgoing Roomba commands and their destination IP:

```sh
uv run roombosc --config roombosc.yaml --log-level DEBUG
```

See the configuration table for CLI/YAML log settings. Each outgoing
command is logged immediately before sending, including the separate `stop` and
`dock` steps of `home`. A send log records an attempt, not robot acknowledgement.

At `DEBUG`, each incoming decoded Roomba event is also logged, including nested
state values. Event logging works with OSC forwarding enabled or disabled and
continues if forwarding fails. The event callback is registered before the robot
connects and detached on shutdown. Debug event logs may contain private device
state; handle them with the same care as telemetry output.

Logs go to stderr by default. To also append to a UTF-8 log file:

```sh
uv run roombosc --config roombosc.yaml --log-level DEBUG --log-to-file
# Choose a different file:
uv run roombosc --config roombosc.yaml --log-to-file --log-file log/session.log
```

Both log outputs use the selected level and include timestamps. Parent directories
are created only when file output is enabled; existing files are appended to.
Changing `log_file` alone does not enable file output. If the file cannot be opened,
startup fails before connecting to the robot. Logs are not rotated automatically;
keep debug logs private and manage their size.
