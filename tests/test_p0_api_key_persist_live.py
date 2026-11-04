"""Live P0 acceptance test for API Key persistence.

This exercises the exact paths used by the running GUI:
- EndpointEditor / ASR panel use read_api_key(provider, base_url)
- Save uses save_api_key_for(provider, base_url, key)
- Provider-scoped DPAPI storage (secrets.dat)
- Model switch inside same provider keeps key (no wipe)
- Restart = new process reading the file still sees the key
- Different provider/url scope does not leak the key
"""

import sys
import tempfile
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from twobyteasr.providers.llm_config import save_api_key_for, read_api_key
import twobyteasr.providers.llm_config as lc


def main():
    # Isolate secrets so we don't touch the user's real secrets.dat
    tmp = Path(tempfile.mkdtemp(prefix="2b_apikey_p0_"))
    secrets_file = tmp / "secrets.dat"

    def test_secrets_path() -> Path:
        secrets_file.parent.mkdir(parents=True, exist_ok=True)
        return secrets_file

    lc.secrets_path = test_secrets_path

    prov = "custom"
    base = "https://api.deepseek.com"
    key = "sk-p0test-ABCDEF1234567890"

    print("=== P0 STEP 1: Save key via provider+base (as UI save does) ===")
    save_api_key_for(prov, base, key)
    k, src = read_api_key(prov, base)
    print(f"Read after save: present={bool(k)} source={src}")
    assert k == key, "Save/read immediate failed"

    print("=== P0 STEP 2: Switch 'model' inside same provider (simulates EndpointEditor/ASR model change) ===")
    # In UI: provider and base_url stay; only the model lineedit text changes.
    # read_api_key must still return the same key without the caller clearing it.
    k2, src2 = read_api_key(prov, base)
    print(f"After model switch read: present={bool(k2)}")
    assert k2 == key, "Key lost when switching models in same provider scope"

    print("=== P0 STEP 3: Restart simulation (new python process reads DPAPI file) ===")
    # Spawn a fresh interpreter like restarting the app.
    code = (
        "import sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, r'" + str(ROOT).replace("\\", "/") + "')\n"
        "import twobyteasr.providers.llm_config as lc\n"
        "lc.secrets_path = lambda: Path(r'" + str(secrets_file.resolve()).replace("\\", "/") + "')\n"
        "from twobyteasr.providers.llm_config import read_api_key\n"
        "k, src = read_api_key('custom', 'https://api.deepseek.com')\n"
        "print('RESTART_READ:', bool(k), src)\n"
        "print('KEY_HEAD:', (k[:8] if k else ''))\n"
    )
    py = str((ROOT / ".venv-main" / "Scripts" / "python.exe").resolve())
    proc = subprocess.run([py, "-c", code], capture_output=True, text=True, cwd=str(ROOT))
    print("CHILD_STDOUT:", proc.stdout.strip())
    print("CHILD_STDERR:", proc.stderr.strip())
    assert "RESTART_READ: True" in (proc.stdout + proc.stderr), "Restart read from DPAPI file failed"

    print("=== P0 STEP 4: Different provider/url scope must not see the key ===")
    k3, _ = read_api_key("dashscope", "https://dashscope.aliyuncs.com")
    print(f"Different scope present={bool(k3)}")
    assert not k3, "Key leaked across different provider/endpoint scope"

    print("=== P0 STEP 5: Switch back to original scope still has key ===")
    k4, _ = read_api_key(prov, base)
    print(f"Back to original scope present={bool(k4)}")
    assert k4 == key

    print("API_KEY_PERSIST_LIVE_TEST: PASS")


def test_api_key_persistence(monkeypatch):
    # No tests were previously collected: the checks only ran as a script.
    # A provider ENV fixture must not masquerade as cross-scope secret leakage.
    monkeypatch.delenv('DASHSCOPE_API_KEY',raising=False)
    main()


if __name__ == "__main__":
    main()
