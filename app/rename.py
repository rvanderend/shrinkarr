"""Updating the codec words in the names of files that were converted before the option was on.

What Shrinkarr changed comes from the `SHRINKARR` tag it writes into every converted file (`qsv q21 + eac3`,
`video copy + eac3`, ...), so the same rules apply as for a new conversion. A scan lists what would change;
nothing is renamed until that list is confirmed. The renaming takes the same route as after a conversion:
sidecar files along, then Sonarr/Radarr get the new file before the rescan, so nothing is unmonitored.
"""
import asyncio
import json
import logging
import os
from pathlib import Path

from . import arr, db, media, naming
from .worker import update_arr

log = logging.getLogger("shrinkarr.rename")

# One scan or run at a time; the web UI polls this.
STATE: dict = {"busy": False, "stage": "", "done": 0, "total": 0, "items": [], "errors": []}


def mark_of(p: dict) -> str | None:
    tags = (p.get("format") or {}).get("tags") or {}
    return next((v for k, v in tags.items() if k.upper() == "SHRINKARR"), None)


def plan(path: Path, p: dict) -> Path | None:
    """The new path for a converted file, or None when its name is already right (or not ours)."""
    mark = mark_of(p)
    if not mark:
        return None
    audio = media.streams(p, "audio")
    eac3 = [a for a in audio if a.get("codec_name") == "eac3"]
    stem = naming.new_stem(path.stem, video=not mark.startswith("video copy"),
                           dts="+ eac3" in mark and not any(a.get("codec_name") == "dts" for a in audio),
                           channels=max((int(a.get("channels") or 2) for a in eac3), default=6))
    new = path.with_name(stem + path.suffix)
    return new if new != path and not new.exists() else None


async def scan():
    """Lists the finished jobs whose file would get a new name."""
    STATE.update(busy=True, stage="scan", done=0, items=[], errors=[])
    try:
        rows = db.q("SELECT id, kind, arr_id, file_id, title, subtitle, path FROM jobs WHERE status='done' ORDER BY finished")
        # A file that is in the queue again keeps its name: the job would no longer find it.
        seen, jobs = {r["path"] for r in db.q("SELECT path FROM jobs WHERE status IN ('queued','running')")}, []
        for j in reversed(rows):  # the newest job for a path counts
            if j["path"] not in seen and os.path.exists(j["path"]):
                seen.add(j["path"])
                jobs.append(j)
        STATE["total"] = len(jobs)
        sem = asyncio.Semaphore(4)

        async def one(j):
            async with sem:
                try:
                    new = plan(Path(j["path"]), await media.probe(j["path"]))
                    if new:
                        STATE["items"].append({**j, "new_path": str(new)})
                except Exception as e:  # noqa: BLE001
                    STATE["errors"].append(f"{j['path']}: {e}")
                STATE["done"] += 1
        await asyncio.gather(*(one(j) for j in jobs))
        STATE["items"].sort(key=lambda i: i["path"])
    finally:
        STATE.update(busy=False, stage="scanned")


async def apply(ids: list[int]):
    """Renames the scanned files with these job ids, one at a time."""
    todo = [i for i in STATE["items"] if i["id"] in set(ids)]
    STATE.update(busy=True, stage="apply", done=0, total=len(todo), errors=[])
    try:
        for i in todo:
            try:
                await _rename(i)
                i["renamed"] = True
            except Exception as e:  # noqa: BLE001
                log.exception("Renaming %s failed", i["path"])
                STATE["errors"].append(f"{Path(i['path']).name}: {e}")
            STATE["done"] += 1
    finally:
        STATE["items"] = [i for i in STATE["items"] if not i.get("renamed")]
        STATE.update(busy=False, stage="applied")


async def _rename(i: dict):
    src, final = Path(i["path"]), Path(i["new_path"])
    if not src.exists() or final.exists():
        raise RuntimeError("the file changed since the scan")
    if db.one("SELECT id FROM jobs WHERE path=? AND status IN ('queued','running')", (str(src),)):
        raise RuntimeError("the file is in the queue")
    state, has_arr = None, arr.configured("radarr" if i["kind"] == "movie" else "sonarr")
    if has_arr:
        file_id = await arr.find_file(i["kind"], i["arr_id"], str(src)) or i["file_id"]
        state = await arr.file_state(i["kind"], i["arr_id"], file_id)
    os.rename(src, final)
    renamed = naming.rename_sidecars(src, final)
    new_id, notes = await update_arr(i["kind"], i["arr_id"], state, final) if has_arr else (None, [])
    if arr.plex_configured():
        try:
            await arr.plex_refresh(str(final))
        except Exception as e:  # noqa: BLE001
            notes.append(str(e))
    job = db.one("SELECT renamed FROM jobs WHERE id=?", (i["id"],))
    before = json.loads((job or {}).get("renamed") or "[]")
    db.update_job(i["id"], path=str(final), renamed=json.dumps(before + renamed),
                  **({"file_id": new_id} if new_id else {}))
    log.info("Renamed %s -> %s (%d sidecar file(s))%s", src.name, final.name, len(renamed),
             "; " + "; ".join(notes) if notes else "")
    if notes:
        STATE["errors"].append(f"{final.name}: " + "; ".join(notes))
    if has_arr:
        asyncio.create_task(arr.LIB.refresh_item("movie" if i["kind"] == "movie" else "series", i["arr_id"]))
