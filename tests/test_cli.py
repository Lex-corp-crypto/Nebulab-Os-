"""
Tests for NebulaLab CLI (nebulalab.py)
"""
import sys
import subprocess
import pytest

def test_cli_help():
    res = subprocess.run([sys.executable, "nebulalab.py", "--help"], capture_output=True, text=True)
    assert res.returncode == 0
    assert "NebulaLab OS" in res.stdout
    assert "version" in res.stdout
    assert "nodes" in res.stdout
    assert "download" in res.stdout
    assert "rm-file" in res.stdout
    assert "jobs" in res.stdout

def test_cli_version():
    res = subprocess.run([sys.executable, "nebulalab.py", "version"], capture_output=True, text=True)
    assert res.returncode == 0
    assert "2.1.0" in res.stdout

def test_cli_doctor():
    res = subprocess.run([sys.executable, "nebulalab.py", "doctor"], capture_output=True, text=True)
    assert res.returncode == 0
    assert "Auto-diagnostic Système" in res.stdout
    assert "Toutes les dépendances sont installées" in res.stdout

def test_cli_subcommands_syntax():
    # Test that each new subcommand responds gracefully without crashing or raising unhandled exceptions
    for subcmd in [["nodes"], ["files"], ["jobs"], ["tunnel"]]:
        res = subprocess.run([sys.executable, "nebulalab.py"] + subcmd + ["--api", "http://127.0.0.1:59999"], capture_output=True, text=True)
        # Should exit cleanly or report unable to connect, without Python traceback
        assert "Traceback" not in res.stderr
        assert res.returncode == 0 or "Impossible de joindre" in res.stdout or "Erreur" in res.stdout
