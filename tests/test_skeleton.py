import subprocess


def test_gate_imports():
    import sys

    sys.path.insert(0, "src")
    from jev_memory import Gate, Store, Recall, Injector  # noqa: F401

    assert Gate is not None


def test_cli_help():
    out = subprocess.run(
        ["python3", "-m", "jev_memory.cli", "--help"],
        cwd="src",
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0
    assert "run the frozen eval" in out.stdout


def test_smoke_package():
    import sys

    sys.path.insert(0, "src")
    from jev_memory import __version__

    assert __version__ == "0.1.0"