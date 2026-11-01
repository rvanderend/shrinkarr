"""Information about the GPU in use, from sysfs, fdinfo, vainfo and nvidia-smi (works in an unprivileged LXC)."""
import asyncio
import os
import re
import shutil
import time
from pathlib import Path

from . import config, encoders

INTEL_NAMES = {"4680": "Intel UHD Graphics 770", "4690": "Intel UHD Graphics 770", "a780": "Intel UHD Graphics 770",
               "4682": "Intel UHD Graphics 730", "4692": "Intel UHD Graphics 730", "a782": "Intel UHD Graphics 730",
               "4626": "Intel Iris Xe Graphics", "46a6": "Intel Iris Xe Graphics", "a7a0": "Intel Iris Xe Graphics",
               "46d1": "Intel UHD Graphics (N100)", "46d0": "Intel UHD Graphics (N-series)",
               "3e92": "Intel UHD Graphics 630", "3e9b": "Intel UHD Graphics 630", "9bc5": "Intel UHD Graphics 630",
               "5912": "Intel HD Graphics 630", "4e61": "Intel UHD Graphics (Jasper Lake)",
               "56a0": "Intel Arc A770", "56a1": "Intel Arc A750", "56a5": "Intel Arc A380"}
CODECS = [("H.264", "VAProfileH264"), ("HEVC 8-bit", "VAProfileHEVCMain"), ("HEVC 10-bit", "VAProfileHEVCMain10"),
          ("AV1", "VAProfileAV1"), ("VP9", "VAProfileVP9"), ("MPEG-2", "VAProfileMPEG2"), ("VC-1", "VAProfileVC1")]

_static: dict[str, dict] = {}
_prev: dict | None = None


def _read(path: Path, default=None):
    try:
        return path.read_text().strip()
    except OSError:
        return default


def _card(device: str) -> Path | None:
    render = Path("/sys/class/drm") / Path(device).name
    cards = sorted((render / "device" / "drm").glob("card*"))
    return cards[0] if cards else None


async def _run(*cmd: str, timeout: float = 10) -> str:
    try:
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.STDOUT)
        return (await asyncio.wait_for(proc.communicate(), timeout))[0].decode(errors="replace")
    except (OSError, asyncio.TimeoutError):
        return ""


async def _nvidia_query(fields: str) -> list[str]:
    if not shutil.which("nvidia-smi"):
        return []
    out = await _run("nvidia-smi", f"--query-gpu={fields}", "--format=csv,noheader,nounits")
    line = out.strip().splitlines()[0] if out.strip() else ""
    return [x.strip() for x in line.split(",")] if line else []


async def static_info(enc: dict) -> dict:
    """Model, drivers and codecs of the device in use; looked up once per device."""
    key = f"{enc['encoder']}:{enc['device']}"
    if key in _static:
        return _static[key]
    info = {"name": "CPU", "vendor": "cpu", "kernelDriver": "", "mediaDriver": "", "codecs": []}
    if enc["encoder"] == "nvenc":
        q = await _nvidia_query("name,driver_version")
        info.update(name=q[0] if q else "NVIDIA GPU", vendor="nvidia", kernelDriver="nvidia",
                    mediaDriver=f"NVIDIA {q[1]}" if len(q) > 1 else "")
    elif enc["device"]:
        card = _card(enc["device"])
        vendor = encoders.VENDORS.get(_read(card / "device" / "vendor", "") if card else "", "other")
        dev = (_read(card / "device" / "device", "") if card else "").replace("0x", "")
        name = INTEL_NAMES.get(dev, f"Intel GPU 0x{dev}") if vendor == "intel" else f"{vendor.upper()} GPU 0x{dev}"
        info.update(name=name, vendor=vendor,
                    kernelDriver=(card / "device" / "driver").resolve().name if card else "")
        out = await _run(config.VAINFO, "--display", "drm", "--device", enc["device"])
        m = re.search(r"Driver version:\s*(.+)", out)
        if m:
            info["mediaDriver"] = m.group(1).strip().replace("Intel iHD driver for Intel(R) Gen Graphics - ", "iHD ")
        pairs = re.findall(r"(VAProfile\w+)\s*:\s*(VAEntrypoint\w+)", out)
        for cname, prefix in CODECS:
            match = [e for p, e in pairs if (p == prefix if cname == "HEVC 8-bit" else p.startswith(prefix))]
            info["codecs"].append({"name": cname, "decode": "VAEntrypointVLD" in match,
                                   "encode": any(e.startswith("VAEntrypointEnc") for e in match)})
    else:
        info["name"] = f"CPU ({os.cpu_count()} threads)"
    _static[key] = info
    return info


def _engines(pid: int | None) -> dict | None:
    """Busy time per engine (ns) of our own ffmpeg process, from /proc/<pid>/fdinfo (Intel and AMD)."""
    if not pid:
        return None
    seen, total, cap = set(), {}, {}
    for f in Path(f"/proc/{pid}/fdinfo").glob("*"):
        txt = _read(f, "")
        if "drm-engine-" not in txt:
            continue
        cid = re.search(r"drm-client-id:\s*(\d+)", txt)
        if cid and cid.group(1) in seen:
            continue
        if cid:
            seen.add(cid.group(1))
        for k, v in re.findall(r"drm-engine-([a-z-]+):\s*(\d+) ns", txt):
            total[k] = total.get(k, 0) + int(v)
        for k, v in re.findall(r"drm-engine-capacity-([a-z-]+):\s*(\d+)", txt):
            cap[k] = int(v)
    return {"ns": total, "cap": cap} if total else None


def _snapshot(enc: dict, pid: int | None) -> dict:
    snap = {"t": time.monotonic(), "pid": pid, "engines": _engines(pid), "rc6": None, "cpu": None}
    card = _card(enc["device"]) if enc["device"] else None
    if card:
        rc6 = _read(card / "gt" / "gt0" / "rc6_residency_ms")
        snap["rc6"] = int(rc6) if rc6 and rc6.isdigit() else None
    stat = _read(Path("/proc/stat"), "")
    if stat.startswith("cpu "):
        vals = [int(x) for x in stat.splitlines()[0].split()[1:8]]
        snap["cpu"] = (sum(vals), vals[3] + vals[4])  # total, idle + iowait
    return snap


async def live(enc: dict, pid: int | None) -> dict:
    global _prev
    cur = _snapshot(enc, pid)
    if not _prev or not 0.4 < cur["t"] - _prev["t"] < 30:
        await asyncio.sleep(0.6)
        _prev, cur = cur, _snapshot(enc, pid)
    prev, _prev = _prev, cur
    dt = cur["t"] - prev["t"]
    res: dict = {"busy": None, "engines": {}, "freq": None, "temp": None, "throttle": [], "cpu": None}
    if cur["cpu"] and prev["cpu"] and cur["cpu"][0] > prev["cpu"][0]:
        tot, idle = cur["cpu"][0] - prev["cpu"][0], cur["cpu"][1] - prev["cpu"][1]
        res["cpu"] = round((1 - idle / tot) * 100, 1)
    if cur["engines"] and prev["engines"] and cur["pid"] == prev["pid"] and dt > 0:
        for k, v in cur["engines"]["ns"].items():
            d = v - prev["engines"]["ns"].get(k, v)
            capacity = cur["engines"]["cap"].get(k, 1)
            res["engines"][k] = round(max(0.0, min(1.0, d / (dt * 1e9 * capacity))) * 100, 1)

    if enc["encoder"] == "nvenc":
        q = await _nvidia_query("utilization.gpu,utilization.encoder,utilization.decoder,clocks.gr,clocks.max.gr,"
                                "temperature.gpu")
        if len(q) >= 6:
            num = [float(x) if x.replace(".", "", 1).isdigit() else None for x in q]
            res.update(busy=num[0], engines={"encoder": num[1], "decoder": num[2]},
                       freq={"act": num[3], "max": num[4]}, temp=num[5])
        return res

    card = _card(enc["device"]) if enc["device"] else None
    if card:
        dev = card / "device"
        if cur["rc6"] is not None and prev["rc6"] is not None and dt > 0:  # Intel: idle residency
            idle = (cur["rc6"] - prev["rc6"]) / (dt * 1000)
            res["busy"] = round(max(0.0, min(1.0, 1 - idle)) * 100, 1)
        elif _read(dev / "gpu_busy_percent", "").isdigit():  # AMD
            res["busy"] = float(_read(dev / "gpu_busy_percent"))

        def mhz(name):
            v = _read(card / name)
            return int(v) if v and v.isdigit() else None
        if mhz("gt_act_freq_mhz") is not None:
            res["freq"] = {"act": mhz("gt_act_freq_mhz"), "max": mhz("gt_RP0_freq_mhz")}
            gt = card / "gt" / "gt0"
            res["throttle"] = [p.name.replace("throttle_reason_", "") for p in gt.glob("throttle_reason_*")
                               if p.name != "throttle_reason_status" and _read(p) == "1"]
        else:
            sclk = _read(dev / "pp_dpm_sclk", "")  # AMD: "1: 1800Mhz *"
            cur_f = re.search(r"(\d+)Mhz \*", sclk)
            all_f = [int(x) for x in re.findall(r"(\d+)Mhz", sclk)]
            if cur_f:
                res["freq"] = {"act": int(cur_f.group(1)), "max": max(all_f) if all_f else None}
            for hw in dev.glob("hwmon/hwmon*"):
                t = _read(hw / "temp1_input")
                if t and t.isdigit():
                    res["temp"] = int(t) / 1000
    if res["temp"] is None:
        for z in Path("/sys/class/thermal").glob("thermal_zone*"):
            if _read(z / "type") == "x86_pkg_temp":
                t = _read(z / "temp")
                res["temp"] = int(t) / 1000 if t and t.lstrip("-").isdigit() else None
    return res
