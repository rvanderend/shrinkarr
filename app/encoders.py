"""Video encoders: Intel Quick Sync (qsv), VAAPI (AMD and Intel), NVIDIA NVENC and the CPU (libx265).

`detect()` finds the GPUs, tries a short test encode on each and remembers the result;
`resolve()` picks the encoder from the settings (or the best working one on "auto").
"""
import asyncio
import logging
import os
import shutil
from pathlib import Path

from . import config, db

log = logging.getLogger("shrinkarr.encoders")

LABELS = {"qsv": "Intel Quick Sync", "vaapi": "VAAPI", "nvenc": "NVIDIA NVENC", "cpu": "CPU (libx265)"}
VENDORS = {"0x8086": "intel", "0x1002": "amd", "0x10de": "nvidia"}
# Source codecs decoded on the GPU (8-bit 4:2:0, progressive); everything else is decoded in software.
HW_DECODE = {"h264", "mpeg2video"}
QSV_DECODERS = {"h264": "h264_qsv", "mpeg2video": "mpeg2_qsv"}
DEFAULT_FPS = {
    "qsv": {"2160p": 40, "1080p": 120, "720p": 230, "sd": 350},
    "vaapi": {"2160p": 40, "1080p": 110, "720p": 210, "sd": 320},
    "nvenc": {"2160p": 60, "1080p": 200, "720p": 350, "sd": 500},
    "cpu": {"2160p": 4, "1080p": 20, "720p": 45, "sd": 90},
}
AUTO_ORDER = ("nvenc", "qsv", "vaapi", "cpu")

_detected: list[dict] | None = None
_lock = asyncio.Lock()


def render_devices() -> list[dict]:
    out = []
    for dev in sorted(Path("/sys/class/drm").glob("renderD*")):
        vendor_id = (dev / "device" / "vendor").read_text().strip() if (dev / "device" / "vendor").exists() else ""
        device_id = (dev / "device" / "device").read_text().strip() if (dev / "device" / "device").exists() else ""
        out.append({"path": f"/dev/dri/{dev.name}", "vendor": VENDORS.get(vendor_id, "other"),
                    "deviceId": device_id.replace("0x", "")})
    return out


def nvidia_present() -> bool:
    return os.path.exists("/dev/nvidia0") or shutil.which("nvidia-smi") is not None


def candidates() -> list[dict]:
    devs = render_devices()
    out = []
    if nvidia_present():
        out.append({"encoder": "nvenc", "device": ""})
    for d in devs:
        if d["vendor"] == "intel":
            out.append({"encoder": "qsv", "device": d["path"]})
            out.append({"encoder": "vaapi", "device": d["path"]})
        elif d["vendor"] == "amd":
            out.append({"encoder": "vaapi", "device": d["path"]})
    out.append({"encoder": "cpu", "device": ""})
    return out


def init_args(enc: dict) -> list[str]:
    if enc["encoder"] == "qsv":
        return ["-init_hw_device", f"qsv=hw:{enc['device']}", "-filter_hw_device", "hw"]
    if enc["encoder"] == "vaapi":
        return ["-init_hw_device", f"vaapi=va:{enc['device']}", "-filter_hw_device", "va"]
    return []


def can_hw_decode(enc: dict, vi: dict) -> bool:
    return (enc["encoder"] != "cpu" and vi["codec"] in HW_DECODE and not vi["interlaced"]
            and vi["pix_fmt"] in ("yuv420p", "yuvj420p"))


def decode_args(enc: dict, vi: dict) -> list[str]:
    """Input options for decoding on the GPU (only when can_hw_decode)."""
    if enc["encoder"] == "qsv":
        return ["-hwaccel", "qsv", "-hwaccel_output_format", "qsv", "-c:v", QSV_DECODERS[vi["codec"]]]
    if enc["encoder"] == "vaapi":
        return ["-hwaccel", "vaapi", "-hwaccel_device", "va", "-hwaccel_output_format", "vaapi"]
    if enc["encoder"] == "nvenc":
        return ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
    return []


def encode_args(enc: dict, vi: dict, hw_decode: bool, q: int) -> list[str]:
    name, ten = enc["encoder"], vi["ten_bit"]
    filters = []
    if not hw_decode:
        if vi["interlaced"]:
            filters.append("bwdif=mode=send_frame")
        if name == "cpu":
            filters.append("format=yuv420p10le" if ten else "format=yuv420p")
        else:
            filters.append("format=p010le" if ten else "format=nv12")
        if name == "vaapi":
            filters.append("hwupload")
    args = ["-vf", ",".join(filters)] if filters else []
    if name == "qsv":
        args += ["-c:v:0", "hevc_qsv", "-preset", "slow", "-global_quality", str(q),
                 "-extbrc", "1", "-look_ahead_depth", "40"]
    elif name == "vaapi":
        args += ["-c:v:0", "hevc_vaapi", "-rc_mode", "CQP", "-qp", str(q)]
    elif name == "nvenc":
        args += ["-c:v:0", "hevc_nvenc", "-preset", "p5", "-tune", "hq", "-rc", "vbr", "-cq", str(q), "-b:v", "0",
                 "-spatial-aq", "1", "-rc-lookahead", "32"]
    else:
        args += ["-c:v:0", "libx265", "-preset", "medium", "-crf", str(q), "-x265-params", "log-level=error"]
    if ten:
        args += ["-profile:v:0", "main10"]
    return args


def codec_name(enc: dict) -> str:
    return {"qsv": "hevc_qsv", "vaapi": "hevc_vaapi", "nvenc": "hevc_nvenc", "cpu": "libx265"}[enc["encoder"]]


async def test(enc: dict) -> dict:
    """Encodes one second of a test picture; returns {"ok", "error"}."""
    src = ["-f", "lavfi", "-i", "testsrc2=duration=1:size=640x360:rate=25"]
    vi = {"ten_bit": False, "interlaced": False}
    cmd = [config.FFMPEG, "-hide_banner", "-nostdin", "-v", "error", *init_args(enc), *src,
           *encode_args(enc, vi, False, 28), "-f", "null", "-"]
    try:
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL,
                                                    stderr=asyncio.subprocess.PIPE)
        _, err = await asyncio.wait_for(proc.communicate(), timeout=60)
    except (OSError, asyncio.TimeoutError) as e:
        return {"ok": False, "error": str(e)}
    lines = [ln for ln in err.decode(errors="replace").splitlines() if ln and not ln.startswith("libva info")]
    return {"ok": proc.returncode == 0, "error": "" if proc.returncode == 0 else (lines[-1] if lines else "failed")}


async def detect(force: bool = False) -> list[dict]:
    global _detected
    async with _lock:
        if _detected is None or force:
            res = []
            for c in candidates():
                r = await test(c)
                res.append({**c, "label": LABELS[c["encoder"]], **r})
            _detected = res
            log.info("Encoders: %s", ", ".join(f"{d['encoder']}{' ' + d['device'] if d['device'] else ''}="
                                               f"{'ok' if d['ok'] else 'no'}" for d in res))
        return _detected


async def resolve() -> dict:
    """The encoder to use: {"encoder", "device", "label"}."""
    s = db.get_settings()
    found = await detect()
    want, dev = s["encoder"], s["gpu_device"]
    if want in config.ENCODERS:
        match = [d for d in found if d["encoder"] == want and (not dev or not d["device"] or d["device"] == dev)]
        if match:
            return {"encoder": want, "device": match[0]["device"], "label": LABELS[want]}
        return {"encoder": want, "device": dev, "label": LABELS[want]}
    for name in AUTO_ORDER:
        for d in found:
            if d["encoder"] == name and d["ok"] and (not dev or not d["device"] or d["device"] == dev):
                return {"encoder": name, "device": d["device"], "label": LABELS[name]}
    return {"encoder": "cpu", "device": "", "label": LABELS["cpu"]}
