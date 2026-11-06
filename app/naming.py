"""Keeping the codec words in a file name true after a conversion.

Release names carry words like `x264`, `H.264` or `DTS-HD.MA.5.1`. After a conversion they no longer
describe the file. `new_stem` rewrites only the words for what Shrinkarr itself changed, in the style of
the source name, and never adds a word: title, year, resolution, source (BluRay, WEB-DL, Remux) and the
release group stay as they are, because Sonarr and Radarr read the quality and the group from them.
"""
import logging
import os
import re
from pathlib import Path

log = logging.getLogger("shrinkarr.naming")

_B = r"(?<![A-Za-z0-9])"  # start of a word: no letter or digit before it
_E = r"(?![A-Za-z0-9])"   # end of a word

# x264, X264, H.264, h264, x 264, AVC, XviD, DivX, VC-1, MPEG-2
VIDEO = re.compile(_B + r"(?:[xh][. ]?264|AVC|XviD|DivX|VC-?1|MPEG-?2)" + _E, re.I)

# The whole DTS word: DTS, DTS-HD, DTS-HD.MA.5.1, DTS-HD MA5_1, dtshd-ma, DTS-X, DTS-ES, DTS 7.1, ...
# `DTS.x264` and `DTS.x 264` are DTS followed by x264, not DTS:X.
DTS = re.compile(
    _B + r"DTS"
    r"(?:[-. _:]?(?:HD(?:[-. _]?(?:MA|HRA?))?|MA|X(?![-. _]?26[45])|ES))?"
    r"(?:[-. _]?[0-9][-. _][0-9](?![0-9]))?" + _E, re.I)

VIDEO_EXT = {".mkv", ".mp4", ".m4v", ".avi", ".ts", ".m2ts", ".wmv", ".mpg", ".mpeg", ".mov", ".webm"}
# Extras that belong to a video (Plex/Kodi naming), not videos of their own
_EXTRA = re.compile(r"-(?:trailer|sample|behindthescenes|deleted|featurette|interview|scene|short|other)$", re.I)


def _video(m: re.Match) -> str:
    t = m.group(0)
    low = re.sub(r"[. ]", "", t.lower())
    if low in ("x264", "h264"):
        return t[:-1] + "5"                       # x264 -> x265, H.264 -> H.265, h264 -> h265
    if low == "avc":
        return "HEVC" if t.isupper() else "Hevc" if t[0].isupper() else "hevc"
    return "X265" if t.isupper() else "x265"      # XviD, DivX, VC-1, MPEG-2: no word of the same family


def new_stem(stem: str, video: bool, dts: bool, channels: int = 6) -> str:
    """The name without extension after a conversion.

    video: the video was encoded again (to HEVC).
    dts: every DTS track became E-AC3 (none left). `channels` is the most channels of those new tracks.
    """
    out = stem
    if video:
        out = VIDEO.sub(_video, out)
    if dts:
        word = "DDP" + ("5.1" if channels > 2 else "2.0")
        out = DTS.sub(lambda m: word.lower() if m.group(0).islower() else word, out)
        out = re.sub(r"(?i)(DDP[25]\.[01])[-. _]+\1" + _E, r"\1", out)  # 'DDP5.1.DDP5.1' -> 'DDP5.1'
    return out


def is_video(p: Path) -> bool:
    return p.suffix.lower() in VIDEO_EXT and not _EXTRA.search(p.stem)


def sidecars(video: Path) -> list[Path]:
    """Files next to `video` that belong to it: `<stem>.nl.srt`, `<stem>.nfo`, `<stem>-poster.jpg`, ...

    When another video in the folder has a longer name that also fits (`Movie.mkv` and `Movie.Part.2.mkv`),
    a file belongs to the longest one.
    """
    folder, stem = video.parent, video.stem
    try:
        entries = [p for p in folder.iterdir() if p.is_file() and not p.name.startswith(".")]
    except OSError:
        return []
    owners = sorted({p.stem for p in entries if is_video(p)} | {stem}, key=len, reverse=True)
    found = []
    for p in entries:
        if p == video or is_video(p):
            continue
        owner = next((o for o in owners if p.name.startswith(o) and p.name[len(o):len(o) + 1] in (".", "-")), None)
        if owner == stem:
            found.append(p)
    return sorted(found)


def rename_sidecars(old: Path, new: Path) -> list[list[str]]:
    """Gives subtitles, .nfo and artwork of a video its new name too. Returns [[old, new], ...]."""
    done = []
    for p in sidecars(old):
        dest = new.parent / (new.stem + p.name[len(old.stem):])
        if dest.exists():
            log.warning("Not renamed, %s already exists", dest)
            continue
        try:
            os.rename(p, dest)
            done.append([str(p), str(dest)])
        except OSError as e:
            log.warning("Could not rename %s: %s", p, e)
    return done
