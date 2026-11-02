<p align="center"><img src="app/static/icon.svg" width="88" alt=""></p>

<h1 align="center">Shrinkarr</h1>

<p align="center">
  Shrink your Sonarr and Radarr library by re-encoding it to HEVC on your GPU.<br>
  A web UI with estimates, a queue, and safe in-place replacement. Audio and subtitles stay untouched.
</p>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/library-dark.png">
    <img src="docs/screenshots/library-light.png" alt="The Shrinkarr library: a ring with how much can still be saved, and posters with their current and expected size">
  </picture>
</p>

## What it does

- **Shows your library** from Sonarr and Radarr with posters, current size, the expected size after shrinking and how long it takes.
- **Estimates before you start.** A rough estimate from the bitrate, or an accurate one from a ~15-second test encode of a few fragments. Every conversion makes the rough estimates better.
- **Re-encodes on the GPU** to HEVC: Intel Quick Sync, AMD/Intel VAAPI, NVIDIA NVENC, or the CPU (libx265) when there is no GPU. Usually 50–70% smaller at hardly any visible difference.
- **Keeps everything else as it is.** All audio tracks, subtitles (MP4 text subtitles become SRT, closed captions in the video stream are saved as an SRT track), chapters and attachments are copied 1:1.
- **Replaces safely.** The new file is checked (codec, number of audio and subtitle tracks, duration, minimum gain) before it replaces the original. Sonarr, Radarr and Plex rescan afterwards.
- **Can keep originals** for a few days (optional), so you can undo a conversion with one click.
- **Never replaces a file someone is watching** in Plex: it waits until playback stops.
- **Converts new downloads automatically** (optional) through a webhook from Sonarr/Radarr, inside a time window, for example at night.
- **Sends a daily summary** by e-mail or Pushover.
- English and Dutch, light and dark, works well on a phone.

## Screenshots

| | Light | Dark |
|---|---|---|
| Library | ![](docs/screenshots/library-light.png) | ![](docs/screenshots/library-dark.png) |
| Details and estimate | ![](docs/screenshots/detail-light.png) | ![](docs/screenshots/detail-dark.png) |
| Queue | ![](docs/screenshots/queue-light.png) | ![](docs/screenshots/queue-dark.png) |
| Settings | ![](docs/screenshots/settings-light.png) | ![](docs/screenshots/settings-dark.png) |
| GPU | ![](docs/screenshots/gpu-light.png) | ![](docs/screenshots/gpu-dark.png) |
| Setup wizard | ![](docs/screenshots/wizard-welcome-light.png) | ![](docs/screenshots/wizard-welcome-dark.png) |
| Setup wizard: paths | ![](docs/screenshots/wizard-paths-light.png) | ![](docs/screenshots/wizard-paths-dark.png) |
| Login | ![](docs/screenshots/login-light.png) | ![](docs/screenshots/login-dark.png) |

<p align="center">
  <img src="docs/screenshots/phone-light.png" width="280" alt="Shrinkarr on a phone, light">
  &nbsp;
  <img src="docs/screenshots/phone-dark.png" width="280" alt="Shrinkarr on a phone, dark">
</p>

## Requirements

- Sonarr v4 and/or Radarr v5 or newer (one of them is enough). Plex is optional.
- Access to the same media files, with write permission (Shrinkarr replaces them).
- A GPU for reasonable speed: an Intel iGPU from 7th generation on, an AMD GPU with VCN, or an NVIDIA GPU with NVENC. Without a GPU it works on the CPU, roughly 5–10× slower.
- Room on a work disk for the biggest file you want to convert.

## Installation

### Proxmox VE

Run this on the Proxmox host (as root). It creates an LXC container, finds the GPU, passes it through, mounts your media folder with the right ownership and installs Shrinkarr:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/rvanderend/shrinkarr/main/install/proxmox.sh)"
```

It asks for a few things (with sensible defaults): container ID, storage, network, the **folder with your media on the host** (mount your NAS share on the host first) and which of its sub-folders hold movies and series, and which GPU to use. Each media folder is mounted at `/data/<folder name>`; folders you don't pick (photos, for example) stay out of the container. The owner of the media (uid/gid) is mapped into the unprivileged container, so Shrinkarr can replace files without making the container privileged; a host id in the range of unprivileged containers (100000–165535, as with a bindfs overlay) works too. Unattended use: see the variables at the top of [install/proxmox.sh](install/proxmox.sh), e.g. `MEDIA_PATHS="/mnt/nas/movies|/mnt/nas/tv"`.

### Debian or Ubuntu (container, VM or bare metal)

```bash
curl -fsSL https://raw.githubusercontent.com/rvanderend/shrinkarr/main/install/install.sh | SHRINKARR_UID=1000 SHRINKARR_GID=1000 bash
```

Set `SHRINKARR_UID`/`SHRINKARR_GID` to the owner of your media files. The script installs [jellyfin-ffmpeg](https://github.com/jellyfin/jellyfin-ffmpeg) (ffmpeg with QSV, VAAPI and NVENC), creates a `shrinkarr` user and a systemd service, and gives the user access to `/dev/dri` and `/dev/nvidia*`. Other options (port, work folder) are described at the top of [install/install.sh](install/install.sh).

**GPU notes**

- **Intel:** pass `/dev/dri/renderD128` (and `card*`) into the container. Works out of the box with jellyfin-ffmpeg.
- **AMD:** the same, through VAAPI.
- **NVIDIA:** the container needs the NVIDIA user-space libraries of exactly the same version as the driver on the host. The Proxmox script installs them; elsewhere install them yourself. NVENC support is new and has had little testing so far.

Open `http://<container-ip>:8080` afterwards. The **setup wizard** takes you through language, Sonarr/Radarr, Plex, paths, the encoder, an optional login and automatic conversion.

## How it works

1. The library comes from the Sonarr and Radarr API (media info per file). Posters are cached.
2. A job encodes the video to HEVC in the work folder. Hardware decoding is used for H.264 and MPEG-2; other sources (MPEG-4/XviD, VC-1, 10-bit H.264, interlaced) are decoded in software, with deinterlacing where needed.
3. The output is checked. The original **stays** when ffmpeg fails, the video isn't HEVC, an audio or subtitle track is missing, the duration differs by more than 2 s (or 0.5%), the gain is smaller than the minimum (15% by default), or the original changed in the meantime.
4. The new file is copied next to the original as a hidden temporary file and then renamed over it. An `.mp4`/`.avi` becomes `.mkv` (the original is deleted then). The file gets the tag `SHRINKARR=<encoder> q<quality>`.
   With **Keep originals** on, the original is first moved to `<root folder>/.shrinkarr-originals/…` (a rename on the same disk, no copying; Sonarr, Radarr and Plex skip folders starting with a dot). The History page then has an **Undo** button until it is deleted after the chosen number of days.
5. Sonarr/Radarr rescan the item, Plex rescans only that folder.

Files that are already HEVC, AV1 or VP9 are left alone.

### Quality presets

| Preset | Intel QSV | VAAPI | NVENC | CPU (x265) | Measured on 1080p WEB H.264 at 9.8 Mbps (QSV) |
|---|---|---|---|---|---|
| High quality | `global_quality` 19 | QP 22 | CQ 23 | CRF 21 | 4.8 Mbps, VMAF 94.8 |
| Balanced (default) | 21 | 24 | 26 | 23 | 3.9 Mbps, VMAF 93.4 |
| Maximum savings | 24 | 27 | 29 | 26 | ~2.6 Mbps, VMAF ~89 |

QSV uses `-preset slow -extbrc 1 -look_ahead_depth 40`. An Intel UHD 770 does about 120–150 fps at 1080p (5–6× real time). 10-bit sources become HEVC Main10, 8-bit stays 8-bit; color metadata is kept. The VAAPI, NVENC and CPU values are chosen to give about the same quality, but were not measured with VMAF.

### Automatic conversion

Settings → Automatic conversion → **Set up the webhooks in Sonarr/Radarr** creates a Webhook connection named "Shrinkarr" (on import and upgrade) in both. New files are queued when they are MKV, not HEVC yet, in a root folder you selected, and not waiting for a better version (cutoff not met). Automatic jobs only start inside their own time window (01:00–08:00 by default) and at least an hour after the download, so subtitle tools and the first viewing go first. Every 15 minutes the import history is checked for anything the webhook missed.

The webhook address must be reachable from Sonarr/Radarr without a login. By default it's the LAN address of the container; the URL contains a secret token.

## Updating

```bash
shrinkarr-update                      # the newest release, inside the container
pct exec <ctid> -- shrinkarr-update   # the same, from the Proxmox host
shrinkarr-update v1.0.0               # a given release (see Releases)
shrinkarr-update main                 # the newest, untested state
```

A running conversion starts again after the restart; pause the queue first if you like. What changed is in [CHANGELOG.md](CHANGELOG.md); Settings → About shows when a newer release is out.

## Troubleshooting

- **"Not found in Shrinkarr" in the path check.** Sonarr/Radarr see the files under another path than Shrinkarr. Add a mapping, e.g. `/media` (in Radarr) → `/data/media` (in Shrinkarr). The check suggests one when it finds a folder with the same name.
- **"Found, but Shrinkarr can't write here".** The service user (`id shrinkarr` in the container) needs write access to the media folders. On NFS with `all_squash`, new files get the squashed owner; that's fine as long as the group can read and write.
- **Plex can't be reached.** With "Secure connections: Required" use `https://<ip>:32400`; Shrinkarr accepts Plex's own certificate on the LAN.
- **The encoder says "does not work".** Check that `/dev/dri/renderD*` exists in the container and belongs to a group the `shrinkarr` user is in (`ls -l /dev/dri`, `id shrinkarr`), then press *Detect again*. Logs: `journalctl -u shrinkarr -f`.

## Security

Shrinkarr has an optional login (one user, scrypt-hashed password, signed session cookie). Without it, anyone on your network can use it, so either turn it on or put it behind a reverse proxy with its own login (Authelia, Authentik). The webhook endpoint is protected by its own token and stays reachable for Sonarr/Radarr either way. Other tools (Home Assistant, scripts) use the API key from Settings → Login in the `X-Api-Key` header; `/api/stats` has a summary for dashboards. API keys and tokens are stored in the database in the container and are only shown masked in the UI.

## Development

```
app/main.py        FastAPI routes, login, setup and test endpoints
app/worker.py      the queue: convert, verify, replace, rescan
app/media.py       ffprobe, ffmpeg commands, estimates and test encodes
app/encoders.py    QSV / VAAPI / NVENC / CPU: detection and ffmpeg options
app/arr.py         Sonarr, Radarr, Plex and path mapping
app/auto.py        webhooks, history catch-up, daily summary
app/gpu.py         live GPU information (sysfs, fdinfo, vainfo, nvidia-smi)
app/static/        web UI: vanilla JS modules, no build step (i18n.js holds the texts)
install/           install.sh (Debian/Ubuntu) and proxmox.sh (LXC)
```

`scripts/dev-deploy.sh <ssh-host>` puts your working tree on a machine with Shrinkarr installed.

## License

Shrinkarr is **source-available** under the [PolyForm Strict License 1.0.0](LICENSE): you may use it for any noncommercial purpose, including at home. You may not distribute it or publish modified versions. Development happens in this repository: ideas, bug reports and pull requests are welcome, see [CONTRIBUTING.md](CONTRIBUTING.md).

Shrinkarr uses [jellyfin-ffmpeg](https://github.com/jellyfin/jellyfin-ffmpeg), [FastAPI](https://fastapi.tiangolo.com) and [httpx](https://www.python-httpx.org); those keep their own licenses.
