"""The Chrome extension finds Study Terminal when it had to move off port 8765. Runs the real app (window-free mode of the desktop
launcher) and the extension's own common.js in Node, with only chrome.storage faked. Skipped if Node isn't installed."""
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NODE = shutil.which("node")

SCRIPT = r"""
const store = { port: 8765, token: "not-the-real-code", enabled: true, found_at: null };
globalThis.chrome = {
  storage: { local: { get: async (d) => ({ ...d, ...store }), set: async (o) => { Object.assign(store, o); } } },
  runtime: { getManifest: () => ({ version: "test" }) },
};
const m = await import(process.argv[2]);
const found = await m.findApp(8765);
let err = null;
try { await m.call("/status"); } catch (e) { err = e.message; }
console.log(JSON.stringify({ found, stored: store.port, found_at: !!store.found_at, err }));
"""



@pytest.mark.skipif(NODE is None, reason="Node isn't installed")
def test_extension_finds_the_app_on_another_port(tmp_path):
    blocker = socket.socket()
    try:
        blocker.bind(("127.0.0.1", 8765))
        blocker.listen(1)
    except OSError:
        blocker.close()
        blocker = None                       # something else already has 8765: that's the situation being tested anyway
    stop = tmp_path / "stop"
    env = {**os.environ, "STUDY_TERMINAL_DATA_DIR": str(tmp_path / "data"), "STUDY_TERMINAL_NO_ENV_FILE": "1", "PORT": "8765"}
    env.pop("PYTHONPATH", None)
    proc = subprocess.Popen([sys.executable, str(ROOT / "desktop" / "launcher.py"), "--headless", "--stop-file", str(stop)],
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        port = None
        t0 = time.time()
        while time.time() - t0 < 150 and port is None:
            line = proc.stdout.readline()
            if not line and proc.poll() is not None:
                break
            if line.startswith("headless: listening on"):
                port = int(line.split()[-1])
        assert port and port != 8765, "the app should have moved off the blocked port"
        script = tmp_path / "t.mjs"
        script.write_text(SCRIPT)
        out = subprocess.run([NODE, str(script), (ROOT / "extension" / "common.js").as_uri()], capture_output=True, text=True,
                             timeout=120)
        r = json.loads(out.stdout.strip().splitlines()[-1])
        assert r["found"] == port and r["stored"] == port and r["found_at"]
        assert "turned off" in r["err"]       # it reached the real app: the bridge is off by default, and it says so clearly
    finally:
        stop.write_text("stop")
        try:
            proc.wait(60)
        except subprocess.TimeoutExpired:
            proc.kill()
        if blocker:
            blocker.close()
