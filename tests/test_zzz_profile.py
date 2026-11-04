import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def test_zzz_profile_has_character_terms():
    data = json.loads((ROOT / "game_profiles.json").read_text(encoding="utf-8"))
    terms = data["profiles"]["绝区零"]["terms"]
    names = {item["canonical"] for item in terms}
    for required in ("绝区零", "安比", "妮可", "朱鸢", "莱卡恩", "青衣", "猫又"):
        assert required in names
    assert len(terms) >= 40
