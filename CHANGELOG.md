# Changelog

Newest first. Every bullet names the commit SHA on `main`.

## 2026-10-14 — [RELEASE] v0.1.0 — hermes-agent for emino

First tagged release. State of `main` at HEAD `3e73c548`.

- Farm control plane (`farm/server.py`, FastAPI :8787): node health, live screen, task runner via mobilerun, dashboard.
- Fleet manifest renderer and adb-over-TCP watchdog for many phones.
- One-command phone bootstrap (`bootstrap/node.sh`): Termux, key-only sshd :8022, hardening, control APK.
- Control app `com.phoneuse.control` 0.1.0: accessibility + notification broadcast API (dump, click, swipe, long press, text, launch, URL, notifications).
- On-device agent stack in Termux: `pua_agent.py` plan-act loop, `pua_daemon.py` file queue, `pua_bot.py` WhatsApp/Telegram chat bot with HTTP :8790.
- Docs only in this release: README rewrite (Mermaid architecture and user flow, endpoint and env tables), CHANGELOG, PROMPTLOG. No code changed.

## 2026-09-16

- `3e73c548` bot: ignores its own replies, ending the echo loop; stays alive after WhatsApp is killed.

## 2026-09-15

- `90124a5f` agent: persistent memory (`remember` action, `~/.pua/memory.md` injected into the prompt), `read_url` web tool, current app passed as context.
- `be970446` fix: dedup across notification and foreground paths (msg:chat:text), 25-step chat budget, `wait` action, prompt rules for biometrics and app installs.
- `090ee128` bot: polls the open chat when the app is in the foreground (no notifications there), plus anti-echo.
- `8ee0a95d` bot: new conversational `pua_bot.py`: notification ingress for WhatsApp/Telegram, auto-reply in chat, HTTP :8790 task endpoint, file queue.

## 2026-09-13

- `6787784d` control: app launch works again: `QUERY_ALL_PACKAGES` against AppsFilter blocking, overlay permission, launcher fallback.
- `68666d63` chore: gradle build output no longer tracked.
- `f5c1080d` agent: persistent on-device daemon; control APK gains swipe and long press.
- `09c33f31` agent: first on-device PUA loop in Termux using the accessibility broadcast channel and an OpenAI-compatible brain.
- `064bcaeb` initial commit: bootstrap, control app, farm control plane, docs.
