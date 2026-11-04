"""Small adapters for sidecar choices after an asynchronous media drop."""
from pathlib import Path
from PySide6.QtWidgets import QInputDialog
from ..i18n import tr


def offer_companion_choices(page, results):
    for result in results:
        if result.subtitle_bundle or not result.subtitle_candidates:
            if result.subtitle_error:
                page.save_state.setText(tr("媒体已导入；配套字幕需要检查：") + result.subtitle_error)
            continue
        choices = [Path(p).name for p in result.subtitle_candidates]
        selected, accepted = QInputDialog.getItem(page, tr("选择配套字幕"),
            tr("找到多份字幕，请为此素材选择一次："), choices, 0, False)
        if not accepted:
            continue
        pools = {a.asset_id: a for a in page.project.media_pool}
        clips = [c for t in page.project.video_tracks for c in t.clips
                 if Path(pools[c.asset_id].canonical_source).resolve() == Path(result.source_path).resolve()]
        if len(clips) != 1:
            page.save_state.setText(tr("同一素材有多个片段，请从链接下载窗口指定素材实例。"))
            continue
        from ..app.link_download_controller import controller_for
        controller_for(page).import_sidecar(page, result.subtitle_candidates[choices.index(selected)],
                                            result.source_path, clips[0].id)
