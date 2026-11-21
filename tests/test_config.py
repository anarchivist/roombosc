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
