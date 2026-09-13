# Messaging from phone nodes

A phone node can act on messaging apps the same way a person does — by driving
the app's UI through the control channel. Whether that works out of the box
depends on the app.

## Telegram — works via UI automation

Telegram (and most third-party clients) expose a good accessibility tree and let
an agent read chats, open conversations, type and send, with no special setup.
Flow:

```sh
control/pua-control.sh launch org.telegram.messenger
control/pua-control.sh dump                 # read the visible chat list
control/pua-control.sh click <x> <y>        # open a conversation
control/pua-control.sh click <x> <y>        # focus the input
control/pua-control.sh set-focused-text "hello from an agent"
control/pua-control.sh click <send-x> <send-y>
```

`set-focused-text` writes straight to the input node — no soft keyboard, so it
is immune to IME layout and the `input text` space trap.

The same pattern applies to Signal, Slack, Discord and similar apps that expose
their views to accessibility.

## WhatsApp — needs a registered number + waagent

WhatsApp's accessibility tree is deliberately sparse and it aggressively detects
non-human input. Reliable automation needs a real, registered WhatsApp account on
the node and a dedicated bridge. Plan:

- **Registered number.** Each WhatsApp node needs its own phone number with an
  active registration. Pairing by code links one device to an existing account.
- **waagent.** A small Go bridge that talks to WhatsApp's multi-device protocol
  directly (no UI). This is the path used for headless send/receive; the UI
  automation path is a fallback for actions the bridge does not cover.
- **Trade-off.** UI automation is fragile and against WhatsApp's terms; the
  bridge is more robust but must be treated as an unofficial client.

For now: use Telegram (and similar) via UI automation; treat WhatsApp as a
separate, opt-in module that requires a registered number and the waagent bridge.
