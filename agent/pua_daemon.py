#!/usr/bin/env python3
"""pua-daemon — persistent on-device phone-use agent.

Watches ~/.pua/tasks/*.json ({"id": "...", "task": "...", "steps": 15}),
runs pua_agent on each, writes ~/.pua/results/<id>.json.
Started by Termux:Boot on device boot; supervised by a shell while-loop.

Queue a task from anywhere:
  ssh -p 8022 phone 'echo {\"id\":\"t1\",\"task\":\"open whatsapp\"} > ~/.pua/tasks/t1.json'
Read result:
  ssh -p 8022 phone 'cat ~/.pua/results/t1.json'
"""
import json, os, pathlib, subprocess, sys, time, traceback

# self-sufficient: load env file (daemon starts from Termux:Boot without shell profile)
_env = pathlib.Path.home() / ".pua.env"
if _env.exists():
    for line in _env.read_text().splitlines():
        m = line.strip()
        if m.startswith("export "):
            m = m[7:]
        if "=" in m:
            k, v = m.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

HOME = pathlib.Path.home()
PUA = HOME / ".pua"
TASKS = PUA / "tasks"
RESULTS = PUA / "results"
HEARTBEAT = PUA / "heartbeat"
AGENT = HOME / "pua_agent.py"
for d in (TASKS, RESULTS):
    d.mkdir(parents=True, exist_ok=True)

def log(msg: str):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    with open(PUA / "daemon.log", "a") as f:
        f.write(line + "\n")

def run_task(path: pathlib.Path):
    try:
        spec = json.loads(path.read_text())
    except Exception as e:
        log(f"bad task file {path.name}: {e}")
        path.unlink(missing_ok=True)
        return
    tid = spec.get("id") or path.stem
    task = spec["task"]
    steps = str(spec.get("steps", 15))
    log(f"task {tid} start: {task[:80]}")
    t0 = time.time()
    try:
        r = subprocess.run(
            [sys.executable, str(AGENT), task, "--steps", steps],
            capture_output=True, text=True, timeout=spec.get("timeout", 600),
        )
        out = r.stdout + r.stderr
        answer = ""
        for line in out.splitlines():
            if line.startswith("DONE:"):
                answer = line[5:].strip()
        result = {"id": tid, "ok": bool(answer), "answer": answer,
                  "seconds": round(time.time() - t0, 1), "log": out[-4000:]}
    except Exception as e:
        result = {"id": tid, "ok": False, "answer": "",
                  "seconds": round(time.time() - t0, 1),
                  "log": f"daemon error: {e}\n{traceback.format_exc()[-1500:]}"}
    (RESULTS / f"{tid}.json").write_text(json.dumps(result, indent=2))
    path.unlink(missing_ok=True)
    log(f"task {tid} done ok={result['ok']} in {result['seconds']}s")

def main():
    log("pua-daemon up")
    while True:
        HEARTBEAT.write_text(str(time.time()))
        for path in sorted(TASKS.glob("*.json")):
            run_task(path)
        time.sleep(2)

if __name__ == "__main__":
    main()
