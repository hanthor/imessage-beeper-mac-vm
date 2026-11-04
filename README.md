# iMessage–Beeper bridge on a macOS VM

Automated, repeatable setup of a self-hosted Beeper iMessage bridge
(`bbctl` + `mautrix-imessage`) inside a KubeVirt macOS VM. The VM is
provisioned and managed with [corral](https://github.com/hanthor/corral)'s
`corral-macos` plugin; everything Beeper- or Apple-sign-in-specific lives
here and only *calls* corral tooling.

## Layout

- `scripts/console/driver.py` — generic macOS console driver: screenshot +
  tesseract OCR + VNC input, every action verified (clicks land where OCR
  says the target is, typing is read back, waits poll until text
  appears/vanishes). Knows the hard-won limits: VNC release is unreliable
  (press-hold + verify), META/Command never arrives via VNC, F-keys arrive
  as media keys, Tab/Space need Full Keyboard Access in the guest.
- `scripts/beeper/messages-signin.sh` — signs the guest Apple Account in
  via System Settings (search-driven navigation, Tab-to-field + caret
  verification, vault password via `corral macos apple-field`, operator
  pastes one fresh 2FA code).
- `scripts/beeper/fda-grant.sh` — grants Full Disk Access to the bridge
  binaries (Space-toggles the switch after row select, Go-to-Folder with
  the full binary path + Return to confirm, admin auth via vault).
- `scripts/beeper/verify-bridge.sh` — kickstarts the LaunchAgent and polls
  the bridge log until `Connected` (or reports the blocking error).
- `docs/RESULTS.md` — what actually worked, with evidence, and what is
  still pending.

## Prereqs

- `corral` CLI with the macos plugin; a macOS VM it manages
  (`KVM`, `KCTX=karnataka-k3s`, `KNS=corral-vms`).
- `tesseract-ocr` + `python3-pil` on this machine.
- Bitwarden session for password steps:
  `export BW_SESSION="$(cat /tmp/bw_session_private)"`.
- 2FA codes come from the operator's Apple device at the prompt.

## Order of operations

1. `messages-signin.sh` — system Apple Account + iMessage sign-in.
2. If iMessage activation fails on Contact Key Verification: toggle CKV
   off on an existing device, retry, toggle back on after (Apple's design
   has no per-device approve button).
3. `fda-grant.sh` — FDA for `bbctl` and `mautrix-imessage`.
4. Send or receive one iMessage on the VM (the bridge treats an empty
   message database as "not logged in").
5. `verify-bridge.sh` — confirm `Connected`, then test both directions.

See [docs/RESULTS.md](docs/RESULTS.md) for the proven run.
