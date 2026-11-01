#!/usr/bin/env bash
# Installs (or updates) Shrinkarr on Debian 12/13 or Ubuntu 22.04/24.04: in an LXC container, a VM or bare metal.
#
#   curl -fsSL https://raw.githubusercontent.com/rvanderend/shrinkarr/main/install/install.sh | bash
#
# Options (environment variables):
#   SHRINKARR_UID / SHRINKARR_GID   user/group id the service runs as. Use the owner of your media files,
#                                   so Shrinkarr can replace them. Default 1000/1000.
#   SHRINKARR_PORT                  web port (default 8080)
#   SHRINKARR_WORK                  work folder for conversions (default /work; needs room for the biggest file)
#   SHRINKARR_VERSION               "latest" (default: the newest release), a release such as "v1.0.1",
#                                   or a branch such as "main" (the newest, untested state)
#   SHRINKARR_REPO                  git source (default github.com/rvanderend/shrinkarr)
#   SHRINKARR_TARBALL               install from this local .tar.gz instead of git (for testing)
#
# Update later with: shrinkarr-update [version]
set -euo pipefail

REPO=${SHRINKARR_REPO:-https://github.com/rvanderend/shrinkarr.git}
SK_VERSION=${SHRINKARR_VERSION:-${SHRINKARR_BRANCH:-latest}}
GH_API=https://api.github.com/repos/rvanderend/shrinkarr
UID_=${SHRINKARR_UID:-1000}
GID_=${SHRINKARR_GID:-1000}
PORT=${SHRINKARR_PORT:-8080}
WORK=${SHRINKARR_WORK:-/work}
APP=/opt/shrinkarr
DATA=/var/lib/shrinkarr

c_ok=$'\e[32m'; c_info=$'\e[36m'; c_err=$'\e[31m'; c_off=$'\e[0m'
info() { echo "${c_info}›${c_off} $*"; }
ok() { echo "${c_ok}✓${c_off} $*"; }
die() { echo "${c_err}✗ $*${c_off}" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Run as root."
# An existing install keeps its user and group, unless they are given explicitly.
if id shrinkarr >/dev/null 2>&1; then
  UID_=${SHRINKARR_UID:-$(id -u shrinkarr)}
  GID_=${SHRINKARR_GID:-$(id -g shrinkarr)}
fi
. /etc/os-release
case "$ID" in debian|ubuntu) ;; *) die "Only Debian and Ubuntu are supported (found: $ID)." ;; esac
export DEBIAN_FRONTEND=noninteractive LC_ALL=C.UTF-8 LANG=C.UTF-8
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

info "Installing packages"
apt-get update -qq
apt-get install -y -qq curl gnupg ca-certificates git python3 python3-venv sqlite3 >/dev/null
ok "Packages"

if ! dpkg -s jellyfin-ffmpeg7 >/dev/null 2>&1; then
  info "Installing jellyfin-ffmpeg (ffmpeg with Intel QSV, VAAPI and NVENC)"
  install -d /usr/share/keyrings
  curl -fsSL https://repo.jellyfin.org/jellyfin_team.gpg.key | gpg --dearmor --yes -o /usr/share/keyrings/jellyfin.gpg
  echo "deb [signed-by=/usr/share/keyrings/jellyfin.gpg] https://repo.jellyfin.org/$ID $VERSION_CODENAME main" \
    > /etc/apt/sources.list.d/jellyfin.list
  apt-get update -qq
  apt-get install -y -qq jellyfin-ffmpeg7 >/dev/null
fi
ln -sf /usr/lib/jellyfin-ffmpeg/ffmpeg /usr/local/bin/ffmpeg
ln -sf /usr/lib/jellyfin-ffmpeg/ffprobe /usr/local/bin/ffprobe
ok "ffmpeg $(/usr/lib/jellyfin-ffmpeg/ffmpeg -version 2>/dev/null | awk 'NR==1 {print $3}')"

info "Service user (uid $UID_, gid $GID_)"
if ! getent group "$GID_" >/dev/null; then groupadd -g "$GID_" shrinkarr; fi
GROUP=$(getent group "$GID_" | cut -d: -f1)
if ! id shrinkarr >/dev/null 2>&1; then
  if getent passwd "$UID_" >/dev/null; then
    die "uid $UID_ is already used by $(getent passwd "$UID_" | cut -d: -f1). Pick another SHRINKARR_UID or remove that user."
  fi
  useradd -u "$UID_" -g "$GROUP" -M -d "$APP" -s /usr/sbin/nologin shrinkarr
fi
# Access to the GPU: the groups that own /dev/dri/* and /dev/nvidia*
EXTRA_GROUPS="video"
for dev in /dev/dri/* /dev/nvidia*; do
  [[ -e $dev ]] || continue
  g=$(stat -c %g "$dev")
  [[ $g == 0 ]] && continue
  name=$(getent group "$g" | cut -d: -f1 || true)
  if [[ -z $name ]]; then name="gpu$g"; groupadd -g "$g" "$name"; fi
  [[ " $EXTRA_GROUPS " == *" $name "* ]] || EXTRA_GROUPS="$EXTRA_GROUPS $name"
done
usermod -aG "$(echo "$EXTRA_GROUPS" | tr ' ' ',')" shrinkarr
ok "User shrinkarr ($(id shrinkarr))"

info "Shrinkarr"
if [[ -n ${SHRINKARR_TARBALL:-} ]]; then
  rm -rf "$APP.new" && mkdir -p "$APP.new"
  tar -xzf "$SHRINKARR_TARBALL" -C "$APP.new"
  [[ -d $APP/.venv ]] && mv "$APP/.venv" "$APP.new/.venv"
  rm -rf "$APP" && mv "$APP.new" "$APP"
else
  if [[ $SK_VERSION == latest ]]; then
    SK_VERSION=$(curl -fsSL "$GH_API/releases/latest" 2>/dev/null | grep -oP '"tag_name":\s*"\K[^"]+' || true)
    [[ -n $SK_VERSION ]] || SK_VERSION=main
  fi
  if [[ ! -d $APP/.git ]]; then
    rm -rf /tmp/shrinkarr-venv
    [[ -d $APP/.venv ]] && mv "$APP/.venv" /tmp/shrinkarr-venv
    rm -rf "$APP"
    git clone -q "$REPO" "$APP"
    [[ -d /tmp/shrinkarr-venv ]] && mv /tmp/shrinkarr-venv "$APP/.venv"
  fi
  git -C "$APP" fetch -q --tags --force origin
  # A release is a tag; anything else is a branch on GitHub.
  if git -C "$APP" rev-parse -q --verify "refs/tags/$SK_VERSION" >/dev/null; then REF="refs/tags/$SK_VERSION"
  elif git -C "$APP" rev-parse -q --verify "refs/remotes/origin/$SK_VERSION" >/dev/null; then REF="origin/$SK_VERSION"
  else die "Version $SK_VERSION not found (see https://github.com/rvanderend/shrinkarr/releases)."; fi
  git -C "$APP" reset -q --hard "$REF"
  git -C "$APP" clean -qfd -e .venv
  ok "Version: $SK_VERSION"
fi
[[ -x $APP/.venv/bin/python ]] || python3 -m venv "$APP/.venv"
"$APP/.venv/bin/pip" -q install --upgrade pip >/dev/null
"$APP/.venv/bin/pip" -q install -r "$APP/requirements.txt"
chown -R root:root "$APP"
install -d -o shrinkarr -g "$GROUP" -m 750 "$DATA"
install -d -o shrinkarr -g "$GROUP" -m 770 "$WORK"
chown shrinkarr:"$GROUP" "$WORK"
ok "Installed in $APP ($(grep -oP '^VERSION = "\K[^"]+' "$APP/app/config.py"))"

install -d -m 750 -g "$GROUP" /etc/shrinkarr
if [[ ! -f /etc/shrinkarr/config.env ]]; then
  cat > /etc/shrinkarr/config.env <<EOF
# Everything else is set up in the web interface.
DATA_DIR=$DATA
WORK_DIR=$WORK
PORT=$PORT
EOF
  chgrp "$GROUP" /etc/shrinkarr/config.env && chmod 640 /etc/shrinkarr/config.env
fi
grep -q '^PORT=' /etc/shrinkarr/config.env || echo "PORT=$PORT" >> /etc/shrinkarr/config.env
PORT=$(grep -oP '^PORT=\K.*' /etc/shrinkarr/config.env)

cat > /etc/systemd/system/shrinkarr.service <<EOF
[Unit]
Description=Shrinkarr (shrink media from Sonarr/Radarr to HEVC)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=shrinkarr
Group=$GROUP
SupplementaryGroups=$EXTRA_GROUPS
EnvironmentFile=/etc/shrinkarr/config.env
WorkingDirectory=$APP
ExecStart=$APP/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port \${PORT} --proxy-headers --forwarded-allow-ips=*
Restart=on-failure
RestartSec=5
UMask=0007
Nice=5

[Install]
WantedBy=multi-user.target
EOF

# Also in /usr/bin: `pct exec <ctid> -- shrinkarr-update` runs without /usr/local/bin in its PATH.
cat > /usr/local/bin/shrinkarr-update <<'EOF'
#!/usr/bin/env bash
# Updates Shrinkarr. Usage: shrinkarr-update [version]   (default: the newest release; "main" = newest state)
# A running conversion starts again after the restart.
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
curl -fsSL https://raw.githubusercontent.com/rvanderend/shrinkarr/main/install/install.sh | SHRINKARR_VERSION="${1:-latest}" bash
EOF
chmod 755 /usr/local/bin/shrinkarr-update
ln -sf /usr/local/bin/shrinkarr-update /usr/bin/shrinkarr-update

systemctl daemon-reload
systemctl enable -q shrinkarr
systemctl restart shrinkarr
for _ in $(seq 1 30); do
  curl -fs "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1 && break
  sleep 1
done
curl -fs "http://127.0.0.1:$PORT/api/health" >/dev/null || die "Shrinkarr did not start: journalctl -u shrinkarr"

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
if [[ -e /dev/nvidia0 ]] && ! command -v nvidia-smi >/dev/null; then
  echo "${c_err}!${c_off} An NVIDIA device is present, but no NVIDIA driver libraries. NVENC needs the same driver version as the host."
fi
ok "Shrinkarr is running: ${c_ok}http://${IP:-<this-machine>}:$PORT${c_off}  (open it to finish the setup)"
