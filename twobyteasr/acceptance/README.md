# acceptance：驗收與自我檢查

這裡的模組不是產品功能。它們在真實程式裡跑固定情境、量測並寫出證據，只有在明確開啟時才會執行；一般使用者啟動程式不會載入它們。

## 怎麼被觸發

| 方式 | 入口 |
| --- | --- |
| `quick_start.py` / `2ByteASR.exe` 的旗標 | 例如 `--caption-cli-audit`、`--playback-audit`、`--runtime-fixes-audit`、`--asr-provider-self-test`（`quick_start.py` 的 `main`） |
| 環境變數 `TWOBYTEASR_ACCEPTANCE_SCENARIO` + `TWOBYTEASR_ACCEPTANCE_DIR` | `studio_acceptance_audit.start_acceptance` 依情境名稱載入對應模組（由 `app/ui.py` 的 `run_desktop_app` 延遲 import） |
| `scripts/verify_*_headed.py` | 在私人桌面啟動真實程式（原始碼或 `--exe` 指定的凍結程式），設定上面的環境變數並讀回結果 |

產品程式碼只在函式內、而且只在驗收開關打開時 import 這裡的模組（例如 `app/single_instance.py`、`playback/audio_process.py`）。`tests/test_package_layout.py` 會擋住模組層級的 import。

## 放什麼、不放什麼

- 放：`*_audit.py`、`*_selftest.py`、`*acceptance*.py`、驗收用的替身（`mosi_loopback.py`）與共用工具（`blank_project_audit.py` 的離線防護、`offline_audit_io.py`）。
- 不放：會在一般使用中執行的量測，例如 `diagnostics/playback_probe.py`（選用的播放時間線紀錄）、`caption_design/composed_text_probe.py`（AI 字幕草稿的畫面量測）、`recognition/startup_selftest.py`（第一次辨識前的字幕護欄自檢）。

驗收輸出一律寫到倉庫 `tmp/` 或指定的驗收資料夾，並隔離使用者資料；詳見 [檢查方法](../../docs/VERIFICATION.md)。
