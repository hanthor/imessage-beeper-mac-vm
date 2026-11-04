#!/usr/bin/env bash
# Grants Full Disk Access to the bridge binaries in the guest.
# Proven flow: search Privacy row, open Full Disk Access, select-row + Space
# flips a switch (VNC toggle presses don't land), Go-to-Folder with the full
# binary path + Return confirms the picker.
#
#   KVM=messages ./fda-grant.sh
#
# Requires BW_SESSION exported (one admin auth). Both binaries must end ON:
# tccd attributes access to the *responsible* binary (bbctl), not the leaf.
set -u
KVM="${KVM:-messages}"
KCTX="${KCTX:-karnataka-k3s}"
KNS="${KNS:-corral-vms}"
MAC_ITEM="${MAC_ITEM:-macos-beeper VM}"
DRIVER="${CORRAL_CONSOLE:-$HOME/dev/corral/scripts/macos-console/driver.py}"
export KVM KCTX KNS

need() { command -v "$1" >/dev/null || { echo "missing: $1" >&2; exit 1; }; }
need corral; need tesseract; need "$DRIVER"
: "${BW_SESSION:?export BW_SESSION first}"

ssh_guest() {
  KEY=~/.cache/corral/macos/sequoia/"$KVM"-ssh/id_ed25519
  # shellcheck disable=SC2029
  SHELL=/bin/sh ssh -F /dev/null -T -i "$KEY" -o BatchMode=yes \
    -o IdentitiesOnly=yes -o PasswordAuthentication=no \
    -o KbdInteractiveAuthentication=no -o ConnectTimeout=30 \
    -o StrictHostKeyChecking=no -o GlobalKnownHostsFile=/dev/null \
    -o UserKnownHostsFile=/dev/null \
    -o ProxyCommand="virtctl --context $KCTX -n $KNS port-forward --stdio=true vmi/$KVM 22" \
    -l beeper corral-macos "$1"
}

BBCTL_PATH="/Users/beeper/Library/Application Support/corral-macos/bin/bbctl"
MATRIX_PATH="/Users/beeper/Library/Application Support/corral-macos/bbctl/data/binaries/mautrix-imessage"

goto_add() { # $1 = full binary path; assumes FDA list visible, picker closed
  "$DRIVER" press 521 288 1 0.5        # "+" button
  sleep 6
  "$DRIVER" key /                     # Go to Folder sheet
  sleep 4
  "$DRIVER" type "$(printf '%s' "$1" | sed 's|^/||')"
  "$DRIVER" key RET
  sleep 6
  "$DRIVER" key RET                   # confirm selected file (adds it)
  sleep 8
}

auth_once() { # submit vault password to a focused auth prompt
  corral macos apple-field "$KVM" --context "$KCTX" -n "$KNS" \
    --item "$MAC_ITEM" --field password \
    --confirm-focused-field --confirm-us-layout --enter || exit 1
  sleep 8
}

ssh_guest '/usr/bin/sudo -u beeper /usr/bin/defaults write -g AppleKeyboardUIMode -int 3'
ssh_guest '/usr/bin/sudo -u beeper /usr/bin/open -a "System Settings"'
"$DRIVER" wait "Privacy" 120 || { echo "settings not ready" >&2; exit 1; }

"$DRIVER" press 420 129 1 0.3
"$DRIVER" key ESC
sleep 3
"$DRIVER" press 420 129 1 0.3
"$DRIVER" type Full Disk Access
"$DRIVER" wait "Privacy & Security" 60 || { echo "no privacy row" >&2; exit 1; }
"$DRIVER" click "Privacy & Security" 1.0
"$DRIVER" wait "Full Disk Access" 60 || { echo "no FDA pane" >&2; exit 1; }
"$DRIVER" click "Full Disk Access" 1.0
"$DRIVER" wait "Allow the applications" 60 || { echo "no FDA list" >&2; exit 1; }

# Ensure bbctl entry exists, then select-row + Space to flip it ON.
if ! "$DRIVER" ocr /tmp/fda-list.png | grep -qi bbctl; then
  "$DRIVER" shot /tmp/fda-list.png
  goto_add "$BBCTL_PATH"
  auth_once
fi
"$DRIVER" shot /tmp/fda-list.png
BBCTL_ROW="$(python3 -c "
import sys; sys.path.insert(0, '$HOME/dev/corral/scripts/macos-console')
import driver
w = driver.find_text('/tmp/fda-list.png', 'bbctl')
print('%d %d' % w if w else '')
")"
[ -n "$BBCTL_ROW" ] || { echo "bbctl row not found" >&2; exit 1; }
# shellcheck disable=SC2086
"$DRIVER" press $BBCTL_ROW 1 0.5
"$DRIVER" key SPC
sleep 6
if "$DRIVER" shot /tmp/fda-auth.png && \
   "$DRIVER" ocr /tmp/fda-auth.png | grep -qi "Enter your password"; then
  auth_once
fi

# Ensure mautrix entry exists (new entries land ON).
"$DRIVER" shot /tmp/fda-list.png
if ! "$DRIVER" ocr /tmp/fda-list.png | grep -qi mautrix; then
  goto_add "$MATRIX_PATH"
  auth_once
fi

echo "FDA pass done; verify both toggles blue, then run verify-bridge.sh"
