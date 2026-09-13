#!/usr/bin/env python3
"""phoneuse-agent control plane.

Registry + health polling + live screen + task runner for a fleet of Android
phone nodes. Reads nodes.json, polls every node over adb, and runs natural-
language tasks through the mobilerun CLI against any node in the fleet.

Run:  uvicorn server:app --host 0.0.0.0 --port 8787     (from farm/)
Env:  MOBILERUN_BIN   path to the mobilerun CLI (default: found on PATH)
      NODES_FILE      override registry path (default: ./nodes.json)
"""
import asyncio
import base64
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

ROOT = Path(__file__).parent
NODES_FILE = Path(os.environ.get("NODES_FILE", ROOT / "nodes.json"))
TASKLOG = ROOT / "task.log"
MOBILERUN = os.environ.get("MOBILERUN_BIN") or shutil.which("mobilerun") or "mobilerun"

app = FastAPI(title="phoneuse-agent")


def adb(serial: str, cmd: str, timeout: int = 10) -> str:
    """Run a shell command on one node; '' on any failure (offline, timeout)."""
    try:
        r = subprocess.run(["adb", "-s", serial, "shell", cmd],
                           capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""


def connected_serials() -> set[str]:
    try:
        out = subprocess.run(["adb", "devices"], capture_output=True, text=True,
                             timeout=10).stdout
    except Exception:
        return set()
    serials = set()
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            serials.add(parts[0])
    return serials


def load_nodes() -> list[dict]:
    try:
        return json.loads(NODES_FILE.read_text())
    except Exception:
        return []


def node_health(node: dict, online: set[str]) -> dict:
    s = node["serial"]
    h = {"serial": s, "name": node.get("name", s), "role": node.get("role", ""),
         "online": s in online}
    if not h["online"]:
        return h
    h["model"] = adb(s, "getprop ro.product.model")
    h["android"] = adb(s, "getprop ro.build.version.release")
    bat = adb(s, "dumpsys battery")
    for line in bat.splitlines():
        if "level: " in line:
            h["battery"] = int(line.split("level: ")[1].split()[0])
        if "temperature: " in line:
            h["temp"] = int(line.split("temperature: ")[1].split()[0]) / 10
        if "status: " in line:
            h["charging"] = line.split("status: ")[1].strip() in ("2", "5")
    h["ip"] = adb(s, "ip -f inet addr show wlan0 | grep -oE 'inet [0-9.]+'").replace("inet ", "")
    # 0x1F56 == 8022 (be), present in /proc/net/tcp if sshd listens
    h["sshd"] = "1F56" in adb(s, "cat /proc/net/tcp /proc/net/tcp6").upper()
    h["a11y"] = "phoneuse.control" in adb(s, "settings get secure enabled_accessibility_services")
    h["mem"] = adb(s, "grep -E 'MemTotal|MemAvailable' /proc/meminfo")
    return h


@app.get("/api/nodes")
async def nodes():
    online = await asyncio.to_thread(connected_serials)
    return await asyncio.to_thread(
        lambda: [node_health(n, online) for n in load_nodes()])


@app.get("/api/screen/{serial}")
async def screen(serial: str):
    def grab():
        r = subprocess.run(["adb", "-s", serial, "exec-out", "screencap", "-p"],
                           capture_output=True, timeout=15)
        return base64.b64encode(r.stdout).decode()
    try:
        return JSONResponse({"png": await asyncio.to_thread(grab)})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


class Task(BaseModel):
    serial: str
    task: str


_current = {"running": False, "serial": None, "task": None, "started": None}


@app.post("/api/task")
async def run_task(t: Task):
    if _current["running"]:
        return JSONResponse({"error": "task already running"}, status_code=409)
    known = {n["serial"] for n in load_nodes()}
    if t.serial not in known:
        return JSONResponse({"error": f"unknown node {t.serial}"}, status_code=400)
    TASKLOG.write_text("")
    _current.update(running=True, serial=t.serial, task=t.task, started=time.time())

    async def _run():
        cmd = [MOBILERUN, "run", "--no-reasoning", "--steps", "15",
               "-d", t.serial, t.task]
        with TASKLOG.open("w") as f:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=f, stderr=subprocess.STDOUT)
            await proc.wait()
        _current["running"] = False

    asyncio.create_task(_run())
    return {"started": True}


@app.get("/api/task")
async def task_status():
    log = TASKLOG.read_text()[-3000:] if TASKLOG.exists() else ""
    return {**_current, "log_tail": log}


@app.get("/", response_class=HTMLResponse)
async def index():
    return (ROOT / "static/index.html").read_text()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8787, log_level="warning")
