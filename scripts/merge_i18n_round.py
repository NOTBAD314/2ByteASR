"""Merge round-2026-09-19 translation batches into i18n tables.

Inputs: tmp/i18n-out1.json, tmp/i18n-out2.json ({zh: {en, ja}}) plus
round-specific additions defined here (new strings introduced this round).
Output: printed count summary; tables updated via _ROUND_2026_09_19 in
i18n.py (generated block written to twobyteasr/i18n_round_20260919.py).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ROUND_ADDITIONS: dict[str, dict[str, str]] = {
    # 本轮新增 UI 文案（方案独立轮 + 进工程门 + 保存状态）
    "未保存的方案修改": {"en": "Unsaved profile changes", "ja": "未保存のプロファイル変更"},
    "方案“{name}”有未保存的识别参数修改。": {
        "en": "Profile \"{name}\" has unsaved recognition changes.",
        "ja": "プロファイル「{name}」に未保存の認識設定変更があります。"},
    "保存到当前方案后切换，或放弃修改。": {
        "en": "Save into the current profile before switching, or discard.",
        "ja": "現在のプロファイルに保存して切替、または変更を破棄。"},
    "保存并切换": {"en": "Save & switch", "ja": "保存して切替"},
    "放弃修改": {"en": "Discard changes", "ja": "変更を破棄"},
    "当前识别参数修改尚未保存为方案，切换后将按目标方案恢复。": {
        "en": "Current recognition changes are not saved as a profile; switching will restore the target profile.",
        "ja": "現在の認識設定変更はプロファイル未保存です。切替後は対象プロファイルの設定に戻ります。"},
    "放弃当前修改并切换，或取消。": {
        "en": "Discard current changes and switch, or cancel.",
        "ja": "現在の変更を破棄して切替、またはキャンセル。"},
    "已应用：": {"en": "Applied: ", "ja": "適用："},
    "已更新方案：": {"en": "Updated profile: ", "ja": "プロファイル更新："},
    "自定义方案：当前配置未保存到方案": {
        "en": "Custom: current configuration is not saved as a profile",
        "ja": "カスタム：現在の設定はプロファイル未保存"},
    "方案已删除；当前配置仍保留。": {
        "en": "Profile deleted; current configuration kept.",
        "ja": "プロファイルを削除しました。現在の設定は保持されます。"},
    "有未保存的识别后端修改": {
        "en": "Unsaved recognition backend changes", "ja": "未保存の認識バックエンド変更"},
    "配置已保存；运行前还需填写：": {
        "en": "Saved; still required before running: ", "ja": "保存済み。実行前に必要："},
    "识别后端与密钥已保存": {
        "en": "Recognition backend & keys saved", "ja": "認識バックエンドとキーを保存しました"},
    "AI 配置与密钥已保存，重启后仍会保留": {
        "en": "AI config & keys saved; kept across restarts",
        "ja": "AI設定とキーを保存しました（再起動後も保持）"},
    "已配置 · 未验证": {"en": "Configured · unverified", "ja": "設定済み・未検証"},
    # 就绪门（含本轮新增切块阶段）
    "准备工作台": {"en": "Preparing workspace", "ja": "ワークスペース準備中"},
    "读取工程": {"en": "Loading project", "ja": "プロジェクト読込"},
    "建立时间轴": {"en": "Building timeline", "ja": "タイムライン構築"},
    "准备播放器": {"en": "Preparing player", "ja": "プレイヤー準備"},
    "准备音频": {"en": "Preparing audio", "ja": "オーディオ準備"},
    "准备字幕": {"en": "Preparing subtitles", "ja": "字幕準備"},
    "首屏绘制": {"en": "First paint", "ja": "初回描画"},
    "恢复界面布局": {"en": "Restoring layout", "ja": "レイアウト復元"},
    "恢复播放位置": {"en": "Restoring playhead", "ja": "再生位置復元"},
    "恢复工作区": {"en": "Restoring workspace", "ja": "作業領域復元"},
    "重试": {"en": "Retry", "ja": "再試行"},
    "返回主页": {"en": "Back to home", "ja": "ホームへ戻る"},
    "准备超时；请检查素材和播放器状态。": {
        "en": "Timed out; check media and player status.",
        "ja": "準備がタイムアウトしました。素材とプレイヤー状態を確認してください。"},
    "工程未能打开": {"en": "Project failed to open", "ja": "プロジェクトを開けませんでした"},
    # 保存状态（studio）
    "已保存": {"en": "Saved", "ja": "保存済み"},
    "未保存": {"en": "Unsaved", "ja": "未保存"},
    "正在自动保存…": {"en": "Autosaving…", "ja": "自動保存中…"},
    "已自动保存 · ": {"en": "Autosaved · ", "ja": "自動保存済み・"},
    "自动保存失败": {"en": "Autosave failed", "ja": "自動保存失敗"},
    "未打开项目": {"en": "No project open", "ja": "プロジェクト未開"},
    "已恢复自动保存（尚未保存）": {
        "en": "Autosave recovered (not saved yet)", "ja": "自動保存を復元（未保存）"},
    "媒体加载失败 · 工程仍已打开": {
        "en": "Media failed to load · project still open",
        "ja": "メディア読込失敗・プロジェクトは開いています"},
    "空白工程 · 拖入视频或音频": {
        "en": "Empty project · drag video or audio in", "ja": "空プロジェクト・動画/音声をドロップ"},
    "素材离线 · 自动保存已恢复": {
        "en": "Media offline · autosave recovered", "ja": "メディアオフライン・自動保存復元済み"},
    "素材离线": {"en": "Media offline", "ja": "メディアオフライン"},
    "使用链条按钮重新定位源媒体，工程字幕仍可编辑。": {
        "en": "Use the link button to relocate source media; subtitles stay editable.",
        "ja": "リンクボタンでソースメディアを再指定できます。字幕は編集可能です。"},
    "把媒体拖到预览区即可开始剪辑。": {
        "en": "Drag media into the preview to start editing.",
        "ja": "プレビューにメディアをドロップすると編集開始。"},
}

PLACEHOLDER = re.compile(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}|%[sd]")


def _check_placeholders(zh: str, value: str) -> str:
    want = sorted(PLACEHOLDER.findall(zh))
    got = sorted(PLACEHOLDER.findall(value))
    return "" if want == got else f"placeholder mismatch zh={want} out={got}"


def main() -> int:
    merged: dict[str, dict[str, str]] = {}
    problems: list[str] = []
    for name in ("i18n-out1.json", "i18n-out2.json"):
        path = ROOT / "tmp" / name
        if not path.exists():
            problems.append(f"missing input {name}")
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for zh, pair in data.items():
            if not isinstance(pair, dict):
                continue
            en, ja = str(pair.get("en", "")).strip(), str(pair.get("ja", "")).strip()
            if not en or not ja or en == zh and zh_has_cjk(zh):
                continue
            merged[zh] = {"en": en, "ja": ja}
    merged.update(ROUND_ADDITIONS)

    # 占位符一致性
    for zh, pair in merged.items():
        for lang in ("en", "ja"):
            issue = _check_placeholders(zh, pair[lang])
            if issue:
                problems.append(f"[{lang}] {zh[:40]}: {issue}")

    out_path = ROOT / "twobyteasr" / "i18n_round_20260919.py"
    lines = [
        '"""2026-09-19 i18n 补齐轮生成的翻译块（脚本 merge_i18n_round.py 产出）。"""',
        "",
        "ROUND_2026_09_19: dict[str, dict[str, str]] = {",
    ]
    for zh in sorted(merged):
        en = merged[zh]["en"].replace("\\", "\\\\").replace('"', '\\"')
        ja = merged[zh]["ja"].replace("\\", "\\\\").replace('"', '\\"')
        key = zh.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f"    {key!r}: {{'en': {en!r}, 'ja': {ja!r}}},")
    lines.append("}")
    lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"merged entries: {len(merged)}; problems: {len(problems)}")
    for problem in problems[:20]:
        print("  !", problem)
    print(f"written: {out_path}")
    return 1 if problems else 0


def zh_has_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


if __name__ == "__main__":
    raise SystemExit(main())
