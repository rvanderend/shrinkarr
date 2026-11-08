"""Sonarr, Radarr and Plex: the library, covers, rescans and path mapping. Each one is optional."""
import asyncio
import logging
import time
from pathlib import Path
from urllib.parse import quote

import httpx

from . import config, db, media

log = logging.getLogger("shrinkarr.arr")

APPS = ("sonarr", "radarr")

_client: httpx.AsyncClient | None = None
_plex_client: httpx.AsyncClient | None = None


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0))
    return _client


def plex_client() -> httpx.AsyncClient:
    # Plex often runs with its own certificate on an IP address; don't let that block a LAN connection.
    global _plex_client
    if _plex_client is None:
        _plex_client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0), verify=False)
    return _plex_client


def conn(app: str, s: dict | None = None) -> tuple[str, str]:
    s = s or db.get_settings()
    return s[f"{app}_url"], s[f"{app}_api_key"]


def configured(app: str, s: dict | None = None) -> bool:
    url, key = conn(app, s)
    return bool(url and key)


def plex_configured(s: dict | None = None) -> bool:
    s = s or db.get_settings()
    return bool(s["plex_url"] and s["plex_token"])


async def api(app: str, method: str, path: str, *, url: str | None = None, key: str | None = None, **kw):
    u, k = conn(app)
    url, key = url or u, key or k
    r = await client().request(method, f"{url}/api/v3{path}", headers={"X-Api-Key": key}, **kw)
    r.raise_for_status()
    return r.json() if r.content else None


# --- path mapping ---------------------------------------------------------

def _swap(path: str, pairs: list[tuple[str, str]]) -> str | None:
    for src, dst in sorted(pairs, key=lambda p: -len(p[0])):
        src = src.rstrip("/")
        if src and (path == src or path.startswith(src + "/")):
            return (dst.rstrip("/") or "") + path[len(src):]
    return None


def _mappings() -> list[dict]:
    return [m for m in db.get_settings()["path_mappings"] if m.get("arr") and m.get("local")]


def to_local(arr_path: str) -> str:
    """Path in Sonarr/Radarr -> path in this container."""
    return _swap(arr_path, [(m["arr"], m["local"]) for m in _mappings()]) or arr_path


def to_arr(local_path: str) -> str:
    """Path in this container -> path in Sonarr/Radarr."""
    return _swap(local_path, [(m["local"], m["arr"]) for m in _mappings()]) or local_path


def to_plex(local_path: str) -> str:
    return _swap(local_path, [(m["local"], m.get("plex") or m["local"]) for m in _mappings()]) or local_path


def from_plex(plex_path: str) -> str:
    return _swap(plex_path, [(m.get("plex") or m["local"], m["local"]) for m in _mappings()]) or plex_path


# --- library ----------------------------------------------------------------

def _images(app: str, item_id: int, images: list) -> dict:
    types = {i.get("coverType") for i in images or []}
    return {t: f"/api/cover/{app}/{item_id}/{t}" for t in ("poster", "fanart") if t in types}


def _file(kind: str, arr_id: int, f: dict, label: str, season: int | None = None) -> dict:
    facts = media.file_facts(f.get("mediaInfo") or {}, int(f.get("size") or 0))
    return {
        "kind": kind,
        "arrId": arr_id,
        "fileId": f["id"],
        "path": to_local(f["path"]),
        "name": Path(f["path"]).name,
        "size": int(f.get("size") or 0),
        "quality": ((f.get("quality") or {}).get("quality") or {}).get("name", ""),
        "cutoffNotMet": bool(f.get("qualityCutoffNotMet")),
        "label": label,
        "season": season,
        **facts,
    }


class Library:
    def __init__(self):
        self.movies: dict[int, dict] = {}
        self.series: dict[int, dict] = {}
        self.roots: dict[str, list[dict]] = {"sonarr": [], "radarr": []}
        self.refreshed = 0.0
        self.error = ""
        self._lock = asyncio.Lock()

    def item(self, kind: str, item_id: int) -> dict | None:
        return (self.movies if kind == "movie" else self.series).get(item_id)

    def root_of(self, app: str, path: str) -> dict:
        best = None
        for r in self.roots.get(app, []):
            p = r["path"].rstrip("/")
            if (path == p or path.startswith(p + "/")) and (not best or len(p) > len(best["path"])):
                best = r
        return best or {"path": "", "label": ""}

    async def refresh(self):
        async with self._lock:
            s = db.get_settings()
            errors = []

            async def load(app, fn):
                if not configured(app, s):
                    return {}
                try:
                    return await fn()
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{app.capitalize()}: {type(e).__name__}: {e}")
                    log.exception("Loading %s failed", app)
                    return None

            await asyncio.gather(self._load_roots("sonarr", s), self._load_roots("radarr", s))
            movies, series = await asyncio.gather(load("radarr", self._load_movies), load("sonarr", self._load_series))
            if movies is not None:
                self.movies = movies
            if series is not None:
                self.series = series
            self.refreshed = time.time()
            self.error = "; ".join(errors)

    async def _load_roots(self, app: str, s: dict):
        if not configured(app, s):
            self.roots[app] = []
            return
        try:
            data = await api(app, "GET", "/rootfolder")
            self.roots[app] = [{"app": app, "path": r["path"].rstrip("/"),
                                "label": Path(r["path"].rstrip("/")).name or r["path"]} for r in data]
        except Exception:  # noqa: BLE001
            log.warning("Root folders of %s could not be loaded", app)

    async def refresh_item(self, kind: str, item_id: int):
        try:
            if kind == "movie":
                m = await api("radarr", "GET", f"/movie/{item_id}")
                item = self._movie(m)
                if item:
                    self.movies[item_id] = item
                else:
                    self.movies.pop(item_id, None)
            else:
                s = await api("sonarr", "GET", f"/series/{item_id}")
                self.series[item_id] = await self._series(s, asyncio.Semaphore(1))
        except Exception:  # noqa: BLE001
            log.exception("Updating %s %s failed", kind, item_id)

    def _movie(self, m: dict) -> dict | None:
        if not m.get("hasFile") or not m.get("movieFile"):
            return None
        mf = m["movieFile"]
        f = _file("movie", m["id"], mf, mf.get("quality", {}).get("quality", {}).get("name", "Movie"))
        root = self.root_of("radarr", m["path"])
        return {
            "kind": "movie", "id": m["id"], "title": m["title"], "sortTitle": m.get("sortTitle") or m["title"].lower(),
            "year": m.get("year"), "overview": m.get("overview", ""), "genres": m.get("genres", []),
            "root": root["path"], "rootLabel": root["label"], "images": _images("radarr", m["id"], m.get("images")),
            "files": [f],
        }

    async def _load_movies(self) -> dict[int, dict]:
        data = await api("radarr", "GET", "/movie")
        out = {}
        for m in data:
            item = self._movie(m)
            if item:
                out[m["id"]] = item
        return out

    async def _series(self, s: dict, sem: asyncio.Semaphore) -> dict:
        async with sem:
            files, episodes = await asyncio.gather(
                api("sonarr", "GET", "/episodefile", params={"seriesId": s["id"]}),
                api("sonarr", "GET", "/episode", params={"seriesId": s["id"]}),
            )
        by_file: dict[int, list] = {}
        for e in episodes:
            if e.get("episodeFileId"):
                by_file.setdefault(e["episodeFileId"], []).append(e)
        out_files = []
        for f in files:
            eps = sorted(by_file.get(f["id"], []), key=lambda e: e["episodeNumber"])
            season = f.get("seasonNumber", 0)
            if eps:
                nums = "-".join(f"E{e['episodeNumber']:02d}" for e in eps[:3])
                label = f"S{season:02d}{nums} · {eps[0].get('title') or ''}".strip(" ·")
            else:
                label = Path(f["relativePath"]).stem
            out_files.append(_file("episode", s["id"], f, label, season))
        out_files.sort(key=lambda x: (x["season"] or 0, x["label"]))
        root = self.root_of("sonarr", s["path"])
        return {
            "kind": "series", "id": s["id"], "title": s["title"],
            "sortTitle": s.get("sortTitle") or s["title"].lower(), "year": s.get("year"),
            "overview": s.get("overview", ""), "genres": s.get("genres", []), "network": s.get("network", ""),
            "root": root["path"], "rootLabel": root["label"], "images": _images("sonarr", s["id"], s.get("images")),
            "files": out_files,
        }

    async def _load_series(self) -> dict[int, dict]:
        data = await api("sonarr", "GET", "/series")
        sem = asyncio.Semaphore(6)
        with_files = [s for s in data if (s.get("statistics") or {}).get("episodeFileCount")]
        items = await asyncio.gather(*(self._series(s, sem) for s in with_files))
        return {i["id"]: i for i in items}


LIB = Library()


async def resolve_file(kind: str, file_id: int) -> dict | None:
    """Current data of a file (the path can change through an upgrade)."""
    app, ep = ("radarr", "moviefile") if kind == "movie" else ("sonarr", "episodefile")
    try:
        return await api(app, "GET", f"/{ep}/{file_id}")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return None
        raise


async def rescan(kind: str, arr_id: int) -> dict | None:
    if kind == "movie":
        return await api("radarr", "POST", "/command", json={"name": "RescanMovie", "movieId": arr_id})
    return await api("sonarr", "POST", "/command", json={"name": "RescanSeries", "seriesId": arr_id})


async def wait_command(app: str, cmd: dict | None, timeout: float = 300) -> str:
    """Waits until a Sonarr/Radarr command has finished; returns its status ('completed', 'failed', ...)."""
    if not cmd or "id" not in cmd:
        return "unknown"
    end = time.monotonic() + timeout
    status = cmd.get("status") or "queued"
    while status in ("queued", "started") and time.monotonic() < end:
        await asyncio.sleep(2)
        status = (await api(app, "GET", f"/command/{cmd['id']}")).get("status") or "unknown"
    return status


async def find_file(kind: str, arr_id: int, local_path: str) -> int | None:
    """Id of the file record in Sonarr/Radarr for this path (an id stored earlier can be outdated)."""
    path = to_arr(local_path)
    if kind == "movie":
        files = await api("radarr", "GET", "/moviefile", params={"movieId": arr_id})
    else:
        files = await api("sonarr", "GET", "/episodefile", params={"seriesId": arr_id})
    return next((f["id"] for f in files or [] if f.get("path") == path), None)


async def file_state(kind: str, arr_id: int, file_id: int) -> dict | None:
    """What Sonarr/Radarr know about a file before Shrinkarr gives it a new path: the file record and
    which movie or episodes are monitored. None when that can't be read (then only a rescan follows)."""
    try:
        f = await resolve_file(kind, file_id)
        if not f:
            return None
        if kind == "movie":
            movie = await api("radarr", "GET", f"/movie/{arr_id}")
            return {"file": f, "monitored": {arr_id: bool(movie.get("monitored"))}}
        eps = await api("sonarr", "GET", "/episode", params={"episodeFileId": file_id})
        return {"file": f, "monitored": {e["id"]: bool(e.get("monitored")) for e in eps}}
    except Exception as e:  # noqa: BLE001
        log.warning("Could not read file %s in %s: %s", file_id, "Radarr" if kind == "movie" else "Sonarr", e)
        return None


async def repoint(kind: str, arr_id: int, state: dict, new_local: str) -> int | None:
    """Tells Sonarr/Radarr that `new_local` is now the file of this movie or these episodes.

    After a new name, a rescan alone first drops the old file record as 'missing from disk' while the
    movie still points to it, and Radarr then unmonitors the movie ('Unmonitor deleted movies'). So the
    new file is imported first, with the quality, languages and release group of the old record. It is
    already in the movie or series folder, so Sonarr/Radarr treat it as an existing file: nothing is moved
    and no download or upgrade notifications go out. The rescan that follows cleans up the old record,
    which nothing points to any more. Returns the id of the new file record, or None.
    """
    app = "radarr" if kind == "movie" else "sonarr"
    old = state["file"]
    path = to_arr(new_local)
    entry = {"path": path, "quality": old["quality"], "languages": old.get("languages") or [],
             "releaseGroup": old.get("releaseGroup") or "", "indexerFlags": old.get("indexerFlags") or 0}
    if kind == "movie":
        entry["movieId"] = arr_id
    else:
        entry.update(seriesId=arr_id, episodeIds=list(state["monitored"]))
        if not entry["episodeIds"]:
            return None
    cmd = await api(app, "POST", "/command", json={"name": "ManualImport", "importMode": "auto", "files": [entry]})
    status = await wait_command(app, cmd)
    if status != "completed":
        log.warning("Import of %s in %s ended as %s", path, app, status)
    return await find_file(kind, arr_id, new_local)


async def restore_monitored(kind: str, state: dict) -> int:
    """Monitors again what was monitored before (a safety net if the import didn't take). Returns how many."""
    ids = [i for i, on in state["monitored"].items() if on]
    if not ids:
        return 0
    if kind == "movie":
        now = {m: bool((await api("radarr", "GET", f"/movie/{m}")).get("monitored")) for m in ids}
        lost = [m for m, on in now.items() if not on]
        if lost:
            await api("radarr", "PUT", "/movie/editor", json={"movieIds": lost, "monitored": True})
    else:
        lost = [i for i in ids if not (await api("sonarr", "GET", f"/episode/{i}")).get("monitored")]
        if lost:
            await api("sonarr", "PUT", "/episode/monitor", json={"episodeIds": lost, "monitored": True})
    return len(lost)


async def _grab_of(kind: str, arr_id: int, file_id: int) -> int | None:
    """History id of the grab that brought this file in, found through its import (same download id)."""
    if kind == "movie":
        hist = await api("radarr", "GET", "/history/movie", params={"movieId": arr_id})
    else:
        hist = await api("sonarr", "GET", "/history/series", params={"seriesId": arr_id})
    imp = next((e for e in hist or [] if e.get("eventType") == "downloadFolderImported" and e.get("downloadId")
                and str((e.get("data") or {}).get("fileId")) == str(file_id)), None)
    if not imp:
        return None
    grab = next((e for e in hist if e.get("eventType") == "grabbed" and e.get("downloadId") == imp["downloadId"]), None)
    return grab["id"] if grab else None


async def redownload(kind: str, arr_id: int, file_id: int) -> bool:
    """Deletes a (damaged) file in Sonarr/Radarr and searches for it again.

    The release it came from is marked as failed first, which puts it on the blocklist: otherwise
    the search often grabs the same broken release again. That only works when the file came in
    through a download (not a manual copy); returns whether it was blocklisted.
    The movie or episodes are monitored again first: deleting a file can unmonitor them, and
    a later automatic search should also pick them up. A file that is already gone (a second try
    after a failed search) is fine.
    """
    app = "radarr" if kind == "movie" else "sonarr"

    async def delete(path):
        try:
            await api(app, "DELETE", path)
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 404:
                raise

    blocklisted = False
    try:
        grab = await _grab_of(kind, arr_id, file_id)
        if grab:
            await api(app, "POST", f"/history/failed/{grab}")
            blocklisted = True
    except httpx.HTTPError:
        log.warning("Blocklisting the release of %s file %s failed", app, file_id, exc_info=True)

    if kind == "movie":
        await delete(f"/moviefile/{file_id}")
        await api("radarr", "PUT", "/movie/editor", json={"movieIds": [arr_id], "monitored": True})
        await api("radarr", "POST", "/command", json={"name": "MoviesSearch", "movieIds": [arr_id]})
    else:
        ids = [e["id"] for e in await api("sonarr", "GET", "/episode", params={"episodeFileId": file_id})]
        await delete(f"/episodefile/{file_id}")
        if ids:
            await api("sonarr", "PUT", "/episode/monitor", json={"episodeIds": ids, "monitored": True})
            await api("sonarr", "POST", "/command", json={"name": "EpisodeSearch", "episodeIds": ids})
    return blocklisted


# --- covers -----------------------------------------------------------------

async def cover(app: str, item_id: int, kind: str) -> Path | None:
    size = "-500" if kind == "poster" else ""
    cache = config.DATA_DIR / "covers" / f"{app}-{item_id}-{kind}.jpg"
    if cache.exists() and time.time() - cache.stat().st_mtime < 7 * 86400:
        return cache
    if not configured(app):
        return cache if cache.exists() else None
    url, key = conn(app)
    try:
        r = await client().get(f"{url}/api/v3/mediacover/{item_id}/{kind}{size}.jpg", headers={"X-Api-Key": key})
        if r.status_code == 200 and r.content:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(r.content)
            return cache
    except httpx.HTTPError:
        log.warning("Cover %s/%s/%s could not be loaded", app, item_id, kind)
    return cache if cache.exists() else None


# --- Plex -------------------------------------------------------------------

_plex_sections: dict[str, list[tuple[str, str]]] = {}


async def plex_sections(url: str | None = None, token: str | None = None) -> list[dict]:
    s = db.get_settings()
    url, token = url or s["plex_url"], token or s["plex_token"]
    r = await plex_client().get(f"{url}/library/sections", headers={"X-Plex-Token": token, "Accept": "application/json"})
    r.raise_for_status()
    out = []
    for d in r.json()["MediaContainer"].get("Directory", []):
        out.append({"key": d["key"], "title": d.get("title", ""), "type": d.get("type", ""),
                    "paths": [loc["path"].rstrip("/") for loc in d.get("Location", [])]})
    return out


def in_plex(plex_path: str, library_paths: list[str]) -> bool:
    """True if a Plex library holds this path, or lies below it (a root folder with several libraries)."""
    plex_path = plex_path.rstrip("/")
    for p in library_paths:
        p = p.rstrip("/")
        if plex_path == p or plex_path.startswith(p + "/") or p.startswith(plex_path + "/"):
            return True
    return False


async def plex_refresh(local_path: str) -> bool:
    """Let Plex rescan only the folder of the file. False if Plex isn't set up or no library holds the folder."""
    s = db.get_settings()
    if not plex_configured(s):
        return False
    url = s["plex_url"]
    if url not in _plex_sections:
        _plex_sections[url] = [(p + "/", d["key"]) for d in await plex_sections() for p in d["paths"]]
    folder = str(Path(to_plex(local_path)).parent)
    for prefix, key in sorted(_plex_sections[url], key=lambda x: -len(x[0])):
        if folder.startswith(prefix) or folder + "/" == prefix:
            r = await plex_client().get(f"{url}/library/sections/{key}/refresh?path={quote(folder)}",
                                        headers={"X-Plex-Token": s["plex_token"]})
            r.raise_for_status()
            return True
    log.warning("No Plex library holds %s; check the Plex path in the path mappings", folder)
    return False


async def plex_playing() -> set[str] | None:
    """Local paths of files that are being played in Plex right now (None if Plex can't be reached)."""
    s = db.get_settings()
    if not plex_configured(s):
        return None
    try:
        r = await plex_client().get(f"{s['plex_url']}/status/sessions",
                                    headers={"X-Plex-Token": s["plex_token"], "Accept": "application/json"})
        r.raise_for_status()
    except httpx.HTTPError:
        return None
    paths = set()
    for m in r.json()["MediaContainer"].get("Metadata", []):
        for me in m.get("Media", []):
            for part in me.get("Part", []):
                if part.get("file"):
                    paths.add(from_plex(part["file"]))
    return paths


async def imports_since(app: str, since: str) -> list[dict]:
    """Imports (downloadFolderImported) since an ISO timestamp, oldest first."""
    data = await api(app, "GET", "/history/since", params={"date": since, "eventType": 3})
    out = []
    for e in data or []:
        path = (e.get("data") or {}).get("importedPath")
        arr_id = e.get("seriesId") if app == "sonarr" else e.get("movieId")
        if path and arr_id:
            out.append({"arr_id": arr_id, "path": to_local(path), "date": e.get("date")})
    return sorted(out, key=lambda x: x["date"] or "")


# --- tests and health -------------------------------------------------------

async def test_arr(app: str, url: str, key: str) -> dict:
    url = url.rstrip("/")
    try:
        st = await api(app, "GET", "/system/status", url=url, key=key)
        roots = await api(app, "GET", "/rootfolder", url=url, key=key)
        return {"ok": True, "version": st.get("version"), "roots": [r["path"].rstrip("/") for r in roots]}
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        return {"ok": False, "error": "401: API key?" if code == 401 else f"HTTP {code}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


async def test_plex(url: str, token: str) -> dict:
    url = url.rstrip("/")
    try:
        r = await plex_client().get(f"{url}/identity", headers={"X-Plex-Token": token, "Accept": "application/json"})
        r.raise_for_status()
        version = r.json()["MediaContainer"].get("version")
        sections = await plex_sections(url, token)
        return {"ok": True, "version": version, "sections": sections}
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        return {"ok": False, "error": "401: token?" if code == 401 else f"HTTP {code}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


async def health() -> dict:
    s = db.get_settings()

    async def check(name, coro):
        if coro is None:
            return name, None
        try:
            await coro
            return name, True
        except Exception:  # noqa: BLE001
            return name, False

    async def plex():
        r = await plex_client().get(f"{s['plex_url']}/identity", headers={"X-Plex-Token": s["plex_token"]})
        r.raise_for_status()

    res = await asyncio.gather(
        check("sonarr", api("sonarr", "GET", "/system/status") if configured("sonarr", s) else None),
        check("radarr", api("radarr", "GET", "/system/status") if configured("radarr", s) else None),
        check("plex", plex() if plex_configured(s) else None))
    return dict(res)
