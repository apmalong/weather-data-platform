"""Downloads from NOAA with retries and a content fingerprint per file.

NOAA's Last-Modified header can't be trusted to mean "content changed": the retired CA0... station
files show yesterday's date although their data stopped in 2024. So every file is fingerprinted
(SHA-256) and compared with the last successful download; an unchanged file is skipped downstream.
"""
import gzip
import hashlib
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from wx import ops

USER_AGENT = "weather-data-platform (github.com/apmalong/weather-data-platform)"


@dataclass
class Download:
    url: str
    path: Path
    sha256: str
    changed: bool
    bytes: int


def _get(url: str, attempts: int = 4, timeout: int = 60) -> tuple[int, bytes]:
    for attempt in range(1, attempts + 1):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            if exc.code < 500 or attempt == attempts:  # 404 won't fix itself
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == attempts:
                raise
        time.sleep(2 ** attempt)
    raise AssertionError("unreachable")


def download(conn, run_id: str, url: str, path: Path) -> Download:
    """Fetch url into path, verify it, and record the download in ops.downloads."""
    started = time.time()
    previous = conn.execute("""select sha256 from ops.downloads where url = ? and error is null
                               order by downloaded_at desc limit 1""", [url]).fetchone()
    try:
        status, body = _get(url)
        if not body:
            raise ValueError("empty response")
        if path.suffix == ".gz":
            gzip.decompress(body)  # a truncated or corrupt archive fails here, not in the loader
        sha256 = hashlib.sha256(body).hexdigest()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    except Exception as exc:
        conn.execute("insert into ops.downloads values (?, ?, ?, ?, null, null, null, ?, ?, ?)",
                     [run_id, url, str(path), getattr(exc, "code", None), time.time() - started,
                      f"{type(exc).__name__}: {exc}"[:500], ops.now()])
        raise
    changed = previous is None or previous[0] != sha256
    conn.execute("insert into ops.downloads values (?, ?, ?, ?, ?, ?, ?, ?, null, ?)",
                 [run_id, url, str(path), status, len(body), sha256, changed, time.time() - started, ops.now()])
    return Download(url, path, sha256, changed, len(body))
