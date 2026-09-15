#!/usr/bin/env python3
"""pua-bot — conversational phone-use agent, living on the phone.

You talk to the phone, the phone acts and talks back.

Ingress channels:
  1. Messaging apps: bot watches notifications (WhatsApp/Telegram) via control
     channel. Message from an allowed chat -> becomes a task -> agent executes
     and replies in the same chat.
  2. HTTP: POST :8790/task {"task": "..."} -> runs agent, result in ~/.pua/results
     (A2A-ready entrypoint for the farm/controller.)
  3. File queue: ~/.pua/tasks/*.json (daemon v1 compat).

Brain: OpenAI-compatible API (env, see .pua.env). Runtime: 100% on-device.
"""
import json, os, pathlib, subprocess, sys, threading, time, traceback
from http.server import BaseHTTPRequestHandler, HTTPServer

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
LOGF = PUA / "bot.log"
AGENT = HOME / "pua_agent.py"
PKG = os.environ.get("PUA_PKG", "com.phoneuse.control")
RX = f"{PKG}/.CommandReceiver"

# chats the bot listens to (title match, case-insensitive substring)
ADMIN_CHATS = [c.strip().lower() for c in os.environ.get("PUA_ADMIN_CHATS", "emino (US)").split(",")]
WATCH_PACKAGES = ["com.whatsapp", "org.telegram.messenger.web", "org.telegram.messenger"]
POLL_S = 5

for d in (TASKS, RESULTS):
    d.mkdir(parents=True, exist_ok=True)

def log(msg: str):
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    with open(LOGF, "a") as f:
        f.write(line + "\n")

def broadcast(action: str, *extra: str, timeout=20) -> str:
    cmd = ["/system/bin/am", "broadcast", "--user", "0", "-W", "-n", RX, "-a", f"{PKG}.{action}", *extra]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except Exception as e:
        return f"ERR {e}"
    import re
    m = re.search(r'data="(.*)"\s*$', out, re.S)
    return (m.group(1) if m else out).replace("\\n", "\n")

def notifications(package: str) -> list:
    raw = broadcast("NOTIFICATIONS", "--es", "package", package)
    # listener output: postTime\tpackage\ttitle\ttext\tkey
    items = []
    for ln in raw.splitlines():
        parts = ln.split("\t")
        if len(parts) >= 5:
            items.append({"ts": parts[0], "pkg": parts[1], "title": parts[2],
                          "text": parts[3], "key": parts[4]})
    return items

def run_agent(task: str, steps: int = 18, timeout: int = 600) -> dict:
    t0 = time.time()
    try:
        r = subprocess.run([sys.executable, str(AGENT), task, "--steps", str(steps)],
                           capture_output=True, text=True, timeout=timeout)
        out = r.stdout + r.stderr
        answer = ""
        for line in out.splitlines():
            if line.startswith("DONE:"):
                answer = line[5:].strip()
        return {"ok": bool(answer), "answer": answer, "seconds": round(time.time() - t0, 1), "log": out[-3000:]}
    except Exception as e:
        return {"ok": False, "answer": "", "seconds": round(time.time() - t0, 1),
                "log": f"bot error: {e}\n{traceback.format_exc()[-1200:]}"}

# ---------- messaging ingress ----------
def chat_task(chat_title: str, text: str) -> str:
    return (f"You are the phone's bot. The admin sent you this message in the chat '{chat_title}':\n"
            f"\"{text}\"\n"
            f"Do what they ask using the phone (open apps if needed). "
            f"If it is a question about the phone, find the answer on the phone. "
            f"Then REPLY to them in that same chat (type the reply into the message field and send it). "
            f"Finally report what you did and what you replied.")

def notification_loop():
    seen = set()
    state_f = PUA / "bot-seen.json"
    if state_f.exists():
        try:
            seen = set(json.loads(state_f.read_text()))
        except Exception:
            seen = set()
    log(f"notification loop up, watching {WATCH_PACKAGES} for {ADMIN_CHATS}")
    while True:
        try:
            # path 1: status bar notifications (app in background)
            for pkg in WATCH_PACKAGES:
                for item in notifications(pkg):
                    key = item["key"][:160]
                    if key in seen:
                        continue
                    title, text = item["title"], item["text"]
                    if not text:
                        continue
                    if not any(c in title.lower() for c in ADMIN_CHATS):
                        continue
                    key = "msg:" + title.lower() + ":" + text[:120]
                    if key in seen:
                        continue
                    seen.add(key)
                    log(f"incoming from {title}: {text[:80]}")
                    t = chat_task(title, text)
                    res = run_agent(t, steps=25)
                    (RESULTS / f"chat-{int(time.time())}.json").write_text(json.dumps(
                        {"chat": title, "msg": text, **res}, indent=2))
                    log(f"chat task done ok={res['ok']} {res['seconds']}s")
            # path 2: active-chat polling (WhatsApp in foreground, admin chat open)
            tree = broadcast("DUMP")
            if "com.whatsapp:id/conversation_contact_name" in tree or "com.whatsapp:id/message_text" in tree:
                admin_open = None
                for c in ADMIN_CHATS:
                    if c in tree.lower()[:3000]:
                        admin_open = c
                        break
                if admin_open:
                    import re as _re
                    msgs = _re.findall(r'id=com\.whatsapp:id/message_text text=([^=]+) desc=', tree)
                    if msgs:
                        last = msgs[-1].strip()
                        key = "msg:" + admin_open + ":" + last[:120]
                        if last and key not in seen:
                            seen.add(key)
                            log(f"incoming (fg) from {admin_open}: {last[:80]}")
                            res = run_agent(chat_task(admin_open, last), steps=25)
                            (RESULTS / f"chat-{int(time.time())}.json").write_text(json.dumps(
                                {"chat": admin_open, "msg": last, **res}, indent=2))
                            log(f"chat task done ok={res['ok']} {res['seconds']}s")
                            # anti-echo: whatever is the newest message now (likely our own
                            # reply) must not be treated as a new incoming message
                            tree2 = broadcast("DUMP")
                            msgs2 = _re.findall(r'id=com\.whatsapp:id/message_text text=([^=]+) desc=', tree2)
                            if msgs2:
                                seen.add("msg:" + admin_open + ":" + msgs2[-1].strip()[:120])
            if len(seen) > 5000:
                seen = set(list(seen)[-2000:])
            state_f.write_text(json.dumps(sorted(seen)))
        except Exception as e:
            log(f"notify loop error: {e}")
        time.sleep(POLL_S)

# ---------- file queue (v1) ----------
def queue_loop():
    while True:
        for path in sorted(TASKS.glob("*.json")):
            try:
                spec = json.loads(path.read_text())
            except Exception:
                path.unlink(missing_ok=True)
                continue
            tid = spec.get("id") or path.stem
            res = run_agent(spec["task"], spec.get("steps", 18), spec.get("timeout", 600))
            (RESULTS / f"{tid}.json").write_text(json.dumps({"id": tid, **res}, indent=2))
            path.unlink(missing_ok=True)
            log(f"queue task {tid} ok={res['ok']}")
        time.sleep(2)

# ---------- HTTP (A2A entry) ----------
class H(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"ok": True, "bot": "pua-bot", "ts": time.time()})
        else:
            self._send(404, {"error": "path"})

    def do_POST(self):
        if self.path != "/task":
            self._send(404, {"error": "path"})
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
            spec = json.loads(self.rfile.read(n) or b"{}")
            task = spec["task"]
        except Exception as e:
            self._send(400, {"error": str(e)})
            return
        tid = spec.get("id") or f"http-{int(time.time())}"
        res = run_agent(task, spec.get("steps", 18), spec.get("timeout", 600))
        (RESULTS / f"{tid}.json").write_text(json.dumps({"id": tid, **res}, indent=2))
        self._send(200, {"id": tid, **{k: v for k, v in res.items() if k != "log"}})

    def log_message(self, format, *args):
        pass

def main():
    log("pua-bot up")
    threading.Thread(target=queue_loop, daemon=True).start()
    threading.Thread(target=notification_loop, daemon=True).start()
    HTTPServer(("0.0.0.0", 8790), H).serve_forever()

if __name__ == "__main__":
    main()
