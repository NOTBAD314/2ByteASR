"""Browser authorization entry and task scheduling for the link controller."""
from __future__ import annotations

from ..media.link_authorization import from_browser
from ..media.link_choices import audio_formats, default_selection
from ..i18n import tr


def setup(controller, pending):
    if controller._closed or controller._browser_active or not pending:
        return
    url, mode, auth, target = pending.popleft()
    controller._browser_active = True

    def work():
        catalog = controller.engine.analyze(url, cancel=controller._browser_cancel.is_set,
                                            cookie_file=auth or "")
        return catalog, mode, auth, target

    controller._background("browser_analysis", "", work, browser_url=url, browser_mode=mode)


def enqueue(controller, result):
    catalog, mode, auth, start_context = result
    actual_mode = {"both": "both", "recognize": "video", "subtitles": "subtitles"}[mode]
    from .link_download_controller import link_preferences
    prefs = controller.dialog.preferences if controller.dialog else link_preferences()
    languages = prefs.get("languages", [])
    # Extractors may omit the video's language while providing the original
    # audio's language on the selected audio representations.
    original_audio = {row["language"] for row in audio_formats(catalog)
                      if row.get("language") and "original" in (row.get("format_note") or "").casefold()}
    if not catalog.get("language") and len(original_audio) == 1:
        catalog = dict(catalog, language=next(iter(original_audio)))
    selection = default_selection(catalog, languages, actual_mode)
    if actual_mode in {"subtitles", "both"} and catalog["tracks"] and not selection["track_ids"]:
        controller.offer_browser_choices(catalog, mode, auth)
        return None
    if actual_mode == "subtitles" and not selection["track_ids"]:
        raise ValueError(tr("这个视频没有可默认选择的原语字幕。请在下载窗口查看全部轨道。"))
    if actual_mode in {"both", "video"} and not selection["video_format"]:
        raise ValueError(tr("视频没有可下载的画质。"))
    return controller.enqueue(catalog, controller.directory(), dict(selection, destination="new",
        auto_import=(actual_mode != "subtitles" and not start_context["project_id"]
                     and start_context == controller.context()), recognize=mode == "recognize"),
        cookie_file=auth or "")


def receive(controller, request):
    if len(controller._browser_pending) >= 32:
        return False
    url = request["url"]
    try:
        auth = from_browser(url, request["cookies"]) if "cookies" in request else None
    except ValueError:
        return False
    controller._browser_pending.append((url, request["mode"], auth, controller.context()))
    setup(controller, controller._browser_pending)
    return True
