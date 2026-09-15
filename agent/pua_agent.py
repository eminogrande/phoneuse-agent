#!/usr/bin/env python3
"""pua-agent — on-device phone-use agent. Runs IN Termux on the phone itself.

Loop: dump a11y tree via control-channel broadcast -> LLM (OpenAI-compatible) -> action broadcast.
No adb, no host PC in the loop. stdlib only.

Env: PUA_BASE_URL, PUA_API_KEY, PUA_MODEL, PUA_PKG (control app package, default com.phoneuse.control)
Usage: python3 pua_agent.py "task description" [--steps 25]
"""
import json, os, re, subprocess, sys, time, urllib.request

PKG = os.environ.get("PUA_PKG", "com.phoneuse.control")
RX = f"{PKG}/.CommandReceiver"
STEPS_BUDGET = 25

def broadcast(action: str, *extra: str) -> str:
    cmd = ["/system/bin/am", "broadcast", "--user", "0", "-W", "-n", RX, "-a", f"{PKG}.{action}", *extra]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout
    except Exception as e:
        return f"ERR {e}"
    m = re.search(r'data="(.*)"\s*$', out, re.S)
    return (m.group(1) if m else out).replace("\\n", "\n")

def dump_tree() -> str:
    raw = broadcast("DUMP")
    lines = []
    for ln in raw.splitlines():
        m = re.match(r"\s*(\S+) id=(\S+) text=(\S(?:.*?))? desc=(\S*) bounds=(\[[0-9,]+\]\[[0-9,]+\])", ln)
        if not m:
            continue
        cls, rid, txt, desc, bounds = m.groups()
        if txt in ("null", ""):
            txt = ""
        keep = txt or (desc and desc != "null") or (rid and rid != "null")
        if keep:
            rid = rid.replace("com.whatsapp", "wa").replace("com.whatsapp.w4b", "w4b") if rid else "null"
            lines.append(f'{cls.split(".")[-1]}|{rid}|{txt or desc}|{bounds}')
    return "\n".join(lines[:160])

def act(a: dict) -> str:
    ac = a.get("action")
    if ac == "click":
        return broadcast("CLICK", "--ei", "x", str(a["x"]), "--ei", "y", str(a["y"]))[:200]
    if ac == "swipe":
        return broadcast("SWIPE", "--ei", "x1", str(a["x1"]), "--ei", "y1", str(a["y1"]),
                         "--ei", "x2", str(a["x2"]), "--ei", "y2", str(a["y2"]),
                         "--ei", "duration", str(a.get("duration", 350)))[:200]
    if ac == "long_press":
        return broadcast("LONG_PRESS", "--ei", "x", str(a["x"]), "--ei", "y", str(a["y"]),
                         "--ei", "duration", str(a.get("duration", 800)))[:200]
    if ac == "click_id":
        return broadcast("CLICK_ID", "--es", "viewId", a["id"])[:200]
    if ac == "set_text":
        return broadcast("SET_TEXT", "--es", "viewId", a["id"], "--es", "text", a["text"])[:200]
    if ac == "type":
        return broadcast("SET_FOCUSED_TEXT", "--es", "text", a["text"])[:200]
    if ac == "launch":
        return broadcast("LAUNCH", "--es", "package", a["package"])[:200]
    if ac == "open_url":
        return broadcast("OPEN_URL", "--es", "url", a["url"])[:200]
    if ac in ("back", "home", "recents"):
        return broadcast(ac.upper())[:200]
    if ac == "wait":
        time.sleep(min(int(a.get("seconds", 3)), 30))
        return f"waited {a.get('seconds', 3)}s"
    return "unknown action"

SYSTEM = """You are a phone-use agent running on the phone. You receive the accessibility tree (class|resourceId|textOrDesc|bounds=[x1,y1][x2,y2]) and reply with ONE JSON action.
Actions:
{"action":"click","x":540,"y":600}  — tap center of an element's bounds
{"action":"swipe","x1":540,"y1":1800,"x2":540,"y2":800,"duration":350}  — scroll lists
{"action":"long_press","x":540,"y":600,"duration":800}
{"action":"click_id","id":"pkg:id/name"}
{"action":"set_text","id":"pkg:id/name","text":"..."}
{"action":"type","text":"..."}  — into focused field
{"action":"launch","package":"com.whatsapp"}
{"action":"open_url","url":"https://..."}
{"action":"back"} {"action":"home"} {"action":"recents"}
{"action":"done","answer":"final answer"}
Rules: prefer click_id/set_text with full resourceIds over coordinates. Never repeat the same failing action twice. Reply ONLY with the JSON.
If a task needs biometrics (passkey/fingerprint/face unlock), say so immediately via done — a human finger is required, you cannot do it.
For app installs use open_url market://details?id=<package>, then click Install, then {"action":"wait","seconds":15} until installed.
Reply in the user's language, keep chat replies short."""

def think(task: str, tree: str, history: list) -> dict:
    url = os.environ["PUA_BASE_URL"].rstrip("/") + "/chat/completions"
    payload = {
        "model": os.environ["PUA_MODEL"],
        "temperature": 1,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"TASK: {task}\n\nHISTORY:\n" + "\n".join(history[-12:]) + f"\n\nCURRENT UI TREE:\n{tree}"},
        ],
    }
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + os.environ["PUA_API_KEY"], "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        content = json.load(r)["choices"][0]["message"]["content"]
    m = re.search(r"\{[^{}]*\"action\"[^{}]*\}", content, re.S)
    if not m:
        return {"action": "back", "_raw": content[:100]}
    return json.loads(m.group(0))

def main():
    task = sys.argv[1]
    budget = STEPS_BUDGET
    if "--steps" in sys.argv:
        budget = int(sys.argv[sys.argv.index("--steps") + 1])
    history = []
    for step in range(1, budget + 1):
        tree = dump_tree()
        try:
            a = think(task, tree, history)
        except Exception as e:
            print(f"[{step}] brain error: {e}", flush=True)
            time.sleep(4)
            continue
        print(f"[{step}] {json.dumps(a)}", flush=True)
        if a.get("action") == "done":
            print("DONE:", a.get("answer", ""), flush=True)
            return 0
        res = act(a)
        history.append(f"step{step}: {json.dumps(a)} -> {res[:80]}")
        time.sleep(1.2)
    print("STEPS EXHAUSTED", flush=True)
    return 1

if __name__ == "__main__":
    sys.exit(main())
