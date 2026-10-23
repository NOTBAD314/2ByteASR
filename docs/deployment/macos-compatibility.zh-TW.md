# Mac 版本怎麼選：公開 0.8.3 與 Sonoma 相容候選

更新：2026-10-23。這份說明把「目標支援」「最終二進位靜態檢查」和「實際執行」分開；Windows 版的要求沒有因此降低。

**使用 macOS 14.4.1 的 M3 Max 不應下載公開 0.8.3 DMG。** 該包的啟動宣告要求 15.0，而完整媒體依賴中還有一個要求 15.7.9 的函式庫。本輪候選以原生 arm64、macOS 14.0 為目標；精確的 14.4.1 尚無實機可驗證。36 GB 記憶體與 M3 Max 不是已知的排除條件，但不能用硬體規格代替安裝測試。

## 檢查的是哪個包

| 項目 | 實際證據 |
| --- | --- |
| 公開附件 | `2ByteASR-0.8.3-macos-arm64-Setup.dmg`，556,348,259 bytes |
| SHA-256 | `9a06c271d143d1a92ade1b9aeaf76edec68c27021c7f1bb5edb4c20a417911bd`；本地檔案與 GitHub Release 資產摘要相同 |
| 來源 | `7c7302f568d47428ddcf299a2b5dece3b249fa58`，乾淨來源；建置來源摘要 `6a2c91613960787ed6122372fbd57dacdb57fd05013ad81b13766afb7cad44ac` |
| 建置環境 | GitHub macOS 15.7.9 arm64、Python 3.10.11；[原版建置與驗收](https://github.com/NOTBAD314/2ByteASR/actions/runs/39908496472) |
| 架構 | 原生 arm64；沒有 Intel 或 Universal 2 安裝包 |
| 簽章 | ad hoc 簽章完整性檢查通過；沒有 Developer ID，沒有 Apple 公證 |

DMG 中 388 個實體 Mach-O 的路徑與 SHA-256 **全部**對上原版 CI 回執。Windows 解包未重建符號連結，因此這次本地解包只供讀取二進位，不能拿來重包或當作 Mac 安裝測試。[公開版本](https://github.com/NOTBAD314/2ByteASR/releases/tag/v0.8.3)。

## 哪一層提高了下限

| 元件 | 原版實際版本／二進位下限 | 載入時機與影響 |
| --- | --- | --- |
| Info.plist | `LSMinimumSystemVersion=15.0` | Finder 正常啟動的入口條件 |
| PyInstaller 主程式、內嵌 Python | 主程式與 Python.framework 的 minos 11.0 | 啟動必需；不能只看這兩個檔案判斷整個包 |
| PySide6 / Shiboken6 / Qt | 6.9.2，QtCore minos 12.0 | 基礎 GUI 必需；官方 Qt 6.9 目標下限也是 12.0 |
| NumPy / PyAV | 2.2.6 / 17.1.0；PyAV arm64 擴充 minos 14.0 | GUI／媒體處理的原生依賴，不能只降低 plist 到 12 |
| FFmpeg / ffprobe / mpv | 9.0.2 / 0.41.0_10，主二進位 minos 15.0 | 播放、抽音、編碼或外部播放器；相關依賴同樣影響使用 |
| `libtesseract.5.dylib` | minos **15.7.9** | `libavfilter.12.1.102.dylib` 直接連結它；即使不使用 OCR，也不能忽略它 |
| Remotion 內附媒體 | 4.0.513 的 FFmpeg 7.1 主程式與七個 dylib 都要求 15.0 | 進階渲染；這是另一套媒體依賴，不能只修 tools/ffmpeg |
| Node | 22.16.0，minos 11.0 | 字效／進階成片渲染時啟動 |
| Chrome Headless Shell | 149.0.7790.0，minos 12.0、SDK 26.2 | Remotion 進階渲染時啟動；沒有使用 QtWebEngine（打包明確排除） |
| 首次下載 uv、Python | uv 0.11.7、Python 3.10.19 / 3.12.13，鎖定檔原生最高 minos 都是 11.0 | 模型準備時下載；全包雜湊已核對，沒有依賴使用者自備 Python |
| MLX / mlx-metal / mlx-audio | 0.32.3 / 0.32.3 / 0.5.8；Sonoma wheels 中 3 個原生檔案 minos 14.0、SDK 26.5 | 選用模型的獨立環境，GUI 不匯入 MLX；還要確認 Metal 實際可用 |

原版 91 個 Mach-O 要求 15.0，另有上述 15.7.9 函式庫；其餘檔案沒有把這個下限再提高。**完整媒體功能的可審核下限至少為 15.7.9**，15.0–15.7.8 不能因為通過 plist 檢查就視為完整支援。這是靜態下限，不代表每個較低 patch 已實際啟動並失敗。

SDK、建置主機版本與 minos 分別記錄。較新的 SDK 並不自動提高部署下限；降低宣告也不會修好已編譯的依賴。[Qt 6.9 官方平台說明](https://doc.qt.io/archives/qt-6.9/macos.html)；[MLX 0.32.3 官方安裝說明](https://github.com/ml-explore/mlx/blob/v0.32.3/docs/src/install.rst)；[PyAV 17.1.0 官方 wheel](https://pypi.org/project/av/17.1.0/)。

## 候選改了什麼

保留 PySide6 6.9.2、PyAV 17.1.0、Node 22.16.0 與既有程式架構。媒體改用官方 Homebrew core `252c29dbece147fa170e1755c0d68c18ffe3d651` 的 Sonoma 瓶：FFmpeg-full 9.0.1_1、mpv 0.41.0_9；整個媒體依賴閉包重新準備，不能混用 runner 上較新的函式庫。Sonoma 瓶的 Tesseract 仍要求 14.8.5，因此改從鎖定的同版 5.5.3 來源實際編譯到 14.0。Remotion JS / Rust 保持 4.0.513，只使用官方 4.0.400 中同為 FFmpeg 7.1 的完整九檔媒體組（minos 13.0）；各 dylib ABI 版本一致，現行 compositor 的 63 個 FFmpeg 匯入符號全數吻合，仍須原生渲染驗證。Qt、Python 擴充、媒體、Node、瀏覽器與 helper 全部通過最終 Mach-O 守門後，才可產生候選 DMG。

GUI / CPU 環境的 121 個解析依賴固定版本；MLX、MOSS 保留各自的完整雜湊鎖。首次下載的 uv / Python 及安裝完成的模型環境先檢查原生架構與 minos，再做隔離的原生探測；模型真的跑過樣本後才登記就緒。

系統和架構不符時，選擇／下載前說明原因。MLX 沒有 Metal 時不自動切到未驗證 CPU；MOSS / FireRed 在下載權重前，以子程序檢查實際 MPS 與需要的精度。雲端服務只在使用者明確選擇並設定後使用，沒有音訊或付費的自動切換。

## 相容性矩陣

| 版本／macOS／架構 | 基礎應用 | 播放與字幕編輯 | 雲端識別 | 本地模型／MLX | 成片輸出 | 驗證狀態與限制 |
| --- | --- | --- | --- | --- | --- | --- |
| 公開 0.8.3／14.4.1／arm64 | 啟動宣告不符合 | 媒體依賴不符合 | 無法以此包保證使用 | 無法以此包保證使用 | 媒體依賴不符合 | **已確認不支援**此安裝包；不等於 M3 Max 硬體不支援 |
| 公開 0.8.3／15.0–15.7.8／arm64 | 宣告允許，未逐版執行 | 完整依賴下限不符合 | 尚未測試 | 尚未測試 | 完整依賴下限不符合 | **已確認不支援**作為完整功能範圍；不能只看 plist |
| 公開 0.8.3／15.7.9／arm64 | 啟動、建立／重開工程通過 | 播放、改字、剪切、保存通過 | 本次原版 CI 未執行 | SenseVoice CPU 通過；MLX / MPS 本次未執行 | 字幕及影片輸出通過 | **已實測通過**列明項目：run 39908496472，GitHub 虛擬 Mac；無公證／實體聽審 |
| Sonoma 候選／14.4.1／arm64 | 目標 | 目標 | 目標，需自行選擇服務 | 需各後端就緒探測 | 目標 | **尚未測試**精確 14.4.1；使用者目前沒有可測 Mac |
| Sonoma 候選／CI macOS 14.x／arm64 | 原生建置驗證中 | 原生驗證中 | 模擬服務驗證中 | CPU / MLX 驗證中 | 原生驗證中 | **尚未測試**最終候選；結果按 CI 回執補充 |
| Sonoma 候選／macOS 15／arm64 | 等同一 DMG 回歸 | 等同一 DMG 回歸 | 不冒充真實服務 | CPU 回歸待驗 | 待驗 | **尚未測試**最終候選；不以重新打的另一個包替代 |
| 本輪／macOS 13、12／arm64 | 沒有可交付相容包 | PyAV / 媒體組合仍需替換或重建 | 不能以原始碼存在承諾可用 | MLX 0.32.3 不支援；其他路線未驗 | 沒有相容產物 | **已確認不支援**本輪包；較早相容機型的另行移植尚未測試 |
| 本輪／Intel 或 x86_64 Rosetta 程序 | 沒有相符包 | 沒有完整 x86_64 依賴組合 | 尚無可交付包 | MLX 無 x86_64；現有 PyTorch 組合無新版 Intel Mac wheel | 沒有相符包 | **已確認不支援**本輪包；沒有宣稱 Universal 2 |

macOS 12 是 Qt 6.9 這一層可行的下限，**不是兔白現成安裝包的下限**。若要繼續到 13 / 12，至少需要重建或替換 PyAV arm64 和完整媒體依賴、確認 Node／瀏覽器與 Python wheels，並用相容的較早機型實測。為此另外維護一組大量原生依賴，成本高於本輪優先修好 Sonoma；目前沒有證據可承諾 12 / 13 或 Intel 的完整流程。

## 安裝、更新與診斷

1. 確認檔名是 `macos-arm64`，核對交付紀錄中的 SHA-256。公開 0.8.3 與本輪 Sonoma 候選不可互相替代。
2. 將 DMG 裡的 App 拖到 Applications。程式自帶 GUI、播放器、FFmpeg、Node 與渲染器，不需要自己安裝 Homebrew、Python 或開發工具。模型在選用時另行準備。
3. 候選仍為 ad hoc 簽章，沒有 Apple 公證。簽章信任問題與最低系統版本是不同問題；不應關閉 Gatekeeper 或改寫系統／二進位版本標記。
4. 若舊版已可用，保留一份舊 App 供回退；替換 App 前先退出。不要刪除 Application Support、模型或工程。

舊 Mac 客戶端的更新邏輯不理解 Mac 相容性資訊，可能開啟 Windows Setup 的連結。這次需手動換入相容候選。新客戶端仍核驗原 Ed25519 簽章，只選清單中明確符合完整 macOS 版本、arm64 與執行環境契約的完整 DMG；沒有相容條目就保留目前程式。Mac 不套用 Windows 元件更新。後續發佈必須把通過檢查的 DMG 回執加入原 `release_pipeline.py feed --macos-receipt`，再沿用簽章與來源驗證流程。

能進介面時使用既有「回報問題」。GUI 前也會留下 `macos-startup.json`；Python 啟動例外另有 `macos-startup-failure.json`，記錄完整系統版本、程序／硬體架構、Rosetta、建置來源、套件與工具版本。原生 bootloader／動態載入器更早失敗時，可執行 DMG 內「啟動失敗診斷.command」收集資訊。診斷不查詢序號，不匯出 API Key，也不移除隔離屬性。缺少函式庫、符號、架構、系統下限、簽章／公證與模型初始化分開分類。
