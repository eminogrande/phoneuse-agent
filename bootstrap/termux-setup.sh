#!/data/data/com.termux/files/usr/bin/sh
# phoneuse-agent — on-phone Termux bootstrap.
# Executed INSIDE Termux by bootstrap/node.sh. Idempotent: safe to re-run.
#
# Verified on: Galaxy S21 (Exynos 2100, 8 GB), Android 15, no root.

export PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
export HOME="${HOME:-/data/data/com.termux/files/home}"
export PATH="$HOME/bin:$PREFIX/bin:$PREFIX/bin/applets:/system/bin:/usr/bin:/bin"

STAGE=/sdcard/phoneuse
mkdir -p "$STAGE" 2>/dev/null

# Capture everything (set -x included) to a log the host can read back.
exec > "$STAGE/setup.log" 2>&1
set -x

# Keep the CPU awake through the (slow) package install.
termux-wake-lock 2>/dev/null || true

# Non-interactive dpkg: keep existing config files instead of prompting Y/N on
# every upgrade (the "conffile" trap — unattended runs would otherwise hang).
CONFOLD="-o Dpkg::Options::=--force-confold"
export DEBIAN_FRONTEND=noninteractive

pkg update -y $CONFOLD
pkg upgrade -y $CONFOLD
pkg install -y openssh python nodejs-lts termux-api termux-services termux-tools jq git

mkdir -p "$HOME/.termux/boot" "$HOME/.ssh"

# Allow external apps (adb / other apps) to run commands in Termux.
printf 'allow-external-apps=true\n' > "$HOME/.termux/termux.properties"

# Termux:Boot script — runs on every boot: hold a wake lock, start sshd + crond.
cat > "$HOME/.termux/boot/00-start" <<'EOF'
#!/data/data/com.termux/files/usr/bin/sh
termux-wake-lock
sshd
crond
EOF
chmod +x "$HOME/.termux/boot/00-start"

# SSH: key-only. The public key was pushed to $STAGE/authorized_keys by node.sh.
if [ -f "$STAGE/authorized_keys" ]; then
  cat "$STAGE/authorized_keys" >> "$HOME/.ssh/authorized_keys"
  sort -u -o "$HOME/.ssh/authorized_keys" "$HOME/.ssh/authorized_keys"
fi
chmod 700 "$HOME/.ssh"
chmod 600 "$HOME/.ssh/authorized_keys" 2>/dev/null || true

cat > "$PREFIX/etc/ssh/sshd_config" <<'EOF'
Port 8022
PasswordAuthentication no
PubkeyAuthentication yes
PermitRootLogin no
UseDNS no
EOF

# Start the daemon now; the boot script restarts it after every reboot.
sshd
crond 2>/dev/null || true

echo BOOTSTRAP_DONE > "$STAGE/termux_bootstrap.status"
ip addr show wlan0 2>/dev/null | grep 'inet ' > "$STAGE/termux_ip.txt" || true
