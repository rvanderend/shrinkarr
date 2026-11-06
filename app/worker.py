"""The queue: one job at a time on the GPU.

`stage` is stored as a code (analyze, encode, verify, ...); the web UI translates it.
"""
import asyncio
import errno
import json
import logging
import os
import shutil
import time
from contextlib import suppress
from datetime import datetime
from pathlib import Path

from . import arr, config, db, encoders, media, naming
from .i18n import tr

log = logging.getLogger("shrinkarr.worker")


class Skip(Exception):
    """Not an error, but the original stays (for example too little gain)."""


class Damaged(Exception):
    """The source file is damaged: failed, with a button in the history to download it again."""


class Cancelled(Exception):
    pass


def _between(a: str, b: str) -> bool:
    now = datetime.now().strftime("%H:%M")
    return a <= now < b if a <= b else (now >= a or now < b)


def in_window(s: dict) -> bool:
    return not s["window_enabled"] or _between(s["window_start"], s["window_end"])


def eligible(job: dict, s: dict) -> bool:
    """Manual jobs may always start; automatic ones only inside their window and after the delay."""
    if job.get("source") != "auto":
        return True
    return (job.get("not_before") or 0) <= time.time() and _between(s["auto_window_start"], s["auto_window_end"])


PLEX_WAIT_MAX = 12 * 3600  # waiting longer than this for a viewer: skip after all
KEEP_DIR = ".shrinkarr-originals"


def keep_location(kind: str, src: str) -> Path:
    """Where to keep a replaced original: <root folder>/.shrinkarr-originals/<path below the root>.

    Sonarr, Radarr and Plex skip folders whose name starts with a dot.
    """
    app = "radarr" if kind == "movie" else "sonarr"
    for r in sorted(arr.LIB.roots.get(app, []), key=lambda r: -len(r["path"])):
        base = arr.to_local(r["path"]).rstrip("/")
        if src.startswith(base + "/"):
            return Path(base) / KEEP_DIR / src[len(base) + 1:]
    return Path(src).parent / KEEP_DIR / Path(src).name


def writable(folder: str | Path) -> bool:
    """Can Shrinkarr create files here? False on a read-only mount or without permission."""
    return os.access(folder, os.W_OK | os.X_OK)


def _keep(kind: str, src: str) -> Path:
    """Moves the original out of the way (a rename on the same file system: no copying)."""
    dest = keep_location(kind, src)
    if dest.exists():
        dest = dest.with_name(f"{dest.stem}.{int(time.time())}{dest.suffix}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.rename(src, dest)
    except OSError as e:
        if e.errno != errno.EXDEV:
            raise
        # The root folder is on another mount than this file: keep it next to the file.
        dest = Path(src).parent / KEEP_DIR / Path(src).name
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.rename(src, dest)
    return dest


async def update_arr(kind: str, arr_id: int, state: dict | None, final: Path) -> tuple[int | None, list[str]]:
    """After a replace: tell Sonarr/Radarr about the file. With `state` (the file got a new path) the new
    file is imported first and monitoring is checked after the rescan; see arr.repoint.
    Returns the id of the new file record (or None) and notes for the job message."""
    notes, new_id = [], None
    app_name = "Radarr" if kind == "movie" else "Sonarr"
    if state:
        try:
            new_id = await arr.repoint(kind, arr_id, state, str(final))
            if not new_id:
                notes.append(tr("repoint_failed", app=app_name, err=tr("repoint_nofile")))
        except Exception as e:  # noqa: BLE001
            notes.append(tr("repoint_failed", app=app_name, err=e))
    try:
        cmd = await arr.rescan(kind, arr_id)
        if state:
            await arr.wait_command(app_name.lower(), cmd)
            if n := await arr.restore_monitored(kind, state):
                log.warning("%s unmonitored %d item(s) after the new path of %s; monitored again", app_name, n, final)
                notes.append(tr("remonitored", app=app_name, n=n))
    except Exception as e:  # noqa: BLE001
        notes.append(tr("rescan_failed", app=app_name, err=e))
    return new_id, notes


class Worker:
    def __init__(self):
        self.wake = asyncio.Event()
        self.current: int | None = None
        self.proc: dict = {}
        self.cancel_requested = False
        self.state = "idle"  # idle | running | paused | waiting | waiting_auto | setup

    async def run(self):
        config.WORK_DIR.mkdir(parents=True, exist_ok=True)
        # Leftovers of a conversion that was cut off by a restart
        for f in config.WORK_DIR.glob("job-*"):
            f.unlink(missing_ok=True)
        while True:
            try:
                s = db.get_settings()
                queued = db.q("SELECT * FROM jobs WHERE status='queued' ORDER BY position")
                job = next((j for j in queued if eligible(j, s)), None)
                if not s["setup_done"]:
                    self.state = "setup"
                elif s["paused"]:
                    self.state = "paused"
                elif queued and not in_window(s) and not db.get_state("window_bypass"):
                    self.state = "waiting"
                elif job:
                    self.state = "running"
                    await self.process(job)
                    continue
                elif queued:
                    self.state = "waiting_auto"  # only automatic jobs, outside their window
                else:
                    self.state = "idle"
                    if not queued and db.get_state("window_bypass"):
                        db.set_state("window_bypass", False)  # "start now" lasts until the queue is empty
                self.wake.clear()
                try:
                    await asyncio.wait_for(self.wake.wait(), timeout=15)
                except asyncio.TimeoutError:
                    pass
            except Exception:  # noqa: BLE001
                log.exception("Error in the worker loop")
                await asyncio.sleep(10)

    def cancel(self, job_id: int):
        if self.current == job_id:
            self.cancel_requested = True
            proc = self.proc.get("proc")
            if proc and proc.returncode is None:
                proc.terminate()

    # --- one job --------------------------------------------------------------

    async def process(self, job: dict):
        jid = job["id"]
        self.current, self.cancel_requested, self.proc = jid, False, {}
        out = config.WORK_DIR / f"job-{jid}.mkv"
        cc = config.WORK_DIR / f"job-{jid}.cc.srt"
        db.update_job(jid, status="running", stage="analyze", started=time.time(), progress=0,
                      message="", log="", finished=None, size_after=None)
        try:
            result = await self._process(job, out, cc)
            db.update_job(jid, status="done", stage="done", progress=1, finished=time.time(), eta=0, **result)
        except Cancelled:
            db.update_job(jid, status="cancelled", stage="cancelled", finished=time.time())
        except Skip as e:
            db.update_job(jid, status="skipped", stage="skipped", message=str(e), finished=time.time())
        except Damaged as e:
            db.update_job(jid, status="failed", stage="damaged", message=str(e), finished=time.time())
        except media.FFmpegError as e:
            if self.cancel_requested:
                db.update_job(jid, status="cancelled", stage="cancelled", finished=time.time())
            else:
                db.update_job(jid, status="failed", stage="failed", message=str(e), log=e.log,
                              finished=time.time())
        except Exception as e:  # noqa: BLE001
            log.exception("Job %s failed", jid)
            db.update_job(jid, status="failed", stage="failed", message=f"{type(e).__name__}: {e}",
                          finished=time.time())
        finally:
            for f in (out, cc):
                f.unlink(missing_ok=True)
            self.current = None
            self.proc = {}

    def _check_cancel(self):
        if self.cancel_requested:
            raise Cancelled()

    async def _process(self, job: dict, out: Path, cc: Path) -> dict:
        jid = job["id"]
        preset = job["preset"] if job["preset"] in config.PRESETS else "balanced"
        enc = await encoders.resolve()
        q = config.PRESETS[preset]["q"][enc["encoder"]]

        # 1. Analyse: current path, codec, streams
        src = job["path"]
        if not os.path.exists(src):
            info = await arr.resolve_file(job["kind"], job["file_id"])
            if not info:
                raise Skip(tr("gone"))
            src = arr.to_local(info["path"])
            db.update_job(jid, path=src)
        # Check this before hours of GPU time: replacing would fail anyway.
        if not writable(Path(src).parent):
            raise Skip(tr("read_only", folder=Path(src).parent))
        st = os.stat(src)
        # A few seconds of reading instead of a whole conversion that fails the duration check.
        empty, checked = await asyncio.to_thread(media.zero_blocks, src)
        if empty:
            raise Damaged(tr("damaged", empty=empty, checked=checked))
        p = await media.probe(src)
        if not media.streams(p, "video"):
            raise Skip(tr("no_video"))
        vi = media.video_info(p)
        dts = bool(db.get_settings()["dts_to_eac3"])
        rules = media.audio_rules(db.get_settings())
        plan = media.plan_streams(p, dts, rules)
        # Video already efficient: only the audio, if there is DTS to convert. A forced job re-encodes it anyway.
        audio_only = vi["codec"] in media.EFFICIENT and not job["force"]
        if audio_only and not plan["convert"]:
            raise Skip(tr("already", codec=vi["codec"].upper()))
        # Dolby Vision is dropped when re-encoding. Profile 5 has no HDR10/SDR base layer: its colours would be wrong.
        if not audio_only and vi["dv"] and vi["dv"]["compat"] == 0:
            raise Skip(tr("dv_no_base", profile=vi["dv"]["profile"]))
        if plan["unsupported_subs"]:
            raise Skip(tr("bad_subs", codecs=", ".join(plan["unsupported_subs"])))
        dur = media.duration_of(p)
        src_vbytes = media.video_bytes(p, st.st_size)
        if shutil.disk_usage(config.WORK_DIR).free < st.st_size * 1.1:
            raise RuntimeError(tr("no_space_work", path=config.WORK_DIR))
        db.update_job(jid, size_before=st.st_size)

        # 2. Keep closed captions in the video stream as SRT
        cc_path = None
        if vi["closed_captions"] and not audio_only:  # a copied video stream keeps its captions
            db.update_job(jid, stage="cc")
            if not await media.extract_cc(src, str(cc), config.WORK_DIR):
                raise Skip(tr("cc_failed"))
            cc_path = str(cc)
            self._check_cancel()

        # 3. Convert
        db.update_job(jid, stage="encode", progress=0)
        hw = encoders.can_hw_decode(enc, vi) and not audio_only
        started = time.monotonic()
        last_write = [0.0]

        async def on_progress(pr):
            sec, fps, speed, size = media.parse_progress(pr)
            now = time.monotonic()
            if now - last_write[0] < 1 and pr.get("progress") != "end":
                return
            last_write[0] = now
            frac = min(sec / dur, 1) if dur else 0
            eta = (dur - sec) / speed if speed > 0 else None
            db.update_job(jid, progress=frac, fps=fps, speed=speed, eta=eta, cur_size=size)

        try:
            res = await media.run_ffmpeg(media.build_cmd(p, src, str(out), enc, q, hw, cc_srt=cc_path,
                                                         dts=dts, audio_only=audio_only, rules=rules),
                                         on_progress, self.proc)
        except media.FFmpegError as e:
            self._check_cancel()
            if not hw:
                raise
            log.warning("Hardware decoding failed (%s); trying again with software decoding", e)
            db.update_job(jid, stage="encode_sw", progress=0)
            hw = False
            res = await media.run_ffmpeg(media.build_cmd(p, src, str(out), enc, q, False, cc_srt=cc_path,
                                                         dts=dts, audio_only=audio_only, rules=rules),
                                         on_progress, self.proc)
        self._check_cancel()
        enc_seconds = time.monotonic() - started

        # 4. Verify
        db.update_job(jid, stage="verify", eta=None)
        op = await media.probe(str(out))
        new_size = out.stat().st_size
        ov = media.streams(op, "video")
        if not ov or ov[0].get("codec_name") != ("hevc" if not audio_only else vi["codec"]):
            raise RuntimeError(tr("no_hevc") if not audio_only else tr("video_changed"))
        oa = media.streams(op, "audio")
        n_audio, n_subs = len(oa), len(media.streams(op, "subtitle"))
        want_subs = len(plan["subs"]) + (1 if cc_path else 0)
        if n_audio != len(plan["audio"]):
            raise RuntimeError(tr("audio_count", got=n_audio, want=len(plan["audio"])))
        langs, got = [media.track_lang(s) for s in plan["audio"]], [media.track_lang(s) for s in oa]
        if got != langs:
            raise RuntimeError(tr("audio_langs", got=", ".join(x or "?" for x in got), want=", ".join(x or "?" for x in langs)))
        for i in plan["convert"]:
            want_ch = min(int(plan["audio"][i].get("channels") or 2), 6)
            if oa[i].get("codec_name") != "eac3" or int(oa[i].get("channels") or 0) not in (want_ch, 6 if want_ch > 2 else 2):
                raise RuntimeError(tr("audio_not_eac3", n=i + 1))
        if n_subs != want_subs:
            raise RuntimeError(tr("sub_count", got=n_subs, want=want_subs))
        odur = media.duration_of(op)
        if abs(odur - dur) > max(2.0, dur * 0.005):
            # The samples may have missed a small hole: now read the whole original.
            empty, checked = await asyncio.to_thread(media.zero_blocks, src, None)
            if empty:
                raise Damaged(tr("damaged", empty=empty, checked=checked))
            raise RuntimeError(tr("duration", got=odur, want=dur))

        # Learn for the next estimates
        bkt = media.bucket(vi["width"], vi["height"])
        fps = float(res.get("frame") or 0) / enc_seconds if enc_seconds else 0
        new_vbytes = res.get("video_bytes") or (new_size - (st.st_size - src_vbytes))
        ratio = new_vbytes / src_vbytes if src_vbytes else None
        pixels = max(vi["width"] * vi["height"], 1) * vi["fps"]
        src_bpp = src_vbytes * 8 / dur / pixels if dur else 0
        if not audio_only:
            # Converted audio would skew the ratio: then only the size reported for the video stream counts.
            if plan["convert"] and not res.get("video_bytes"):
                ratio = None
            db.add_observation(preset, bkt, vi["codec"], ratio if src_bpp >= 0.08 else None,
                               fps if hw or enc["encoder"] == "cpu" else None, "job", enc["encoder"])

        s = db.get_settings()
        saved_pct = (1 - new_size / st.st_size) * 100
        # Converting only the audio is about playback, not space: the minimum savings don't apply.
        if not audio_only and saved_pct < s["min_savings"]:
            if saved_pct < 0:
                raise Skip(tr("grew", pct=-saved_pct))
            raise Skip(tr("too_little", pct=saved_pct, min=s["min_savings"]))

        # 5. Don't replace while someone is watching this file in Plex
        await self._wait_for_viewers(jid, src)

        # 6. Replace
        self._check_cancel()
        st2 = os.stat(src)
        if (st2.st_size, st2.st_mtime) != (st.st_size, st.st_mtime):
            raise Skip(tr("changed"))
        folder = Path(src).parent
        stem = Path(src).stem
        if s["rename_codec"]:
            new = [oa[i] for i in plan["convert"]]
            stem = naming.new_stem(stem, video=not audio_only,
                                   dts=bool(new) and not any(a.get("codec_name") == "dts" for a in oa),
                                   channels=max((int(a.get("channels") or 2) for a in new), default=6))
            if stem != Path(src).stem and (folder / (stem + ".mkv")).exists():
                log.warning("%s already exists; keeping the old name", stem + ".mkv")
                stem = Path(src).stem
        final = folder / (stem + ".mkv")
        if final != Path(src) and final.exists():
            raise RuntimeError(tr("exists", name=final.name))
        # A new path: read what Sonarr/Radarr know about the file now, to tell them about the new one later.
        state = None
        if final != Path(src) and arr.configured("radarr" if job["kind"] == "movie" else "sonarr"):
            state = await arr.file_state(job["kind"], job["arr_id"], job["file_id"])
        if shutil.disk_usage(folder).free < new_size + 1e9:
            raise RuntimeError(tr("no_space_nas"))
        tmp = folder / f".{final.stem}.shrinkarr-tmp"
        keep_days = int(db.get_settings()["keep_days"] or 0)
        kept = None
        db.update_job(jid, stage="replace", progress=0)
        try:
            await asyncio.to_thread(self._copy, out, tmp, jid, new_size)
            if tmp.stat().st_size != new_size:
                raise RuntimeError(tr("copy_incomplete"))
            os.chmod(tmp, st.st_mode & 0o777)
            if keep_days > 0:
                kept = _keep(job["kind"], src)
            os.replace(tmp, final)
        except BaseException:
            # Clean up without hiding the real error (the folder may have become read-only, for example).
            with suppress(OSError):
                tmp.unlink(missing_ok=True)
            if kept and kept.exists() and not os.path.exists(src):
                try:
                    os.rename(kept, src)  # put the original back
                except OSError:
                    log.error("Could not put the original back: %s is still in %s", src, kept)
            raise
        if final != Path(src) and not kept:
            os.unlink(src)
        log.info("Replaced: %s (%d -> %d bytes)%s", final, st.st_size, new_size, f"; original kept in {kept}" if kept else "")
        renamed = naming.rename_sidecars(Path(src), final) if final.stem != Path(src).stem else []

        # 7. Update Sonarr/Radarr and Plex
        db.update_job(jid, stage="update", path=str(final), size_after=new_size)
        extra = {}
        new_id, notes = await update_arr(job["kind"], job["arr_id"], state, final)
        if new_id:
            extra["file_id"] = new_id
        try:
            if arr.plex_configured() and not await arr.plex_refresh(str(final)):
                notes.append(tr("plex_nomatch", path=str(Path(arr.to_plex(str(final))).parent)))
        except Exception as e:  # noqa: BLE001
            notes.append(tr("plex_failed", err=e))
        asyncio.create_task(self._refresh_later(job["kind"], job["arr_id"]))
        msg = tr("smaller", pct=saved_pct) + (tr("plus_cc") if cc_path else "") + \
            (tr("plus_eac3", n=len(plan["convert"])) if plan["convert"] else "") + \
            (tr("plus_dropped", n=len(plan["dropped"]), list=", ".join(
                media.track_label(s) for s in plan["dropped"])) if plan["dropped"] else "") + \
            (tr("plus_renamed", name=final.name) if final.stem != Path(src).stem else "") + \
            ("; " + "; ".join(notes) if notes else "")
        if kept:
            extra.update(kept_path=str(kept), kept_until=time.time() + keep_days * 86400, orig_path=src)
        if renamed:
            extra["renamed"] = json.dumps(renamed)
        return {"size_after": new_size, "message": msg, "path": str(final), **extra}

    async def _wait_for_viewers(self, jid: int, src: str):
        start = time.monotonic()
        waiting = False
        while True:
            playing = await arr.plex_playing()
            if playing is None:
                return  # no Plex configured or not reachable: nothing to check
            if src not in playing:
                if waiting:
                    await asyncio.sleep(30)  # give Plex a moment to let go of the file
                return
            if not waiting:
                waiting = True
                db.update_job(jid, stage="wait_plex", eta=None)
                log.info("%s is being watched; replacing waits", src)
            if time.monotonic() - start > PLEX_WAIT_MAX:
                raise Skip(tr("watched_too_long"))
            for _ in range(6):
                self._check_cancel()
                await asyncio.sleep(10)

    def _copy(self, src: Path, dst: Path, jid: int, total: int):
        done, last = 0, 0.0
        with open(src, "rb") as fi, open(dst, "wb") as fo:
            while chunk := fi.read(16 * 1024 * 1024):
                if self.cancel_requested:
                    raise Cancelled()
                fo.write(chunk)
                done += len(chunk)
                if time.monotonic() - last > 1:
                    last = time.monotonic()
                    db.update_job(jid, progress=done / total)
            fo.flush()
            os.fsync(fo.fileno())

    async def _refresh_later(self, kind: str, arr_id: int):
        # Sonarr/Radarr need a moment for the rescan and the new mediaInfo.
        await asyncio.sleep(20)
        await arr.LIB.refresh_item("movie" if kind == "movie" else "series", arr_id)


WORKER = Worker()
