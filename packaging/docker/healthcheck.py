"""Check both the web gateway and the actual desktop process."""
import urllib.request
import urllib.error
import psutil
try:
    with urllib.request.urlopen("http://127.0.0.1:3000/", timeout=3) as response:
        assert response.status == 200
except urllib.error.HTTPError as error:
    if error.code != 401:
        raise
assert any(
    "twobyteasr.container.launch" in (p.info.get("cmdline") or [])
    for p in psutil.process_iter(["cmdline"])
), "2ByteASR desktop process is not running"
