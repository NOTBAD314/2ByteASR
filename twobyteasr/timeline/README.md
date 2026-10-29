# timeline：時間怎麼算、編輯怎麼落地

這裡放工作台時間軸背後的資料與規則，不放畫面。滑鼠、鍵盤與繪製在 `studio/studio_timeline.py`（`WaveformTimeline`），它只發出訊號，真正改工程的是這裡的指令。

## 時間單位

| 在哪裡 | 單位 | 例子 |
| --- | --- | --- |
| 存進工程檔的時間 | **整數毫秒** | `StudioCue.start_ms / end_ms`（`projects/studio_project.py`）、片段的 `*_in_ms / *_out_ms` |
| 播放器與 seek 訊號 | 浮點秒 | `seek_requested = Signal(float)`、`playback/studio_mpv.py` 的 `MpvController.seek` |
| 播放時鐘與媒體時間對照 | 浮點毫秒 | `playback/playback_clock.py` 的 `PlaybackClock`、`media_time.MediaTimeMapping` |
| 需要精確換算時 | `Fraction`（秒） | `clip_time_mapper.project_to_source_exact`、`caption_frame_time` |
| 輸出 ASS | 百分之一秒 | `caption_frame_time.ass_frame_ms` |
| 辨識流程交進來的字幕 | 浮點秒 | 在 `projects/studio_project.py` 的 `project_from_runtime_cues` 轉成整數毫秒 |

所有會刪除或切開時間的編輯都用半開區間 `[start, end)`。

## 三種時間座標

1. **來源媒體時間**：每個素材自己的毫秒數。
2. **工程（時間軸）時間**：剪輯後時間軸上的毫秒數，播放時鐘以它為準。
3. **串流時間戳／取樣位置**：解碼器看到的 PTS 與音訊取樣索引；FLV 常見音訊從 21 ms、視訊從 998 ms 起算，所以不能直接當成來源時間。`media_time.MediaTimeMapping` 專門處理這一步，資料存在 `studio_state['media_time_mapping']`。

字幕存在哪一種時間裡，看 `project.render_settings['_cue_domain']`：

- 沒有這個欄位（舊工程）：字幕存在來源時間，畫面上顯示的是 `studio_edit_sequence.projected_cues` 投影後的結果；時間編輯要用 `map_timing_to_source` 換回來源時間。
- `'timeline'`：字幕直接存在工程時間（`studio_caption_timeline.independent_captions`）。舊工程開啟時由 `ensure_independent_captions` 一次性轉換，原始位置保存在 `studio_state['caption_timeline']` 的收據裡（`caption_source_receipts.py`）。

## 換算函式

| 要做什麼 | 用哪個 |
| --- | --- |
| 某個片段：工程時間 ↔ 來源時間（多軌播放、匯出、波形、縮圖） | `clip_time_mapper.project_to_source` / `source_to_project` / `map_project_time` |
| 主影片序列：工程時間 ↔ 來源時間、產生 mpv EDL | `studio_sequence_mapper.timeline_to_source` / `source_to_timeline` / `export_source_slices` / `write_mpv_edl` |
| 字幕顯示：依序列投影字幕 | `studio_edit_sequence.projected_cues`、`map_timing_to_source` |
| 對齊到影格 | `caption_frame_time` |

公式（`clip_time_mapper.py` 開頭）：`來源時間 = 來源入點 + (工程時間 − 時間軸入點) × 播放速率`。新程式不要自己再寫一份換算；目前仍有幾處重複實作（見 [程式碼地圖](../../docs/CODE_MAP.md) 的「還沒拆開的地方」）。

## 編輯與撤銷

- 撤銷堆疊是 `SubtitleStudioPage` 建立的一個 `QUndoStack`（上限 500），存成 `StudioSession.undo_stack`。開啟工程時會清空。
- 一次編輯的路徑：控制器或混入 `push` 一個 `QUndoCommand` → `redo()` 呼叫 `studio_commands._commit_mutation` → `projects/studio_runtime_state.py` 的交易（每個資料面向先存快照，失敗就還原、驗證、遞增版本）→ 發出 `StateDelta` → 工作台更新畫面並排程自動儲存。
- 指令分類：

  | 檔案 | 指令 |
  | --- | --- |
  | `studio_commands.py` | 字幕欄位（`SetCueFieldsCommand`，連續打字會合併）、拆分／合併／刪除／新增、區間與批次時間 |
  | `studio_edit_commands.py` | 主影片序列（V1）的剃刀、波紋、產生與還原 |
  | `studio_clip_edit.py` | 多軌片段編輯，含波紋刪除 `ripple_ranges_command` 與播放頭編輯 `playhead_edit_command` |
  | `studio_media_commands.py`、`studio_track_delete.py`、`studio_selection.py` | 素材池與多軌、刪除軌道、跨軌選取的移動／複製／刪除 |
  | `range_replace.py` | 「只重新識別這一段字幕」的整段替換（字幕、證據、字級回執、來源快照、譯文一步撤銷） |

- **Q／W**：快捷鍵定義在 `studio/shortcut_registry.py`（`trim_start` = Q、`trim_end` = W）。目前選到字幕時走 `studio/studio_cue_controller.py` 的 `trim_to_playhead` → `SetCueFieldsCommand("Adjust timing")`；沒有字幕或在影片模式時走 `studio/studio_video_flow.py` 的 `_ripple_video_to_playhead` → `studio_clip_edit.playhead_edit_command`（撤銷紀錄名稱「Q/W 波纹删除」）。
- 吸附：`studio_group_snap.snap_group_delta`（整組移動）；時間軸元件內另有 `_snap_time` 等實作。

## 不能破壞的事

- 存檔裡的時間永遠是整數毫秒，區間是 `[start, end)`。
- 播放時間只由 `PlaybackClock` 推進；其他播放器、波形、縮圖只讀不寫。
- 會改工程的動作都要經過可撤銷的指令和狀態交易，畫面元件不直接改資料。
