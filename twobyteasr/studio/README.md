# studio：工作台畫面

這裡是「兔白字幕 Studio」（工作台）的畫面層：頁面、面板、時間軸元件、影片畫布與快捷鍵。工程資料在 `projects/`，時間換算與可撤銷的編輯指令在 `timeline/`，播放器與時鐘在 `playback/`。

## 頁面怎麼組成

`studio_ui.SubtitleStudioPage` 是整個工作台頁面。主視窗第一次用到時才建立（`app/ui.py` 的 `MainWindow.studio_page` 屬性），啟動後約 2.5 秒會先在背景 import 這個模組。

頁面本身持有四個物件：

| 物件 | 檔案 | 負責 |
| --- | --- | --- |
| `StudioSession` | `projects/studio_session.py` | 目前的工程、撤銷堆疊、選取 |
| `StudioProjectController` | `projects/studio_project_controller.py` | 開啟、儲存、恢復、關閉工程 |
| `StudioCueController` | `studio_cue_controller.py` | 字幕選取與修改、Q／W、接收狀態變化並排程自動儲存 |
| `StudioStyleController` | `caption_style/studio_style_controller.py` | 字幕樣式與動效 |

畫面元件由 `studio_workspace.StudioWorkspaceBuilder` 建立並接好訊號（時間軸的剃刀、時間編輯等訊號在 `build()` 裡連到控制器）。

頁面另外由 13 個混入（mixin）分工，每個檔案負責一塊功能：

| 混入 | 檔案 | 負責 |
| --- | --- | --- |
| `StudioHubMixin` | `studio_hub.py` | 工程庫（專案列表）與偏好設定 |
| `StudioProjectFlowMixin` | `studio_project_flow.py` | 開啟／切換／關閉工程、拖入檔案 |
| `StudioMediaFlowMixin` | `studio_media_flow.py` | 匯入素材、探測、匯入字幕、波形、重新辨識 |
| `StudioVideoFlowMixin` | `studio_video_flow.py` | 影片軌、變形、多軌預覽、自動剪氣口 |
| `StudioPlaybackFlowMixin` | `studio_playback_flow.py` | 播放、暫停、seek、音量與速度 |
| `StudioEditAssemblyMixin` | `studio_edit_assembly.py` | 入點／出點、標記、精華候選 |
| `StudioCanvasEditMixin` | `studio_canvas_edit.py` | 在畫面上直接編輯字幕 |
| `StudioStylePanelMixin` | `caption_style/studio_style_panel.py` | 樣式檢視器 |
| `StudioAssFlowMixin` | `studio_ass_flow.py` | ASS 預覽與「導出字幕」對話框 |
| `StudioAdvancedFlowMixin` | `studio_advanced_flow.py` | 進階 LIVE 預覽 |
| `StudioAIFlowMixin` | `studio_ai_flow.py` | AI 字幕設計面板 |
| `StudioReviewMixin` | `studio_review_ui.py` | 審核（品質檢查結果）介面 |
| `StudioSentenceRefineMixin` | `studio_sentence_refine_ui.py` | AI 斷句／句內節奏 |

## 常改的地方

| 想改 | 從哪裡開始 |
| --- | --- |
| 時間軸的外觀、滑鼠與鍵盤行為 | `studio_timeline.py` 的 `WaveformTimeline`（`paintEvent`、`mousePressEvent` 等）；軌道繪製在 `studio_video_track.py`、`studio_track_header.py` |
| 字幕列表 | `studio_cue_table.py` |
| 影片畫面與字幕疊加 | `studio_video_canvas.py` 的 `MpvCanvas`（也持有播放時鐘） |
| 快捷鍵 | 定義在 `shortcut_registry.py`，派送在 `studio_ui.py` 的 `_dispatch_shortcut_sequence`，Windows 原生按鍵過濾在 `studio_shortcuts.py` |
| 工具列排版 | `studio_toolbar_layout.py` |
| 尋找／取代、文字整理 | `studio_find_replace.py`、`studio_text_tools.py` |
| 開啟工程後的「就緒」等待與首幀 | `studio_readiness.py` |

## 不能破壞的事

- 畫面元件只發訊號，修改工程一律經過 `timeline/` 的可撤銷指令。
- 播放時間只來自 `PlaybackClock`；不要在畫面裡另存一份播放位置。
- 關閉頁面要走 `begin_close_page` 的流程（先停音訊、分離播放器，再由背景執行緒寫完自動儲存並關閉 mpv），不要直接結束程式。
