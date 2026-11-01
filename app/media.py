"""ffprobe, estimates, and building and running ffmpeg commands."""
import asyncio
import json
import os
import re
import statistics
import time
from pathlib import Path

from . import config, db, encoders

# Codecs that are already efficient: never re-encode.
EFFICIENT = {"hevc", "av1", "vp9", "vvc"}
MKV_SUBS = {"subrip", "ass", "ssa", "hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle", "webvtt", "text"}
CONVERT_SUBS = {"mov_text": "srt"}

CODEC_FACTOR = {"h264": 1.0, "mpeg2video": 0.6, "vc1": 0.75, "mpeg4": 0.8}
COPY_SPEED = 90e6  # bytes/s from /work to the media storage


# --- normalising what Sonarr/Radarr report ---------------------------------

def norm_codec(raw: str) -> str:
    r = (raw or "").lower().replace("-", "").replace(".", "")
    if r in ("x265", "h265", "hevc"):
        return "hevc"
    if r in ("x264", "h264", "avc"):
        return "h264"
    if r in ("av1", "vp9", "vvc"):
        return r
    if r in ("mpeg2", "mpeg2video"):
        return "mpeg2video"
    if r in ("vc1", "wmv3", "wmv", "vc-1"):
        return "vc1"
    if r in ("xvid", "divx", "mpeg4", "mpeg4part2"):
        return "mpeg4"
    return r or "unknown"


CODEC_LABEL = {"hevc": "HEVC", "h264": "H.264", "av1": "AV1", "vp9": "VP9", "vvc": "VVC",
               "mpeg2video": "MPEG-2", "vc1": "VC-1", "mpeg4": "MPEG-4"}


def bucket(width: int, height: int) -> str:
    if width >= 3200 or height >= 1800:
        return "2160p"
    if width >= 1700 or height >= 1000:
        return "1080p"
    if width >= 1200 or height >= 700:
        return "720p"
    return "sd"


def parse_runtime(s: str) -> float:
    try:
        parts = [float(p) for p in (s or "").split(":")]
    except ValueError:
        return 0.0
    sec = 0.0
    for p in parts:
        sec = sec * 60 + p
    return sec


def file_facts(mi: dict, size: int) -> dict:
    """Facts about a file from the mediaInfo of Sonarr/Radarr."""
    mi = mi or {}
    w, h = 0, 0
    m = re.match(r"(\d+)x(\d+)", mi.get("resolution") or "")
    if m:
        w, h = int(m.group(1)), int(m.group(2))
    dur = parse_runtime(mi.get("runTime", ""))
    fps = float(mi.get("videoFps") or 0) or 24.0
    codec = norm_codec(mi.get("videoCodec", ""))
    abr = float(mi.get("audioBitrate") or 0)
    vbr = float(mi.get("videoBitrate") or 0)
    if dur > 0:
        total_br = size * 8 / dur
        if vbr <= 0 or vbr > total_br:
            # No (reliable) video bitrate: total minus audio (or ~12% for audio and subtitles)
            vbr = total_br - abr * max(1, int(mi.get("audioStreamCount") or 1)) if abr else total_br * 0.88
            vbr = max(vbr, total_br * 0.3)
    hdr = mi.get("videoDynamicRangeType") or mi.get("videoDynamicRange") or ""
    return {
        "codec": codec,
        "codecLabel": CODEC_LABEL.get(codec, codec.upper()),
        "width": w, "height": h,
        "bucket": bucket(w, h) if w else "1080p",
        "duration": dur, "fps": fps,
        "vbr": vbr,
        "bitDepth": int(mi.get("videoBitDepth") or 8),
        "hdr": hdr,
        "audio": mi.get("audioLanguages") or "",
        "audioCodec": mi.get("audioCodec") or "",
        "audioChannels": mi.get("audioChannels") or 0,
        "subs": mi.get("subtitles") or "",
        "efficient": codec in EFFICIENT,
    }


# --- estimate model ------------------------------------------------------------

class Model:
    """Ratio of new to old video size and the encode speed, learned from earlier conversions."""

    def __init__(self, encoder: str = "qsv"):
        self.encoder = encoder
        self.ratio: dict[tuple, float] = {}
        self.fps: dict[str, float] = {}
        obs = db.observations(encoder)
        groups: dict[tuple, list] = {}
        fpsg: dict[str, list] = {}
        for o in obs:
            if o["ratio"]:
                groups.setdefault((o["preset"], o["bucket"], o["codec"]), []).append(o["ratio"])
                groups.setdefault((o["preset"], o["bucket"], "*"), []).append(o["ratio"])
            if o["fps"]:
                fpsg.setdefault(o["bucket"], []).append(o["fps"])
        self.ratio = {k: statistics.median(v[:30]) for k, v in groups.items()}
        self.fps = {k: statistics.median(v[:30]) for k, v in fpsg.items()}
        self.count = len(obs)

    def base_ratio(self, preset: str, bkt: str, codec: str) -> float:
        for key in ((preset, bkt, codec), (preset, bkt, "*")):
            if key in self.ratio:
                return self.ratio[key]
        return config.PRESETS[preset]["ratio"] * CODEC_FACTOR.get(codec, 0.9)

    def enc_fps(self, bkt: str) -> float:
        return self.fps.get(bkt, encoders.DEFAULT_FPS.get(self.encoder, encoders.DEFAULT_FPS["qsv"])[bkt])


def estimate(f: dict, size: int, preset: str, model: Model, sample: dict | None = None) -> dict:
    """Estimated size and conversion time of one file."""
    if f["efficient"] or f["duration"] <= 0:
        return {"size": size, "seconds": 0, "convertible": False}
    p = config.PRESETS[preset]
    vbytes = min(f["vbr"] * f["duration"] / 8, size * 0.97)
    if sample:
        ratio, fps = sample["ratio"], sample["fps"]
    else:
        ratio, fps = model.base_ratio(preset, f["bucket"], f["codec"]), model.enc_fps(f["bucket"])
        # A source with few bits per pixel has less to gain.
        pixels = max(f["width"] * f["height"], 1) * f["fps"]
        src_bpp = f["vbr"] / pixels if f["width"] else 0.15
        if src_bpp > 0:
            out_bpp = max(src_bpp * ratio, min(src_bpp * 0.85, p["floor_bpp"]))
            ratio = out_bpp / src_bpp
    new_size = int(size - vbytes + vbytes * ratio)
    seconds = f["duration"] * f["fps"] / max(fps, 1) + new_size / COPY_SPEED
    return {"size": new_size, "seconds": seconds, "convertible": True, "ratio": ratio, "sampled": bool(sample)}


# --- ffprobe ---------------------------------------------------------------

async def probe(path: str) -> dict:
    proc = await asyncio.create_subprocess_exec(
        config.FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {err.decode(errors='replace').strip()[-300:]}")
    return json.loads(out)


def streams(p: dict, kind: str) -> list[dict]:
    res = [s for s in p.get("streams", []) if s.get("codec_type") == kind]
    if kind == "video":
        res = [s for s in res if not s.get("disposition", {}).get("attached_pic")]
    return res


def duration_of(p: dict) -> float:
    try:
        return float(p["format"]["duration"])
    except (KeyError, ValueError, TypeError):
        return 0.0


def tag(s: dict, name: str):
    tags = s.get("tags") or {}
    for k, v in tags.items():
        if k.upper() == name or k.upper().startswith(name + "-"):
            return v
    return None


def video_bytes(p: dict, size: int) -> float:
    """Size of the video stream in the source: from the mkvmerge tags, else from the bitrate."""
    v = streams(p, "video")[0]
    nb = tag(v, "NUMBER_OF_BYTES")
    if nb and str(nb).isdigit() and 0 < float(nb) < size:
        return float(nb)
    dur = duration_of(p)
    br = v.get("bit_rate") or tag(v, "BPS")
    if br and str(br).isdigit() and dur and 0 < float(br) * dur / 8 < size:
        return float(br) * dur / 8
    other = sum(float(s.get("bit_rate") or tag(s, "BPS") or 0) for s in streams(p, "audio")) * dur / 8
    return max(size - other, size * 0.5) if other else size * 0.88


def video_info(p: dict) -> dict:
    v = streams(p, "video")[0]
    pix = v.get("pix_fmt") or ""
    fr = v.get("avg_frame_rate") or v.get("r_frame_rate") or "24/1"
    try:
        n, d = fr.split("/")
        fps = float(n) / float(d) if float(d) else 24.0
    except ValueError:
        fps = 24.0
    return {
        "stream": v,
        "codec": v.get("codec_name", ""),
        "ten_bit": any(x in pix for x in ("10", "12")),
        "interlaced": v.get("field_order") in ("tt", "bb", "tb", "bt"),
        "width": int(v.get("width") or 0), "height": int(v.get("height") or 0),
        "fps": fps if 1 < fps < 200 else 24.0,
        "closed_captions": bool(v.get("closed_captions")),
        "pix_fmt": pix,
    }


# --- ffmpeg commands ------------------------------------------------------------

def plan_streams(p: dict) -> dict:
    """Which streams to keep. Subtitles MKV doesn't support block the conversion."""
    subs, unsupported = [], []
    for s in streams(p, "subtitle"):
        c = s.get("codec_name", "")
        if c in MKV_SUBS or c in CONVERT_SUBS:
            subs.append(s)
        else:
            unsupported.append(c or "unknown")
    return {
        "audio": streams(p, "audio"),
        "subs": subs,
        "attachments": [s for s in p.get("streams", []) if s.get("codec_type") == "attachment"],
        "unsupported_subs": unsupported,
    }


STAT_TAGS = ["BPS", "NUMBER_OF_BYTES", "NUMBER_OF_FRAMES", "DURATION", "_STATISTICS_TAGS",
             "_STATISTICS_WRITING_APP", "_STATISTICS_WRITING_DATE_UTC"]


def build_cmd(p: dict, src: str, dst: str, enc: dict, quality: int, hw: bool, *, ss: float | None = None,
              t: float | None = None, video_only: bool = False, cc_srt: str | None = None) -> list[str]:
    vi = video_info(p)
    plan = plan_streams(p)
    cmd = [config.FFMPEG, "-hide_banner", "-nostdin", "-y", "-nostats", "-progress", "pipe:1",
           *encoders.init_args(enc)]
    if hw:
        cmd += encoders.decode_args(enc, vi)
    if ss is not None:
        cmd += ["-ss", f"{ss:.2f}"]
    if t is not None:
        cmd += ["-t", f"{t:.2f}"]
    cmd += ["-i", src]
    if cc_srt:
        cmd += ["-i", cc_srt]

    cmd += ["-map", f"0:{vi['stream']['index']}"]
    if not video_only:
        for s in plan["audio"]:
            cmd += ["-map", f"0:{s['index']}"]
        for s in plan["subs"]:
            cmd += ["-map", f"0:{s['index']}"]
        if cc_srt:
            cmd += ["-map", "1:0"]
        for s in plan["attachments"]:
            cmd += ["-map", f"0:{s['index']}"]
        cmd += ["-map_metadata", "0", "-map_chapters", "0"]
    cmd += ["-c", "copy", *encoders.encode_args(enc, vi, hw, quality)]
    v = vi["stream"]
    for opt, key in (("-color_primaries", "color_primaries"), ("-color_trc", "color_transfer"),
                     ("-colorspace", "color_space")):
        val = v.get(key)
        if val and val not in ("unknown", "reserved"):
            cmd += [opt, val]
    if not video_only:
        for i, s in enumerate(plan["subs"]):
            if s.get("codec_name") in CONVERT_SUBS:
                cmd += [f"-c:s:{i}", CONVERT_SUBS[s["codec_name"]]]
        if cc_srt:
            i = len(plan["subs"])
            lang = tag(v, "LANGUAGE") or "eng"
            cmd += [f"-c:s:{i}", "srt", f"-metadata:s:s:{i}", f"language={lang}",
                    f"-metadata:s:s:{i}", "title=Closed captions"]
        # The statistics tags of the old video stream are wrong now: drop them.
        for t_ in STAT_TAGS:
            for suffix in ("", "-eng"):
                cmd += ["-metadata:s:v:0", f"{t_}{suffix}="]
        cmd += ["-metadata", f"SHRINKARR={encoders.codec_name(enc)} q{quality}"]
    cmd += ["-max_muxing_queue_size", "9999", "-f", "matroska", dst]
    return cmd


class FFmpegError(RuntimeError):
    def __init__(self, msg: str, log: str):
        super().__init__(msg)
        self.log = log


async def run_ffmpeg(cmd: list[str], on_progress=None, proc_holder: dict | None = None) -> dict:
    """Runs ffmpeg; returns the last progress values and the tail of stderr."""
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE)
    if proc_holder is not None:
        proc_holder["proc"] = proc
    tail: list[str] = []

    async def read_err():
        async for line in proc.stderr:
            tail.append(line.decode(errors="replace").rstrip())
            if len(tail) > 80:
                del tail[:20]

    err_task = asyncio.create_task(read_err())
    block: dict = {}
    last: dict = {}
    async for raw in proc.stdout:
        line = raw.decode(errors="replace").strip()
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        block[k] = v
        if k == "progress":
            last = dict(block)
            if on_progress:
                await on_progress(last)
            block = {}
    await proc.wait()
    await err_task
    log = "\n".join(tail[-40:])
    if proc.returncode != 0:
        lines = [ln for ln in tail if ln and not ln.startswith(("libva info", "  "))]
        raise FFmpegError(lines[-1] if lines else f"ffmpeg exited with code {proc.returncode}", log)
    # "video:1234KiB audio:..." from the summary
    m = None
    for ln in reversed(tail):
        m = re.search(r"video:\s*([\d.]+)\s*(KiB|kB)", ln)
        if m:
            break
    last["video_bytes"] = float(m.group(1)) * 1024 if m else None
    last["log"] = log
    return last


def parse_progress(pr: dict) -> tuple[float, float, float, int]:
    """(seconds, fps, speed, bytes) from a -progress block."""
    us = pr.get("out_time_us") or pr.get("out_time_ms") or "0"
    try:
        sec = max(int(us), 0) / 1e6
    except ValueError:
        sec = 0.0

    def fl(x):
        try:
            return float(str(x).rstrip("x"))
        except ValueError:
            return 0.0
    try:
        size = int(pr.get("total_size") or 0)
    except ValueError:
        size = 0
    return sec, fl(pr.get("fps")), fl(pr.get("speed")), size


async def extract_cc(src: str, dst: str, workdir: Path) -> bool:
    """Extracts closed captions (EIA-608 in the H.264 stream) as SRT. True if there is something in it."""
    link = workdir / f"cc-src{Path(src).suffix}"
    try:
        link.unlink(missing_ok=True)
        link.symlink_to(src)
        cmd = [config.FFMPEG, "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
               "-f", "lavfi", "-i", f"movie={link}[out0+subcc]", "-map", "0:s", "-c:s", "srt", dst]
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL,
                                                    stderr=asyncio.subprocess.PIPE)
        await proc.communicate()
        return proc.returncode == 0 and os.path.exists(dst) and os.path.getsize(dst) > 64
    finally:
        link.unlink(missing_ok=True)


# --- test encode for an accurate estimate --------------------------------------

_sample_lock = asyncio.Lock()


async def sample(path: str, preset: str, enc: dict, segments: int = 3, seg_len: float = 12.0) -> dict:
    """Encodes a few fragments and measures the video size ratio and the speed."""
    async with _sample_lock:
        p = await probe(path)
        vi = video_info(p)
        dur = duration_of(p)
        if dur < seg_len * 2:
            raise RuntimeError("The file is too short for a test encode")
        q = config.PRESETS[preset]["q"][enc["encoder"]]
        tmp = config.WORK_DIR / "sample"
        tmp.mkdir(parents=True, exist_ok=True)
        src_total = enc_total = 0.0
        fps_list = []
        points = [dur * (i + 1) / (segments + 1) for i in range(segments)]
        hw = encoders.can_hw_decode(enc, vi)
        for ss in points:
            ref = tmp / "ref.mkv"
            out = tmp / "enc.mkv"
            copy = [config.FFMPEG, "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-ss", f"{ss:.2f}",
                    "-t", f"{seg_len}", "-i", path, "-map", f"0:{vi['stream']['index']}", "-c", "copy",
                    "-f", "matroska", str(ref)]
            proc = await asyncio.create_subprocess_exec(*copy, stderr=asyncio.subprocess.PIPE)
            _, err = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(err.decode(errors="replace")[-300:])
            rp = await probe(str(ref))
            start = time.monotonic()
            try:
                res = await run_ffmpeg(build_cmd(rp, str(ref), str(out), enc, q, hw, video_only=True))
            except FFmpegError:
                if not hw:
                    raise
                hw = False
                start = time.monotonic()
                res = await run_ffmpeg(build_cmd(rp, str(ref), str(out), enc, q, False, video_only=True))
            elapsed = time.monotonic() - start
            src_total += ref.stat().st_size
            enc_total += out.stat().st_size
            frames = float(res.get("frame") or 0)
            reported = float(res.get("fps") or 0)  # ffmpeg leaves out the start-up time
            if reported > 0:
                fps_list.append(reported)
            elif frames and elapsed:
                fps_list.append(frames / elapsed)
        for f in tmp.iterdir():
            f.unlink(missing_ok=True)
        ratio = enc_total / src_total if src_total else 1.0
        fps = statistics.median(fps_list) if fps_list else \
            encoders.DEFAULT_FPS[enc["encoder"]][bucket(vi["width"], vi["height"])]
        return {"ratio": ratio, "fps": fps, "bucket": bucket(vi["width"], vi["height"]), "codec": vi["codec"],
                "hw": hw}
