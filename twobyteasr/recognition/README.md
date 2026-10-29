# recognition：一次辨識任務怎麼跑

這裡負責「把素材交給模型、把結果收回來、交給字幕規則、寫成工程與報告」的流程協調。斷句、校對、標點、數字等規則在 `subtitle_rules/`；文字 AI 與雲端辨識的請求在 `providers/`；模型 worker 本身是倉庫根目錄的 `*_worker.py`。

## 唯一入口

畫面不直接呼叫模型或字幕規則，只呼叫 `service.run_media_queue(paths, options, event_sink=..., cancel_token=...)`。

- `RunOptions`（`service.py`）凍結這次任務的設定、啟用的詞庫與工作台資訊；`create_runtime_context` 由它產生 `run_context.RuntimeContext`。
- `run_context.activate_runtime_context` 同一時間只允許一個辨識或校對任務，並把狀態同步到舊的 `subtitle_core.RUNTIME_*` 全域變數。
- 進度以 `PipelineEvent` 送回畫面：流程裡呼叫 `cache.record_run_event` → `service` 轉成事件 → 主視窗的 `_handle_event`。

`app/ui.py` 的 `_start_run` → `_launch_pipeline_worker` → `PipelineWorker`（QThread）呼叫這個入口；「匹配文稿」走 `script_match.py`，不經過這條佇列。

## 一個檔案的處理順序

`run_media_queue` 先做環境檢查（`system/environment.py`），再對每個檔案呼叫倉庫根目錄 `moss_firered_pipeline.process_media`。主要階段：

1. 統一成 16 kHz 音訊（`cache.load_shared_audio`）。
2. 主力轉寫（MOSS worker，或 `asr.transcribe_primary_reference` 的其他後端）；同時做語音活動偵測。
3. 字詞時間（FireRed-AED；日語、英語用對齊模型）。
4. 組成主稿，Qwen3 複核，FireRed-LLM 處理有爭議的段落。
5. 詞庫替換（`glossary/terminology.apply_to_segments`）與選用的雲端校對（`subtitle_rules/polishing.py`）。
6. 斷句（`subtitle_rules/grouping.py`；英語 `english_segmentation.py`）。
7. 定稿時間（`pipeline_runtime.finalize_cues`、`subtitle_rules/display_timing.py`）。
8. 收尾 `pipeline_runtime.complete_media_run`：翻譯（選用）→ `projects/studio_project.create_studio_outputs` 寫工程 → `reporting` 寫任務報告。

每個階段都包在快取（`cache.run_cached_stage`）裡；會改變輸出的參數必須進入快取簽名。

## 模型 worker

本機模型在獨立的 Python 環境裡以子程序執行：`system/runtime_registry.resolve_runtime_python(role)` 決定用哪個 Python，`system/processes.py` 以隱藏視窗啟動，請求與結果用 JSON 檔或 stdin 交換，進度用帶標籤的 stdout 行。啟動點：

| worker | 由誰啟動 |
| --- | --- |
| `moss_worker.py` | `moss_firered_pipeline`（MOSS 專用 Python 3.12 環境） |
| `firered_aed_worker.py`、`qwen_asr_worker.py`、`qwen_aligner_worker.py`、`sensevoice_worker.py`、`firered_llm_worker.py`、`glm_asr_worker.py`、`canary_asr_worker.py` | `asr.py` |
| `ctc_aligner_worker.py` | `ctc_alignment.py` |
| `mlx_worker.py` | `mlx_backend.py`（Apple 晶片） |
| `asr_api_worker.py` | `providers/cloud_api_worker.cloud_worker_command`（雲端辨識） |

worker 在自己的環境裡會 import `twobyteasr` 根目錄的幾個模組（見 [套件地圖](../README.md)），所以那些模組和 `twobyteasr/__init__.py` 在模組層級只能用標準函式庫。

## 和 subtitle_core 的關係

倉庫根目錄的 `subtitle_core.py` 是舊介面的相容門面：它保存全域設定，並把 `recognition/asr.py`、`recognition/cache.py`、`subtitle_rules/` 的 `correction`、`segmentation`、`timing`、`output`、`text_rules` 用 `import *` 重新公開；這些模組反過來也 `from subtitle_core import *`。這是歷史留下的循環，`tests/test_module_layout.py` 守著它的現狀。新功能不要再加進 `subtitle_core.py`。

## 結果放在哪

- 工程：`recognition_result.recognition_project_path` 放在工程庫（`projects/studio_project.project_library_root`，預設 `%LOCALAPPDATA%\2ByteASR\Projects`）裡與素材同名的資料夾，資料夾名加上 `__{任務編號}_{序號}`，避免同名素材互相覆蓋。
- 任務報告：`%LOCALAPPDATA%\2ByteASR\reports\` 下的 `*_字幕任务报告.json/.txt`（`reporting.py`）。
- 辨識不再直接寫 SRT／TXT；字幕檔由工作台匯出（`exports/studio_subtitle_export.py`）。

## 名稱提醒

- `text_ai_plan.py`（這次任務要不要用文字 AI）與 `recognition_plans.py`（使用者可選的辨識方案預設）是兩回事。
- `recognition_profiles.py` 保存辨識設定組合，不是工作台工程。
- `transcript_data.py` 是 `SpeechSegment`／`SubtitleCue`／`WordUnit` 資料類別，不是模型清單（模型清單在 `local_models/`）。
- `optional_models.py`、`optional_model_details.py`、`optional_model_process.py` 屬於已停用的 VibeVoice／DiariZen，留著是為了辨認舊資料，不再交付。
