#!/usr/bin/env bash
# Signs the guest Apple Account in via System Settings and activates iMessage.
# Proven flow: search-driven navigation, Tab-to-field with focus verification,
# vault passwords via `corral macos apple-field`, one fresh operator 2FA code.
#
#   KVM=messages APPLE_EMAIL=trogdor3000@gmail.com ./messages-signin.sh
#
# Requires BW_SESSION exported. If iMessage activation fails on Contact Key
# Verification, toggle CKV off on an existing device and rerun.
set -u
# Per-run scratch dir: fixed /tmp names let another local user pre-link them,
# and screenshots of credential prompts must not outlive the run.
SHOTS="$(mktemp -d)"
trap 'rm -rf "$SHOTS"' EXIT
KVM="${KVM:-messages}"
KCTX="${KCTX:-karnataka-k3s}"
KNS="${KNS:-corral-vms}"
APPLE_EMAIL="${APPLE_EMAIL:-trogdor3000@gmail.com}"
APPLE_ITEM="${APPLE_ITEM:-James Apple ID}"
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

# Full keyboard navigation so Tab reaches every control.
ssh_guest '/usr/bin/sudo -u beeper /usr/bin/defaults write -g AppleKeyboardUIMode -int 3'
ssh_guest '/usr/bin/sudo -u beeper /usr/bin/open -a "System Settings"'
"$DRIVER" wait "Sign in with your Apple Account" 120 || {
  echo "settings not ready" >&2; exit 1; }

# Search field keeps history: focus it, reset with ESC, then type.
"$DRIVER" press 420 129 1 0.3
"$DRIVER" key ESC
sleep 3
"$DRIVER" press 420 129 1 0.3
"$DRIVER" type Apple Account
"$DRIVER" wait "Sign in" 60 || { echo "no sign-in row" >&2; exit 1; }
"$DRIVER" click "Sign in" 1.0
"$DRIVER" wait "Email or Phone Number" 60 || { echo "no sheet" >&2; exit 1; }

# Focus the email field (Tab from search), type, OCR-readback, submit.
"$DRIVER" key TAB
sleep 2
"$DRIVER" type "$APPLE_EMAIL"
sleep 3
"$DRIVER" ocr "$SHOTS/im-email.png" | grep -qi "$(printf '%s' "$APPLE_EMAIL" | cut -d@ -f1)" \
  || { echo "email not echoed; refocus and retry" >&2; exit 1; }
"$DRIVER" key RET
"$DRIVER" wait "Password" 120 || { echo "no password pane" >&2; exit 1; }

# Tab to the password field (caret/Passwords popup = focused), vault-type.
"$DRIVER" key TAB
sleep 3
corral macos apple-field "$KVM" --context "$KCTX" -n "$KNS" \
  --item "$APPLE_ITEM" --field password \
  --confirm-focused-field --confirm-us-layout --enter || exit 1

if "$DRIVER" wait "Verification Code" 180; then
  printf 'Paste ONE fresh 6-digit code: '
  IFS= read -r CODE
  CODE="$(printf '%s' "$CODE" | tr -cd '0-9')"
  [ "${#CODE}" -eq 6 ] || { echo "not a 6-digit code" >&2; exit 1; }
  "$DRIVER" type "$CODE"
  "$DRIVER" key RET
  unset CODE
  sleep 10
fi

# Mac-password keychain unlock if prompted.
if "$DRIVER" wait "Enter Mac Password" 60; then
  corral macos apple-field "$KVM" --context "$KCTX" -n "$KNS" \
    --item "$MAC_ITEM" --field password \
    --confirm-focused-field --confirm-us-layout --enter || exit 1
  sleep 10
fi

N=$(ssh_guest '/usr/bin/sudo -u beeper /usr/bin/defaults read MobileMeAccounts 2>/dev/null | /usr/bin/grep -c AccountID' | tr -cd '0-9')
if [ "${N:-0}" -ge 1 ]; then
  echo "SIGNED IN: MobileMeAccounts has account(s)"
else
  echo "NOT SIGNED IN: MobileMeAccounts empty" >&2
  exit 1
fi
