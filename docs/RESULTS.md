# Proven results (2026-11-04, KubeVirt Sequoia guest `messages`)

Automated driver: `scripts/console/driver.py` (screenshot + tesseract OCR
+ VNC input with verify loops). All GUI steps below were executed through
it, not by hand.

## Done and verified

- **Fresh VM, unique identity.** Provisioned with a newly generated
  OpenCore identity after diagnosing a duplicate-serial device-trust
  failure (`An unknown error occurred`, `MobileMeAccounts` reverting).
  Lesson: never reuse a serial across VMs.
- **System Apple Account sign-in, persisted.** Email typed with OCR
  readback, password via `corral macos apple-field`, one fresh operator
  2FA code, Mac-password keychain unlock. `MobileMeAccounts` shows the
  account afterwards — no revert. Apple mailed an iMac-27" sign-in notice
  matching the VM (iMac19,1), expected.
- **iMessage activation.** First attempt blocked by Contact Key
  Verification (`could not be activated ... contact key verification is
  turned on`). Apple has no per-device approve switch, so CKV was toggled
  off on the iPhone, activation retried cleanly, iMessage Settings shows
  the account with both addresses checked.
- **Full Disk Access for the bridge.** tccd logs proved the access check
  runs against the *responsible* binary (`bbctl`), not the leaf —
  toggling only `mautrix-imessage` kept failing with `operation not
  permitted`. Both entries are now ON:
  `.../corral-macos/bin/bbctl` and
  `.../bbctl/data/binaries/mautrix-imessage`.
  Key techniques: select-row + Space flips a switch (VNC toggle presses
  don't), Go-to-Folder with the *full binary path* + Return confirms the
  file picker. Ad-hoc `codesign -s -` applied to the unsigned bridge
  binary for a stable identity.
- **Bridge past the DB gate.** Log moved from
  `failed to open message database ... operation not permitted` to
  `Logged in as bridge bot` + `Error in iMessage connection: you're not
  logged into iMessage`.

## Pending

- **First message row.** The bridge reports "not logged in" while the
  message database is empty (its check reads the newest row; fresh
  accounts have none). Fix: send or receive one iMessage on the VM, then
  the agent's retry loop connects on its own. A scripted send from the VM
  did not stick (recipient unresolved while iCloud sync is paused), so
  the reliable trigger is one iMessage sent from the operator's iPhone to
  the account address — which also tests inbound delivery.
- **Bidirectional test.** After `Connected`: reply from the VM (outbound)
  and confirm both directions in Beeper.
- **Re-enable CKV** on the iPhone once the bridge is connected.

## Automation lessons encoded in the driver

- Never `launchctl asuser` from SSH — it fails silently (rc=1). Use
  `sudo -u <user> open -a` / `osacript` directly.
- Verify focus before typing (Tab-to-field + caret/ring/OCR readback);
  never type blind. Search fields keep history — click the field end,
  BKSP-clear, or ESC-reset before typing.
- Small switches need select-row + Space; file pickers confirm with
  Return, not a button press; Go-to-Folder (`/`) with a full path beats
  clicking through columns.
- Research verdict: no supported CLI/MDM-free FDA bypass exists
  (tccutil only resets; direct TCC.db edits need SIP off; MDM PPPC is the
  only silent path and needs enrollment). GUI grants are the sanctioned
  route — this repo automates exactly that.
