# twobyteasr 套件地圖

2026-10-15 起，`twobyteasr/` 從一個平鋪約 700 個模組的資料夾，改成按功能分的子套件。檔名大多沒變，只是換了資料夾；舊名稱 → 新位置的完整對照在 [`scripts/module_moves.json`](../scripts/module_moves.json)，用法說明在 [程式碼地圖](../docs/CODE_MAP.md)。

想改某個功能，先看 [程式碼地圖](../docs/CODE_MAP.md)；想了解整體怎麼運作，看 [架構導覽](../ARCHITECTURE.md)。

## 子套件一覽

| 資料夾 | 放什麼 | 從哪裡開始讀 |
| --- | --- | --- |
| `app/` | 主視窗與程式外殼：首頁、進度頁、完成頁、新手教學、設定對話框、更新、單一實例 | `ui.py` 的 `run_desktop_app`、`MainWindow` |
| `recognition/` | 辨識任務：佇列入口、流程協調、辨識方案、結果與歷史、呼叫本機模型 worker、說話人 | `service.py` 的 `run_media_queue` |
| `providers/` | 外部 AI 與雲端服務：文字 AI（LLM）、雲端語音辨識、CLI 供應商、端點與金鑰、請求與診斷 | `ai_providers.py`、`llm_config.py`、`cloud_api_worker.py` |
| `glossary/` | 詞庫（術語庫）：資料、匯入、查詢與啟用、建庫與學習、詞庫校對 | `terminology.py`（執行時的詞庫快照與替換）、`glossary_proofread.py`（校對頁） |
| `subtitle_rules/` | 辨識後整理字幕條的規則：斷句、校對、標點、數字、清理、翻譯、字幕時長、品質檢查 | `grouping.py`、`polishing.py`、`text_rules.py`、`timing.py` |
| `projects/` | 工程（`.2byteproj`）：資料模型、開啟／儲存／自動儲存／恢復、工程庫與最近工程 | `studio_project.py`、`studio_project_controller.py` |
| `timeline/` | 時間軸的資料與規則：時間換算、剪輯序列、可撤銷的編輯指令、選取與吸附 | [timeline/README.md](timeline/README.md) |
| `studio/` | 工作台畫面：`SubtitleStudioPage` 與它的分工混入、時間軸元件、影片畫布、面板、快捷鍵 | [studio/README.md](studio/README.md) |
| `playback/` | 工作台播放：mpv 程序、單一播放時鐘、音訊引擎、視訊解碼與多軌合成 | `playback_clock.py`、`studio_mpv.py` |
| `media/` | 媒體檔：匯入、探測、索引、相容副本、可用性檢查、彈幕檔 | `media_service.py` |
| `exports/` | 匯出：字幕檔、壓制成片、單幀、音訊混音，以及匯出工作區 | `studio_subtitle_export.py`、`studio_render.py`、`studio_export_ui.py` |
| `caption_style/` | 字幕外觀（手動設定）：樣式配方、預設、字型、效果 DSL、動效庫、每條字幕的樣式解析 | `style_recipe.py`、`studio_style_controller.py` |
| `caption_design/` | AI 字幕設計：網頁主題（HTML/CSS 字幕皮膚）的生成、候選、修訂與素材語彙 | `web_theme.py`、`studio_ai.py`、`authored_generation.py` |
| `rendering/` | 字幕畫面渲染：LIVE 預覽、Remotion 渲染服務、ASS 編譯、像素快取、mpv 疊加層 | `advanced_renderer.py`、`ass_compiler.py`、`visual_runtime.py` |
| `cover/` | 封面編輯 | `cover_editor.py` |
| `design/` | 軟體本身的外觀與共用控制項：主題與配色、QSS、圖示、字型層級、介面動效 | `ui_theme.py`（主題定義）、`theme_manager.py`（套用） |
| `local_models/` | 本機模型：模型清單與健康狀態、下載與儲存、模型工坊頁面、各模型支援哪些語言 | `model_registry.py`、`model_workshop.py`、`model_languages.py` |
| `system/` | 這台電腦的執行環境：Python 執行環境登記與檢查、子程序、硬體、作業系統差異 | `processes.py`、`runtime_registry.py`、`environment.py` |
| `storage/` | 使用者資料：設定檔、快取清點與清理、舊資料辨識、原子寫檔 | `settings.py`、`storage_service.py` |
| `diagnostics/` | 不改變行為的觀測：啟動與延遲追蹤、卡頓監看、程序紀錄、建置身分、診斷報告 | `startup_trace.py`、`build_identity.py` |
| `local_mcp/` | 本機 MCP：讓外部 AI 用戶端在使用者核准下讀寫工程 | `mcp_bridge.py`、`mcp_stdio.py` |
| `acceptance/` | 驗收與自我檢查腳本，只在明確開啟的驗收／QA 模式下執行，不是產品功能 | [acceptance/README.md](acceptance/README.md) |
| `locales/` | 介面翻譯檔（JSON），由根目錄的 `i18n.py` 載入 | [locales/README.md](locales/README.md) |

「軟體配色」「字幕外觀」「輸出渲染」分別在 `design/`、`caption_style/`（AI 生成的字幕主題在 `caption_design/`）、`rendering/`。名稱裡有 `theme` 的模組要看資料夾：`design/theme_manager.py` 是軟體主題，`caption_design/theme_*.py` 是字幕主題。

## 為什麼這些模組留在根目錄

根目錄只放三類模組，`tests/test_package_layout.py` 會擋住新增的其他模組：

1. **套件入口**：`__init__.py`（公開 `run_media_queue` 等服務型別，延遲載入）、`__main__.py`、`test_isolation.py`（測試與驗收用的資料隔離，套件一載入就要生效）。
2. **介面語言**：`i18n.py`、`i18n_widgets.py`，翻譯檔在旁邊的 `locales/`。
3. **被套件外的程式按名稱或檔案路徑直接載入的模組**：模型 worker 在自己的 Python 環境裡匯入 `model_integrity`、`read_only_weights`、`forced_alignment`、`python_runtime_identity`、`runtime_paths`、`optional_speaker_evidence`；PowerShell 用 `python -m` 執行 `download_sources`、`environment_repair`；`scripts/run_repository_download.py` 載入 `repository_download`；各角色的 Python 直接執行 `environment_probe.py` 這個檔案。搬動它們要同時改 worker、腳本與打包設定，而且只有實際跑模型才驗證得到，所以固定不動。

## 依賴方向

大致由上往下依賴，下層不反過來 import 上層：

```text
畫面與入口      app/  →  studio/
功能            recognition/ providers/ glossary/ subtitle_rules/ projects/ timeline/
                playback/ media/ exports/ caption_style/ caption_design/ rendering/
                cover/ local_models/ local_mcp/
共用基礎        design/（外觀）  system/  storage/  diagnostics/  根目錄模組
驗收            acceptance/（只由驗收旗標與明確的驗收掛鉤延遲載入）
```

功能資料夾裡也有自己的畫面模組（例如 `glossary/glossary_proofread.py`、`exports/studio_export_ui.py`），這是刻意的：改一個功能時，畫面和規則在同一處。

目前已由 `tests/test_package_layout.py` 檢查的規則：

- 新子套件的 `__init__.py` 只有說明文字，不 import 任何東西（避免一 import 子套件就把整串模組、Qt 或模型一起載入）。
- 產品程式碼不在模組層級 import `acceptance/`。
- `subtitle_rules/`、`system/`、`media/` 不在模組層級 import PySide6；`recognition/`、`providers/`、`storage/`、`local_models/` 只有列名的畫面模組可以。
- `system/` 與 `diagnostics/` 在模組層級只依賴根目錄模組。

已知但這輪沒有拆的交叉依賴，記在 [程式碼地圖](../docs/CODE_MAP.md) 的「還沒拆開的地方」。

## 容易混淆的邊界

每一組都寫「負責／不負責／從哪裡進入／對外提供什麼」。

### 辨識流程（recognition）與外部服務（providers）

| | `recognition/` | `providers/` |
| --- | --- | --- |
| 負責 | 任務佇列與流程協調、辨識方案、啟動本機模型 worker 並把結果轉成標準格式（`asr.py`、`asr_schema.py`）、結果與報告、辨識歷史、說話人 | 與外部服務溝通：文字 AI 的呼叫介面與排程、重試、串流；雲端語音辨識各引擎的請求與回應轉換、分段續傳；端點與金鑰；設定對話框與連線測試；用量 |
| 不負責 | HTTP 請求格式、金鑰、供應商錯誤細節；斷句校對規則；畫面 | 何時呼叫、結果怎麼變成字幕（由呼叫端決定） |
| 入口 | `service.run_media_queue`、`RunOptions`、`PipelineEvent` | 文字 AI：`ai_providers.provider_for_stage`；雲端辨識：`cloud_api_worker.run`；金鑰：`llm_config.read_secret_value` |

本機模型與雲端服務刻意沒有套同一個介面：本機模型是獨立 Python 環境裡的子程序（`recognition/asr.py` 啟動、以檔案與 stdout 標籤交換資料），雲端引擎在自己的程序裡用 HTTP（`providers/cloud_api_worker.py`）。兩者最後都轉成 `recognition/asr_schema.py` 的標準結果。

### 詞庫（glossary）與字幕規則（subtitle_rules）

| | `glossary/` | `subtitle_rules/` |
| --- | --- | --- |
| 負責 | 詞庫資料、匯入與解析、啟用狀態、任務開始時凍結成快照、查詢與替換（`terminology.TermResolver`）、建庫與學習、術語庫頁與詞庫校對頁 | 辨識後的文字與時間規則：雲端校對、斷句、標點、數字、清理、翻譯、字幕時長、品質檢查 |
| 不負責 | 斷句、標點、數字 | 詞庫內容與替換規則的來源 |
| 入口 | `terminology.snapshot_glossaries`、`TermResolver`、`apply_to_segments`；`glossary_proofread.py` | `grouping.group_subtitles`、`polishing.polish_subtitles`、`text_rules.normalize_output_text`、`punctuation_style.style_cues`、`number_fidelity.format_numbers` |

詞庫參與校對與替換的入口只有 `TermResolver`：辨識中由 `apply_to_segments` 套用，雲端校對把詞庫當作輸入，工作台詞庫校對經 `studio_glossary_service` 產生建議；寫回工程一律用 `timeline/studio_commands.BatchReplaceTextCommand`。舊的兩代替換仍在程式裡（見 KNOWN_ISSUES），不要再接新的呼叫。

### 時間軸規則（timeline）與工作台畫面（studio）

| | `timeline/` | `studio/` |
| --- | --- | --- |
| 負責 | 時間單位與座標換算、剪輯序列、所有可撤銷的編輯指令（含 Q／W、剃刀、合併、波紋、移動）、選取與吸附規則 | 頁面、滑鼠鍵盤事件、繪製、面板、快捷鍵派送；持有播放器畫布 |
| 不負責 | 繪製與事件、播放器生命週期 | 決定資料怎麼改（交給 `timeline/` 指令）、存檔（`projects/`） |
| 入口 | `studio_commands.py`、`studio_clip_edit.py`、`clip_time_mapper.py`、`studio_edit_sequence.py` | `studio_ui.SubtitleStudioPage`、`studio_timeline.WaveformTimeline` |

Qt、mpv、原生視窗與播放器的持有關係（`MpvCanvas` 持有 mpv 控制器與播放時鐘）這輪沒有拆，見 [timeline/README.md](timeline/README.md) 與 [studio/README.md](studio/README.md)。

### 工程（projects）與使用者資料（storage）

| | `projects/` | `storage/` |
| --- | --- | --- |
| 負責 | 工程資料模型、開啟／儲存／自動儲存／恢復流程、舊工程相容（載入時修補）、狀態交易、撤銷堆疊所在的工作階段、工程庫與最近工程 | 一般設定檔、原子寫檔、快取清點與刪除、舊資料辨識、媒體保存、執行期快取 |
| 不負責 | 一般設定、快取清理 | 工程內容；不另存一份工程狀態 |
| 入口 | `studio_project.save_project` / `load_project`、`studio_project_controller.StudioProjectController` | `settings.load_runtime_settings` / `save_runtime_settings`、`storage_service.py` |

兩者都從根目錄的 `runtime_paths.py` 取得使用者資料夾位置。

### 執行環境（system）與本機模型（local_models）

| | `system/` | `local_models/` |
| --- | --- | --- |
| 負責 | Python 執行環境的登記與選擇、環境檢查、子程序啟動與結束、硬體與 CUDA 偵測、作業系統差異、前景／背景資源策略 | 模型清單與健康狀態、下載與下載來源、存放位置與移除、模型工坊頁面、評測資料 |
| 不負責 | 有哪些模型、使用者選了哪個 | 程序生命週期、實際推論 |
| 入口 | `runtime_registry.resolve_runtime_python`、`processes.popen_hidden_subprocess`、`environment.ensure_environment_ready` | `model_registry.scan_model_registry`、`model_workshop.ModelWorkshopPage` |

模型實際載入、卸載與裝置選擇在各 worker 內（例如 `moss_worker.resolve_device`）；少數在同一程序裡跑的模型由 `recognition/asr.py` 的 `begin_local_asr_session` / `end_local_asr_session` 管理。使用者選的模型存在設定檔的 `models`（`storage/settings.py`）。

### 軟體外觀（design）、字幕外觀（caption_style／caption_design）與輸出渲染（rendering）

- 改軟體配色、控制項樣式 → `design/`（主題定義 `ui_theme.py`，套用 `theme_manager.py`）。
- 改字幕外觀 → `caption_style/`（手動樣式、字型、效果）；AI 產生的網頁字幕主題 → `caption_design/`。
- 改預覽或成片怎麼畫出字幕 → `rendering/`（成片的 ffmpeg 指令在 `exports/studio_render.py`）。
- 宣傳素材、封面範本、設計參考圖不在程式套件裡：`assets/`、`website/`、`scripts/readme_showcase/`。

### 介面（UI）與語言（locales）

- 介面語言：根目錄 `i18n.py`、`i18n_widgets.py` 與 `locales/*.json`，設定鍵 `ui.language`。
- 辨識語言與字幕輸出語言是另一套：`subtitle_rules/language_rules.py`，設定鍵 `subtitle_language`，經 `RunOptions.recognition_language` 進入任務。
- 畫面模組放法：主視窗與它的頁面、對話框在 `app/`；工作台在 `studio/`；某功能專用的畫面放在該功能資料夾；跨功能共用的控制項在 `design/`。新畫面模組請用 `_ui`（頁面或面板）、`_dialog`（對話框）、`_widgets`（元件集合）結尾；既有的 `main_ui_*`、`studio_*_flow` 等名稱是歷史命名，沒有大量改名。
- `app/ui.py` 只放 `MainWindow`、啟動（`run_desktop_app`）、首次設定流程，以及辨識後端選項與 AI／辨識設定的儲存函式；新的元件或對話框不要再加進去。2026-10-15 從它拆出的模組（`ui` 仍用原名稱匯出，舊寫法 `from twobyteasr.app.ui import EndpointEditor` 照常可用）：

  | 內容 | 模組 |
  | --- | --- |
  | 標題列與視窗按鈕 `WindowTitleBar`、`BrandLabel` | `app/window_chrome_widgets.py` |
  | 首頁元件 `CollapsibleFrame`、`MediaPickCard`、`MediaNameLabel`、`DropOverlay`、流程條 | `app/home_widgets.py` |
  | 視窗內對話框容器 `ModalHost` | `app/modal_host_widgets.py` |
  | 自訂首次設定 `GuidedSetupDialog` | `app/guided_setup_dialog.py` |
  | 任務結束提示卡 `CompletionDialog` | `app/completion_dialog.py` |
  | 更新對話框與檢查／下載執行緒 | `app/update_dialog.py` |
  | 辨識背景執行緒 `PipelineWorker` | `app/pipeline_worker.py` |
  | 執行紀錄捲動輔助函式 | `app/progress_widgets.py` |
  | `_icon`、`_active_theme_definition` | `app/main_ui_helpers.py` |
  | AI 端點編輯器 `EndpointEditor`、供應商檢查執行緒、`provider_for_stage`、`PromptDialog` | `providers/endpoint_editor_ui.py` |
  | 術語庫頁 `TermLibraryPage`、`GlossaryPickerDialog` | `glossary/term_library_ui.py` |
  | AI 遊戲術語搜尋 | `glossary/ai_term_search.py` |

  測試要替換這些類別裡用到的名稱（例如 `read_api_key`、`provider_for_stage`、`detect_cuda_runtime`），要打在上表的模組上，打在 `app.ui` 不會生效（[檢查方法](../docs/VERIFICATION.md)）。
- 首頁 AI 卡與 AI 文字服務設定（2026-10-22／23 新增，不是從 `ui.py` 拆出）：首頁卡 `HomeAiCard`、「內容與術語」的毛玻璃 `FrostOverlay` 在 `app/home_ai_widgets.py`；設定窗口左欄的引導卡 `AiGuidePanel`（三步、連上後的成功卡片）與 `SuccessBadge` 在 `app/ai_settings_widgets.py`。接線、狀態判斷（`_refresh_home_ai_chips`、`_refresh_ai_dialog_state`、`_place_ai_editors`）仍在 `app/ui.py`。

## 命名說明

- 搬家時保留了原檔名，所以 `studio/studio_ui.py`、`timeline/studio_commands.py` 這類名稱會有重複的前綴。這是為了讓舊文件、舊計畫和搜尋舊檔名仍然找得到。
- 只有 5 個名稱會誤導的模組在搬家時改名：`runtime` → `recognition/run_context`、`recognition_plan` → `recognition/text_ai_plan`、`project_profiles` → `recognition/recognition_profiles`、`models` → `recognition/transcript_data`、`theme_persistence` → `storage/atomic_files`。
- 套件內部維持原本的相對 import 寫法（`from ..projects.studio_project import ...`）。
