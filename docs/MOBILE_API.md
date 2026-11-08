# Mobile companion API

The mobile API lets a phone **watch** Study Terminal and **apply the brakes**. It can't place orders, change modes or rules,
start automation, or clear an emergency stop. Everything it shows is simulated trading.

## What it does

| Request | What it does |
|---|---|
| `GET /api/mobile/status` | Automation mode and status, per-contract decisions, simulated balance/equity, day P&L, room to the max loss and daily limits, positions, recent decisions, recent log |
| `GET /api/mobile/alerts?limit=30` | Recent alerts |
| `POST /api/mobile/automation/pause` | Pause monitoring |
| `POST /api/mobile/automation/resume` | Resume after a pause (refused during an emergency stop) |
| `POST /api/mobile/automation/emergency-stop` | Cancel all simulated working orders, flatten simulated positions, stop automation |

Every request needs `Authorization: Bearer <token>`.

## Turning it on

1. Automation Center > **Mobile companion** > **Turn on**.
2. Copy the token. It's shown **once**; only its SHA-256 hash is saved. **New token** replaces it (the old one stops working);
   **Turn off** deletes it.
3. Ten wrong tokens from one address within a minute lock that address out for a minute.

## Reaching it from a phone (securely)

Study Terminal listens on `127.0.0.1` only and never opens a port to your network or the internet itself. Pick one:

- **SSH tunnel** (encrypted): from a phone SSH client that supports port forwarding, forward a local port to `127.0.0.1:8765` on your
  computer, then call `http://127.0.0.1:<local port>/api/mobile/status` on the phone. Needs an SSH server on the computer.
- **Private overlay network** (Tailscale/WireGuard, encrypted): run e.g. `tailscale serve` to proxy your tailnet name to
  `127.0.0.1:8765`, and set `STUDY_MOBILE_ALLOWED_HOSTS=<your-machine>.<tailnet>.ts.net` in `.env`. That host name is accepted
  **only** for `/api/mobile/*`; the rest of the API still answers to localhost only.

Don't use router port forwarding or bind the app to `0.0.0.0`: that would put it on the public internet without encryption.

## What was tested

Automated tests (`backend/tests/test_p10_mobile.py`) cover: off by default, missing/wrong/revoked tokens, hash-only storage, the token
not appearing in `/api/settings` and not being settable there, the brake-only controls, refusal of every other API route from a
phone even with a valid token, the extra host being accepted only for mobile paths, and the bad-token lockout.

**Not tested:** a real phone over an SSH tunnel or Tailscale. Those setups depend on software outside Study Terminal, and none
was available in this build. There is no phone app yet; the API is ready for one (or for a simple HTTP shortcut app).

## Why no orders from the phone

Topstep's TopstepX API rules prohibit trading from VPS, VPNs or remote servers, and every order in Study Terminal is simulated anyway.
The phone is a monitor with a brake, nothing more.
