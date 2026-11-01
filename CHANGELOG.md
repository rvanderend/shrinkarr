# Changelog

## 1.0.1

- **Keep originals** (Settings → Encoding): keep a replaced original for 1–30 days, so a conversion can be undone from the History page. The original is moved (not copied) to a hidden `.shrinkarr-originals` folder in the root folder and deleted when its time is up. Off by default. (#4)
- **Versions:** `install.sh` and `shrinkarr-update` install the newest release by default; `shrinkarr-update v1.0.0` installs a given release and `shrinkarr-update main` the newest, untested state. (#3)
- `pct exec <ctid> -- shrinkarr-update` works: the command is also in `/usr/bin`. (#1)
- `proxmox.sh`: more than one media folder. Pick the sub-folders of a parent folder (or set `MEDIA_PATHS="a|b"`); each is mounted at `/data/<folder name>`, folders with a space or comma in the name too. (#5)
- `proxmox.sh`: a media folder owned by a host id in 100000–165535 (for example a bindfs overlay) now works; the service user gets the matching id inside the container. (#2)

## 1.0.0

First release.
