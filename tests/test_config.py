import pytest

from roombosc.config import Config, parse_config

BASE = ["--ip", "192.168.1.50", "--blid", "abc", "--password", "secret"]


def test_cli_defaults_and_secret_repr():
    config = parse_config(BASE)
    assert config.listen_port == 9000
    assert config.listen_host == "127.0.0.1"
    assert "secret" not in repr(config)


def test_yaml_and_cli_override(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        'ip: "192.168.1.51"\nblid: "123"\npassword: "secret"\nlisten_port: 8000\n'
    )
    config = parse_config(["--config", str(path), "--listen-port", "9001"])
    assert config.ip == "192.168.1.51"
    assert config.blid == "123"
    assert config.listen_port == 9001


@pytest.mark.parametrize(
    "extra",
    [
        ["--ip", "hostname"],
        ["--ip", "999.1.1.1"],
        ["--blid", ""],
        ["--password", " "],
        ["--listen-port", "0"],
        ["--listen-port", "65536"],
        ["--listen-port", "abc"],
        ["--listen-host", "invalid"],
        ["--unknown"],
    ],
)
def test_bad_cli(extra):
    with pytest.raises(SystemExit) as exc:
        parse_config(BASE + extra)
    assert exc.value.code == 2


def test_missing_credentials():
    with pytest.raises(SystemExit):
        parse_config([])


@pytest.mark.parametrize(
    "content",
    [
        "",
        "[]",
        "abc",
        "ip: [",
        "unknown: value",
        'ip: "192.168.1.50"\nblid: 123\npassword: "secret"',
        'ip: "192.168.1.50"\nblid: "abc"\npassword: null',
        'ip: "192.168.1.50"\nblid: "abc"\npassword: "secret"\nlisten_port: true',
        '!!python/object/apply:os.system ["echo unsafe"]',
    ],
)
def test_bad_yaml(tmp_path, content):
    path = tmp_path / "config.yaml"
    path.write_text(content)
    with pytest.raises(SystemExit):
        parse_config(["--config", str(path)])


def test_unreadable_config(tmp_path):
    with pytest.raises(SystemExit):
        parse_config(["--config", str(tmp_path / "missing")])


def test_ipv6_and_port_bounds():
    assert Config("::1", "abc", "secret", "::", 65535).listen_port == 65535
    assert Config("127.0.0.1", "abc", "secret", listen_port=1).listen_port == 1


def test_forward_destination():
    config = parse_config(BASE + ["--forward-host", "::1", "--forward-port", "9002"])
    assert config.forward_host == "::1"
    assert config.forward_port == 9002
    assert parse_config(BASE).forward_host is None


@pytest.mark.parametrize(
    "extra",
    [
        ["--forward-host", "invalid"],
        ["--forward-port", "0"],
        ["--forward-port", "65536"],
        ["--forward-port", "abc"],
    ],
)
def test_invalid_forward_destination(extra):
    with pytest.raises(SystemExit):
        parse_config(BASE + extra)


def test_forward_yaml_override(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text('forward_host: "127.0.0.2"\nforward_port: 8001\n')
    config = parse_config(BASE + ["--config", str(path), "--forward-port", "9003"])
    assert config.forward_host == "127.0.0.2"
    assert config.forward_port == 9003


@pytest.mark.parametrize("level", ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
def test_log_level_cli(level):
    assert parse_config(BASE + ["--log-level", level.lower()]).log_level == level


def test_log_level_defaults_and_yaml_override(tmp_path):
    assert parse_config(BASE).log_level == "INFO"
    path = tmp_path / "config.yaml"
    path.write_text('log_level: "WARNING"\n')
    assert parse_config(BASE + ["--config", str(path)]).log_level == "WARNING"
    assert (
        parse_config(BASE + ["--config", str(path), "--log-level", "DEBUG"]).log_level
        == "DEBUG"
    )


@pytest.mark.parametrize("value", ["INVALID", "", None, 10])
def test_invalid_log_level(value):
    with pytest.raises(ValueError, match="log_level"):
        Config("127.0.0.1", "fake", "fake", log_level=value)


def test_invalid_cli_log_level():
    with pytest.raises(SystemExit):
        parse_config(BASE + ["--log-level", "invalid"])


def test_file_logging_options(tmp_path):
    default = parse_config(BASE)
    assert default.log_to_file is False
    assert default.log_file == "log/roombosc.log"
    path = tmp_path / "config.yaml"
    path.write_text('log_to_file: true\nlog_file: "custom.log"\n')
    configured = parse_config(BASE + ["--config", str(path)])
    assert configured.log_to_file is True
    assert configured.log_file == "custom.log"
    assert not parse_config(
        BASE + ["--config", str(path), "--no-log-to-file"]
    ).log_to_file
    override = parse_config(BASE + ["--config", str(path), "--log-file", "other.log"])
    assert override.log_file == "other.log"
    assert parse_config(BASE + ["--log-to-file"]).log_to_file
    assert not parse_config(BASE + ["--log-file", "other.log"]).log_to_file


@pytest.mark.parametrize("value", ["", " ", "bad\x00path", "bad\npath", None, 42])
def test_invalid_log_file(value):
    with pytest.raises(ValueError, match="log_file"):
        Config("127.0.0.1", "fake", "fake", log_file=value)


@pytest.mark.parametrize("value", ["true", None, 1])
def test_invalid_log_to_file(value):
    with pytest.raises(ValueError, match="log_to_file"):
        Config("127.0.0.1", "fake", "fake", log_to_file=value)


def test_log_file_directory_and_symlink(tmp_path):
    for path in (tmp_path, tmp_path / "link"):
        if path != tmp_path:
            path.symlink_to(tmp_path / "missing")
        with pytest.raises(ValueError, match="log_file"):
            Config("127.0.0.1", "fake", "fake", log_file=str(path))


@pytest.mark.parametrize(
    "name,value",
    [
        ("stop_retries", -1),
        ("stop_retries", True),
        ("stop_retries", 1.5),
        ("stop_timeout", 0),
        ("stop_timeout", float("inf")),
        ("stop_timeout", float("nan")),
        ("stop_retry_backoff", -1),
        ("stop_retry_backoff", True),
    ],
)
def test_invalid_stop_settings(name, value):
    with pytest.raises(ValueError, match=name):
        Config("127.0.0.1", "fake", "fake", **{name: value})


def test_stop_settings_cli_yaml(tmp_path):
    config = parse_config(BASE)
    assert (config.stop_retries, config.stop_timeout, config.stop_retry_backoff) == (
        3,
        5,
        0.25,
    )
    path = tmp_path / "config.yaml"
    path.write_text("stop_retries: 1\nstop_timeout: 2\nstop_retry_backoff: 0.1\n")
    config = parse_config(
        BASE
        + [
            "--config",
            str(path),
            "--stop-retries",
            "0",
            "--stop-timeout",
            "3",
            "--stop-retry-backoff",
            "0.2",
        ]
    )
    assert (config.stop_retries, config.stop_timeout, config.stop_retry_backoff) == (
        0,
        3,
        0.2,
    )
