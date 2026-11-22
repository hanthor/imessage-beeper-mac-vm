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

- `corral` CLI with the macos plugin; a macOS VM it manages. corral also
  creates the per-VM SSH key the scripts use, at
  `~/.cache/corral/macos/sequoia/<KVM>-ssh/id_ed25519`.
- `virtctl` (KubeVirt) and `ssh` on this machine: every script reaches the
  guest with `ssh` through `virtctl port-forward`. The scripts do not check
  for them, so a missing one surfaces as an SSH failure partway through.
- `tesseract-ocr` + `python3-pil` on this machine (the console driver).
- A console driver. `messages-signin.sh` and `fda-grant.sh` run the driver
  named by `CORRAL_CONSOLE`, which defaults to corral's copy at
  `$HOME/dev/corral/scripts/macos-console/driver.py`. Without a corral
  checkout there, point `CORRAL_CONSOLE` at this repo's
  `scripts/console/driver.py`.
- Bitwarden CLI (`bw`) with an unlocked session for the password steps
  (`messages-signin.sh` and `fda-grant.sh`). Export its session key as
  `BW_SESSION`; the scripts exit if it is unset.
- 2FA codes come from the operator's Apple device at the prompt.

### Settings

Every script reads these environment variables. The defaults match the
original operator's setup, so override the ones marked *yours* before you
run anything.

| Variable | Default | Used by | Meaning |
| --- | --- | --- | --- |
| `KVM` | `messages` | all | Name of the macOS VM (and VMI) corral manages |
| `KCTX` | `karnataka-k3s` | all | kubectl context for the cluster running the VM |
| `KNS` | `corral-vms` | all | Namespace of the VM |
| `CORRAL_CONSOLE` | `$HOME/dev/corral/scripts/macos-console/driver.py` | `messages-signin.sh`, `fda-grant.sh` | Console driver to run |
| `APPLE_EMAIL` | an operator-specific address — *yours* | `messages-signin.sh` | Apple Account to sign in |
| `APPLE_ITEM` | an operator-specific vault item — *yours* | `messages-signin.sh` | Bitwarden item holding that account's password |
| `MAC_ITEM` | `macos-beeper VM` | `messages-signin.sh`, `fda-grant.sh` | Bitwarden item holding the guest Mac account password (entered at the "Enter Mac Password" and admin auth prompts) |

For example:

```bash
export BW_SESSION=...   # from `bw unlock`
KVM=messages KCTX=<your-context> KNS=<your-namespace> \
  APPLE_EMAIL=<you@example.com> APPLE_ITEM=<vault item> \
  scripts/beeper/messages-signin.sh
```

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
