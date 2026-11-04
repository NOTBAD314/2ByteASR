"""Voiceprint registry access for the host-identification stage."""

import json


def load_host_voiceprint_registry():
    """Load enrolled ECAPA prototypes without exposing sample audio."""
    import subtitle_core as core

    path = core.HOST_VOICEPRINT_REGISTRY_PATH
    try:
        with open(path, "r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, ValueError, TypeError):
        return {"schema": 1, "hosts": [], "path": path}
    hosts = []
    for item in payload.get("hosts") or []:
        if not isinstance(item, dict):
            continue
        embedding = item.get("embedding") or []
        if not embedding:
            continue
        hosts.append(
            {
                "id": str(item.get("id") or item.get("name") or ""),
                "name": str(item.get("name") or item.get("id") or ""),
                "label": str(item.get("label") or ""),
                "embedding": [float(value) for value in embedding],
                "updated": str(item.get("updated") or ""),
            }
        )
    return {"schema": int(payload.get("schema") or 1), "hosts": hosts, "path": path}


def host_voiceprint_status_summary():
    registry = load_host_voiceprint_registry()
    hosts = registry.get("hosts") or []
    if not hosts:
        import subtitle_core as core

        return f"未注册主播声纹（可运行 register_host_voiceprint.py，目录 {core.HOST_VOICEPRINT_DIR}）"
    names = "、".join(item.get("name") or item.get("id") or "?" for item in hosts)
    return f"已注册 {len(hosts)} 位主播声纹：{names}"
