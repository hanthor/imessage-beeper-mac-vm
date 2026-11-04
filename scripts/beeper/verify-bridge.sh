#!/usr/bin/env bash
# Kickstarts the bridge LaunchAgent and polls its log until it connects.
# Success looks like: "Logged in as bridge bot" then "Connected to iMessage".
# Known non-fatal gate: "you're not logged into iMessage" while the message
# database is empty — send or receive one iMessage on the VM, the agent's
# retry loop connects on its own afterwards.
#
#   KVM=messages ./verify-bridge.sh
set -u
KVM="${KVM:-messages}"
KCTX="${KCTX:-karnataka-k3s}"
KNS="${KNS:-corral-vms}"
export KVM KCTX KNS

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

ssh_guest '/bin/launchctl kickstart -k gui/501/io.github.tuna-os.corral.imessage'
echo "kickstarted; polling log for 3 minutes..."
for i in $(seq 1 18); do
  sleep 10
  OUT="$(ssh_guest '/usr/bin/sudo -u beeper /usr/bin/tail -n 8 "$HOME/Library/Application Support/corral-macos/logs/stdout.log" 2>&1' | tr -d '\000' | grep -a -E 'Connected|FTL|not logged into iMessage|operation not permitted' | tail -n 3)"
  echo "--- poll $i:"
  echo "$OUT" | head -n 3
  if echo "$OUT" | grep -qa "Connected"; then
    echo "BRIDGE CONNECTED"
    exit 0
  fi
done
echo "NOT CONNECTED within window; inspect the log tail above" >&2
exit 1
