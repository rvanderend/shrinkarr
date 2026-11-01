#!/usr/bin/env bash
# Creates a Shrinkarr LXC container on a Proxmox VE host: finds the GPU, passes it through, mounts your
# media folder with the right ownership, and installs Shrinkarr. Run it on the Proxmox host as root:
#
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/rvanderend/shrinkarr/main/install/proxmox.sh)"
#
# Without a terminal (or with SHRINKARR_YES=1) it uses the defaults and these variables, no questions:
#   CTID, CT_HOSTNAME, CT_STORAGE, CT_DISK (GB), CT_CORES, CT_RAM (MB), CT_BRIDGE, CT_IP (dhcp or 10.0.0.5/24),
#   CT_GW, MEDIA_PATHS (host folders with your media, separated by "|"; each is mounted at /data/<folder name>),
#   or MEDIA_PATH + MEDIA_MP (one folder at a path of your choice), WORK_SIZE (GB for the work volume, default 100),
#   GPU (render node, e.g. /dev/dri/renderD128, or "nvidia" or "none")
#   SHRINKARR_TARBALL (local .tar.gz of the app instead of GitHub, for testing)
set -euo pipefail
export LC_ALL=C.UTF-8 LANG=C.UTF-8

RAW=${SHRINKARR_RAW:-https://raw.githubusercontent.com/rvanderend/shrinkarr/main}
c_ok=$'\e[32m'; c_info=$'\e[36m'; c_warn=$'\e[33m'; c_err=$'\e[31m'; c_b=$'\e[1m'; c_off=$'\e[0m'
info() { echo "${c_info}›${c_off} $*"; }
ok() { echo "${c_ok}✓${c_off} $*"; }
warn() { echo "${c_warn}!${c_off} $*"; }
die() { echo "${c_err}✗ $*${c_off}" >&2; exit 1; }

cat <<'EOF'
   _____ __         _       __
  / ___// /_  _____(_)___  / /______ ___________
  \__ \/ __ \/ ___/ / __ \/ //_/ __ `/ ___/ ___/
 ___/ / / / / /  / / / / / ,< / /_/ / /  / /
/____/_/ /_/_/  /_/_/ /_/_/|_|\__,_/_/  /_/

  Shrinkarr LXC for Proxmox VE
EOF

[[ $EUID -eq 0 ]] || die "Run this as root on the Proxmox host."
command -v pct >/dev/null && command -v pveversion >/dev/null || die "This is not a Proxmox VE host."

INTERACTIVE=1
[[ -t 0 && -t 1 && ${SHRINKARR_YES:-0} != 1 ]] && command -v whiptail >/dev/null || INTERACTIVE=0

ask() {  # ask <var> <question> <default>
  local var=$1 q=$2 def=$3 val
  if [[ -n ${!var:-} ]]; then return; fi
  if [[ $INTERACTIVE == 1 ]]; then
    val=$(whiptail --title "Shrinkarr" --inputbox "$q" 10 72 "$def" 3>&1 1>&2 2>&3) || die "Cancelled."
  else
    val=$def
  fi
  printf -v "$var" '%s' "$val"
}
choose() {  # choose <var> <question> <default> <tag> <item> [<tag> <item> ...]
  local var=$1 q=$2 def=$3; shift 3
  if [[ -n ${!var:-} ]]; then return; fi
  if [[ $INTERACTIVE == 1 && $# -gt 2 ]]; then
    local val
    val=$(whiptail --title "Shrinkarr" --default-item "$def" --menu "$q" 18 76 8 "$@" 3>&1 1>&2 2>&3) || die "Cancelled."
    printf -v "$var" '%s' "$val"
  else
    printf -v "$var" '%s' "$def"
  fi
}

# --- container settings ------------------------------------------------------------------
ask CTID "Container ID" "$(pvesh get /cluster/nextid)"
[[ -e /etc/pve/lxc/$CTID.conf || -e /etc/pve/qemu-server/$CTID.conf ]] && die "ID $CTID is already in use."
ask CT_HOSTNAME "Hostname" "shrinkarr"
mapfile -t STORES < <(pvesm status -content rootdir 2>/dev/null | awk 'NR>1 && $3=="active" {print $1}')
[[ ${#STORES[@]} -gt 0 ]] || die "No storage for containers found."
args=(); for s in "${STORES[@]}"; do args+=("$s" "$(pvesm status -storage "$s" | awk 'NR==2 {printf "%.0f GB free", $6/1048576}')"); done
choose CT_STORAGE "Storage for the container and its work volume" "${STORES[0]}" "${args[@]}"
ask CT_DISK "Disk size (GB)" "8"
ask CT_CORES "CPU cores" "4"
ask CT_RAM "Memory (MB)" "2048"
ask CT_BRIDGE "Network bridge" "vmbr0"
ask CT_IP "IP address: dhcp, or static like 192.168.1.50/24" "dhcp"
if [[ $CT_IP != dhcp ]]; then ask CT_GW "Gateway" "$(ip route | awk '/default/ {print $3; exit}')"; fi

# --- media folders --------------------------------------------------------------------------
# Only the folders you pick are mounted (writable). Each one is mounted at /data/<folder name>.
M_HOST=(); M_CT=()
if [[ -n ${MEDIA_PATH:-} ]]; then
  M_HOST=("$MEDIA_PATH"); M_CT=("${MEDIA_MP:-/data/media}")
else
  if [[ -z ${MEDIA_PATHS:-} ]]; then
    ask MEDIA_PARENT "Folder on this Proxmox host that holds your movies and series (the files Sonarr/Radarr use). Mount your NAS share here first. Next you pick the sub-folders." "/mnt/media"
    [[ -d $MEDIA_PARENT ]] || die "$MEDIA_PARENT does not exist on this host."
    MEDIA_PATHS=$MEDIA_PARENT
    if [[ $INTERACTIVE == 1 ]]; then
      items=(".all" "The whole folder $MEDIA_PARENT" "OFF")
      while IFS= read -r -d '' d; do items+=("$(basename "$d")" "" "ON"); done \
        < <(find "$MEDIA_PARENT" -mindepth 1 -maxdepth 1 -type d ! -name '.*' -print0 | sort -z)
      if [[ ${#items[@]} -gt 3 ]]; then
        sel=$(whiptail --title "Shrinkarr" --separate-output --checklist \
          "Which folders hold movies or series? Only these are mounted, and Shrinkarr can write in them." \
          20 76 12 "${items[@]}" 3>&1 1>&2 2>&3) || die "Cancelled."
        if [[ -n $sel ]] && ! grep -qx '.all' <<< "$sel"; then
          MEDIA_PATHS=""
          while IFS= read -r name; do MEDIA_PATHS+="${MEDIA_PATHS:+|}$MEDIA_PARENT/$name"; done <<< "$sel"
        fi
      fi
    fi
  fi
  IFS='|' read -r -a M_HOST <<< "$MEDIA_PATHS"
  for h in "${M_HOST[@]}"; do M_CT+=("/data/$(basename "$h")"); done
fi
for h in "${M_HOST[@]}"; do [[ -d $h ]] || die "$h does not exist on this host."; done
ask WORK_SIZE "Size of the work volume in GB (room for the biggest file you'll convert)" "100"
MEDIA_UID=$(stat -c %u "${M_HOST[0]}"); MEDIA_GID=$(stat -c %g "${M_HOST[0]}")
info "Media folder is owned by uid $MEDIA_UID, gid $MEDIA_GID"
for h in "${M_HOST[@]:1}"; do
  [[ $(stat -c %u:%g "$h") == "$MEDIA_UID:$MEDIA_GID" ]] || warn "$h has another owner ($(stat -c %u:%g "$h")) than ${M_HOST[0]}; Shrinkarr may not be able to write there."
done

# --- GPU ----------------------------------------------------------------------------------------
gpu_items=()
for r in /sys/class/drm/renderD*; do
  [[ -e $r ]] || continue
  v=$(cat "$r/device/vendor" 2>/dev/null || true)
  case $v in 0x8086) name="Intel (Quick Sync)" ;; 0x1002) name="AMD (VAAPI)" ;; 0x10de) name="NVIDIA (nouveau, not usable)" ;; *) name="other ($v)" ;; esac
  model=$(lspci -s "$(basename "$(readlink -f "$r/device")")" 2>/dev/null | cut -d: -f3- | sed 's/^ *//' || true)
  gpu_items+=("/dev/dri/$(basename "$r")" "$name ${model:0:40}")
done
[[ -e /dev/nvidia0 ]] && gpu_items+=("nvidia" "NVIDIA (NVENC, experimental)")
gpu_items+=("none" "No GPU: encode on the CPU (slow)")
choose GPU "Which GPU should Shrinkarr use?" "${gpu_items[0]}" "${gpu_items[@]}"
ok "GPU: $GPU"

# --- template -------------------------------------------------------------------------------
info "Looking for the Debian 13 template"
pveam update >/dev/null 2>&1 || true
ARCH=$(dpkg --print-architecture)
TPL=$(pveam available --section system 2>/dev/null | awk -v a="_$ARCH." '/debian-13-standard/ && index($2, a) {print $2}' | sort -V | tail -1)
[[ -n $TPL ]] || TPL=$(pveam available --section system | awk -v a="_$ARCH." '/debian-12-standard/ && index($2, a) {print $2}' | sort -V | tail -1)
# Use a template that is already downloaded when there is one of the same release
LOCAL_TPL=$(pveam list "$(pvesm status -content vztmpl | awk 'NR>1 && $3=="active" {print $1; exit}')" 2>/dev/null \
  | awk -v a="_$ARCH." '/debian-13-standard/ && index($1, a) {sub(/.*vztmpl\//, "", $1); print $1}' | sort -V | tail -1)
[[ -n $LOCAL_TPL ]] && TPL=$LOCAL_TPL
[[ -n $TPL ]] || die "No Debian template found (pveam available)."
TPL_STORE=$(pvesm status -content vztmpl | awk 'NR>1 && $3=="active" {print $1; exit}')
if ! pveam list "$TPL_STORE" | grep -q "$TPL"; then
  info "Downloading $TPL"
  pveam download "$TPL_STORE" "$TPL" >/dev/null
fi
ok "Template $TPL"

# --- create -----------------------------------------------------------------------------------
NET="name=eth0,bridge=$CT_BRIDGE,ip=$CT_IP,type=veth"
[[ $CT_IP != dhcp ]] && NET="$NET,gw=$CT_GW"
# Mount points. A path with a space or comma can't be an mpN; that one becomes an lxc.mount.entry.
MP_ARGS=(); MOUNT_ENTRIES=(); m=0
esc() { local x=${1// /\\040}; echo "${x//,/\\054}"; }
for i in "${!M_HOST[@]}"; do
  h=${M_HOST[$i]}; c=${M_CT[$i]}
  if [[ $h == *[\ ,]* || $c == *[\ ,]* ]]; then
    MOUNT_ENTRIES+=("lxc.mount.entry: $(esc "$h") $(esc "${c#/}") none bind,create=dir 0 0")
  else
    MP_ARGS+=(--mp$m "$h,mp=$c,backup=0"); m=$((m+1))
  fi
done
MP_ARGS+=(--mp$m "$CT_STORAGE:$WORK_SIZE,mp=/work,backup=0")

info "Creating container $CTID"
pct create "$CTID" "$TPL_STORE:vztmpl/$TPL" \
  --hostname "$CT_HOSTNAME" --ostype debian --unprivileged 1 --features nesting=1,keyctl=1 \
  --cores "$CT_CORES" --memory "$CT_RAM" --swap 512 --rootfs "$CT_STORAGE:$CT_DISK" \
  --net0 "$NET" --onboot 1 "${MP_ARGS[@]}" \
  --description "Shrinkarr: shrink media from Sonarr/Radarr to HEVC. https://github.com/rvanderend/shrinkarr" >/dev/null
CONF=/etc/pve/lxc/$CTID.conf
# Everything below is appended right after creating, so it lands in the main section (no snapshots yet).
for e in "${MOUNT_ENTRIES[@]}"; do echo "$e" >> "$CONF"; done

# GPU passthrough. Device nodes get gid 44 (video) in the container; the service user is in that group.
n=0
if [[ $GPU == /dev/dri/* ]]; then
  echo "dev$n: $GPU,gid=44" >> "$CONF"; n=$((n+1))
  card=$(ls "/sys/class/drm/$(basename "$GPU")/device/drm" | grep -m1 '^card' || true)
  [[ -n $card ]] && echo "dev$n: /dev/dri/$card,gid=44" >> "$CONF" && n=$((n+1))
elif [[ $GPU == nvidia ]]; then
  for d in /dev/nvidia0 /dev/nvidiactl /dev/nvidia-uvm /dev/nvidia-uvm-tools /dev/nvidia-caps/nvidia-cap1 /dev/nvidia-caps/nvidia-cap2; do
    [[ -e $d ]] && echo "dev$n: $d,gid=44" >> "$CONF" && n=$((n+1))
  done
fi

# Ownership: map the owner of the media folder 1:1 into the container, so Shrinkarr can replace files.
idmap() {  # idmap <u|g> <id>
  local k=$1 id=$2
  if [[ $id -le 0 || $id -ge 65536 ]]; then echo "lxc.idmap: $k 0 100000 65536"; return; fi
  echo "lxc.idmap: $k 0 100000 $id"
  echo "lxc.idmap: $k $id $id 1"
  if [[ $id -lt 65535 ]]; then echo "lxc.idmap: $k $((id+1)) $((100000+id+1)) $((65535-id))"; fi
  return 0
}
# The id the owner has inside the container: 1-65535 are mapped 1:1 below; a host id in the default
# range of unprivileged containers (100000-165535, e.g. a bindfs overlay) is that id minus 100000.
ct_id() {  # ct_id <host id> <fallback> <what>
  local id=$1 fallback=$2 what=$3
  if [[ $id -ge 1 && $id -le 65535 ]]; then echo "$id"
  elif [[ $id -gt 100000 && $id -le 165535 ]]; then echo $((id - 100000))
  else
    warn "The media folder's $what ($id) can't be used inside the container; Shrinkarr uses $fallback and needs write access through the other permissions." >&2
    echo "$fallback"
  fi
}
SVC_UID=$(ct_id "$MEDIA_UID" 1000 owner)
SVC_GID=$(ct_id "$MEDIA_GID" 1000 group)
[[ $MEDIA_UID != "$SVC_UID" || $MEDIA_GID != "$SVC_GID" ]] && info "Shrinkarr runs as uid $SVC_UID, gid $SVC_GID in the container"
{ idmap u "$MEDIA_UID"; idmap g "$MEDIA_GID"; } >> "$CONF"
if [[ $MEDIA_UID -gt 0 && $MEDIA_UID -lt 65536 ]] && ! grep -q "^root:$MEDIA_UID:1$" /etc/subuid; then echo "root:$MEDIA_UID:1" >> /etc/subuid; fi
if [[ $MEDIA_GID -gt 0 && $MEDIA_GID -lt 65536 ]] && ! grep -q "^root:$MEDIA_GID:1$" /etc/subgid; then echo "root:$MEDIA_GID:1" >> /etc/subgid; fi
ok "Container $CTID created"

info "Starting the container"
pct start "$CTID"
for _ in $(seq 1 30); do
  pct exec "$CTID" -- bash -c 'getent hosts deb.debian.org >/dev/null' 2>/dev/null && break
  sleep 2
done
pct exec "$CTID" -- bash -c 'getent hosts deb.debian.org >/dev/null' || die "The container has no internet connection."

if [[ $GPU == nvidia ]]; then
  VER=$(awk '/NVRM version/ {for (i=1;i<=NF;i++) if ($i ~ /^[0-9]+\.[0-9.]+$/) {print $i; exit}}' /proc/driver/nvidia/version)
  info "Installing the NVIDIA $VER libraries in the container (same version as the host)"
  pct exec "$CTID" -- bash -c "apt-get update -qq && apt-get install -y -qq curl kmod >/dev/null &&
    curl -fsSL -o /tmp/nv.run https://download.nvidia.com/XFree86/Linux-x86_64/$VER/NVIDIA-Linux-x86_64-$VER.run &&
    sh /tmp/nv.run --no-kernel-module --silent --no-questions --ui=none >/dev/null && rm /tmp/nv.run" \
    || warn "Installing the NVIDIA libraries failed; Shrinkarr will fall back to the CPU."
fi

info "Installing Shrinkarr (this takes a few minutes)"
ENVS="SHRINKARR_UID=$SVC_UID SHRINKARR_GID=$SVC_GID"
if [[ -n ${SHRINKARR_TARBALL:-} ]]; then
  pct push "$CTID" "$SHRINKARR_TARBALL" /tmp/shrinkarr.tar.gz
  tar -xzf "$SHRINKARR_TARBALL" -O ./install/install.sh > /tmp/shrinkarr-install.sh 2>/dev/null \
    || tar -xzf "$SHRINKARR_TARBALL" -O install/install.sh > /tmp/shrinkarr-install.sh
  pct push "$CTID" /tmp/shrinkarr-install.sh /tmp/install.sh && rm /tmp/shrinkarr-install.sh
  pct exec "$CTID" -- bash -c "$ENVS SHRINKARR_TARBALL=/tmp/shrinkarr.tar.gz bash /tmp/install.sh"
else
  pct exec "$CTID" -- bash -c "apt-get update -qq && apt-get install -y -qq curl >/dev/null && curl -fsSL $RAW/install/install.sh | $ENVS bash"
fi

IP=$(pct exec "$CTID" -- hostname -I | awk '{print $1}')
echo
ok "${c_b}Shrinkarr is ready:${c_off} ${c_ok}http://$IP:8080${c_off}"
echo "  Open it and follow the setup wizard. Your media is in the container at:"
for i in "${!M_HOST[@]}"; do echo "    ${c_b}${M_CT[$i]}${c_off}  ←  ${M_HOST[$i]}"; done
echo "  The wizard helps you map these to the paths Sonarr/Radarr use."
echo "  Update later with: pct exec $CTID -- shrinkarr-update"

