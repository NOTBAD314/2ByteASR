# macOS 14.4.1 相容性與可驗證的系統下限

日期：2026-10-23。獨立分支 `codex/macos-compatibility-20261023`，基於公開 v0.8.3 / 7c7302f568d47428ddcf299a2b5dece3b249fa58。共享開發樹 1,937 項變更、Windows 日常程式與使用者資料保留原樣。

## Goal

查清已發佈 DMG 的真實門檻；優先準備 14.4.1 原生 arm64 候選，按證據評估 13 / 12 / Intel；安裝、啟動、模型與更新遵守一致的相容性要求。

## Non-goals

不改工程、識別結果或設定格式；不靜默切換雲端，不呼叫付費 API；不公開正式 Release，不替換日常。靜態掃描不冒充舊系統實測。

## Acceptance criteria

- [ ] 現有 DMG 的 SHA、來源、架構、逐層最低版本、簽章可追溯。
- [ ] 修正實際依賴，最終 app / runtime 的 Mach-O 掃描守門。
- [ ] 選擇與下載前檢查模型條件，原生探測隔離。
- [ ] 更新不選錯系統或架構，核對舊客戶端。
- [ ] 候選 DMG 與安裝說明、真實回執；缺少的真機測試具體列明。
- [ ] 聚焦回歸通過；支援文件、矩陣與現狀符合證據。

## Current state

Windows 主機，尚無 14.4.1 / 13 / 12 / Intel Mac。公開 v0.8.3 與本地 DMG 同 SHA `9a06c271d143d1a92ade1b9aeaf76edec68c27021c7f1bb5edb4c20a417911bd`，556348259 bytes。CI run 39908496472。plist 與媒體鎖均要求 15.0，使用 arm64_sequoia 瓶。原版 Mac 15 有安裝、SenseVoice、編輯與輸出回執；Developer ID / 公證未完成。

## Tasks

1. DMG 內原生檔案與 CI 回執鑑識。
2. 依賴組合、版本與架構判斷、原生掃描守門。
3. 下載、能力、啟動診斷與更新修正，聚焦測試。
4. 既有 Mac CI 準備候選、驗證、記錄缺口。
5. 文件、矩陣、交付。

## Verification strategy

Windows 做純版本、架構、Mach-O 解析及下載契約測試。GUI、Metal、安裝、簽章只在 Mac 記為執行證據。區分已實測通過、靜態符合待驗、已確認不支援、尚未測試。

## Decisions

以公開版隔離實作，不將其他進行中改動帶入；不只修改 plist 或重寫 Mach-O 標記。

## Findings

既有打包只檢查 lipo 架構與 Homebrew 絕對連結，沒有檢查 LC_BUILD_VERSION 的 minos。

原版 DMG 的 388 個實體 Mach-O 已掃描：91 個要求 15.0.0，libtesseract.5.dylib 要求 15.7.9，FFmpeg 鏈會載入它。Python / bootloader 11.0、Qt 12.0、PyAV 17.1.0 arm64 14.0、Node 11.0、Chrome Headless Shell 149 的二進位下限 12.0；SDK 版本另記。原版完整媒體門檻為至少 15.7.9，而 plist 只寫 15.0。只在 15.7.9 的原版 CI 有執行證據。

修復方案：保留 Qt 6.9.2 / PyAV 17.1.0 / Node 22.16.0；媒體改用官方 core 252c29dbece147fa170e1755c0d68c18ffe3d651 的 Sonoma 瓶（FFmpeg-full 9.0.1_1、mpv 0.41.0_9）。必須重建整個依賴閉包，不能混用 runner 預裝新版函式庫。最終逐檔 minos 守門。macOS 12 / 13 的 arm64 路線還需替換或重建 PyAV 及完整媒體閉包，本輪不降低其他平台依賴。

## Progress

- 2026-10-23：需求、協作規則、既有計畫與發佈產物身分核對完成，建立本計畫。

## Blockers

- 無目標版本與 Intel Mac 實機。
- 無 Developer ID / 公證身分。

- M1：純 Python Mach-O 掃描器 8 項測試通過（SDK/target、fat slices、損壞資料、架構與外部依賴）；實際原包掃描為靜態證據。Windows 解開 DMG 跳過符號連結，不宣稱可在此重包或安裝。

## M2 程式與建置修正（2026-10-23）

- 最低版本與架構共用純標準庫判斷（保留 patch，比較數字 tuple）；候選目標 14.0 / 原生 arm64，沒有宣稱 Intel / Universal 2。MLX 缺 Metal 不再靜默切 CPU。
- GUI / CPU 固定原版實際解析的 121 個依賴；Python / uv 下載後、各模型 runtime 安裝後、最終 app 及 DMG 打包前都讀取原生二進位，超門檻或錯誤架構即停止。目標設定只用於本輪從原始碼編譯的部分，不覆寫預編譯版本標記。
- 媒體整個 runtime dependency closure 取自同一官方 core 快照，不能沿用 runner 預裝高門檻函式庫；macOS 14 建置，15 用同一 DMG 做回歸。
- 模型選擇／下載先檢查條件；原生探測仍在 worker。啟動前留 host / 架構 / Rosetta / 套件 / build 診斷，回報問題包加入同一資訊。DMG 附啟動失敗診斷 command，不修改隔離屬性或信任設定。
- 更新沿用 Ed25519 簽章清單，增加 macos_installers；Mac 只選符合完整系統版本、架構及 runtime contract 的完整 DMG，不使用 Windows 元件更新。舊客戶端不理解新欄位，仍會指向 Windows Setup；需手動安裝此次候選遷移，不能聲稱改新欄位能修好舊客戶端。
- 本機純契約與更新回歸 118 項、媒體 worker / desktop 邊界 10 項、診斷整合 10 項通過。模型工坊 31、GUI 準備 11、MLX 13 項逐檔通過；更新視窗 5 項、平台 16 項通過／1 平台跳過。均非 Mac 執行證據。
- 已拆開官方 mlx 0.32.3 / mlx-metal 0.32.3 的 macosx_14_0_arm64 wheels，3 個 Mach-O 下限都是 14.0.0，SDK 26.5.0；mlx-audio 0.5.8 為純 Python。完整模型流程仍需原生執行。
- 使用者已確認目前沒有可測 Mac；14.4.1 實機驗收繼續標為尚未測試。CI 的 14.x 不冒充 14.4.1。

- CI 39944894726 在媒体准备前停下：ca-certificates 使用不分架构的 all 瓶，第一版闭包检查只允许 arm64_sonoma。现已明确允许 all 数据瓶（仍拒绝其他 OS / CPU），新增回归；没有生成候选。未重复相同失败做法。

- CI 39945165855：macOS **14.8.9** / arm64 的完整媒體安裝與 Python runtime 通過；最終 App 掃描攔下 Tesseract minos 14.8.5、Remotion 的九個 FFmpeg 媒體檔 minos 15.0。沒有生成 DMG；未降低守門條件。實際 261 個平台測試通過，2 個過時 Qt 測試 fixture、1 個被替身強制拒絕平台卻取回空錯誤的測試失敗；已針對 fixture / 訊息修正。Keychain 真實回合通過，VideoToolbox 硬體編碼未通過，保留獨立限制。
- MLX 新探測誤拒絕：0.5.8 的 mlx_audio 模組沒有 __version__；改為使用實際 distribution metadata，並保留 native stderr / exit code。沒有把失敗改記成成功。
- 原生輸入修正：Tesseract 5.5.3 從同版官方雜湊鎖來源以 deployment target 14.0 編譯；Remotion JS / Rust 仍為 4.0.513。官方 4.0.400 中的 FFmpeg 仍為 n7.1，九件 minos 13.0；全部 dylib ABI 版本與目前套件相同，現行 Rust compositor 對 FFmpeg 的 63 個符號全在相容媒體中。已用實際原版檔案執行置換工具的靜態驗證（10 個 native objects 通過），還需原生渲染驗收。
- 新增候選的 12 秒透明動效驗證：使用包內的原始 SubtitleOverlay 元件、Node、Chrome、Rust compositor、FFmpeg，檢查 360 幀、Alpha 與入退場；另讓正常 Studio 流程手動編輯雙語、保存重開、匯出雙語 SRT。這些是驗收，不改使用者字幕或工程格式。
- 補上 MOSS / FireRed 下載權重前的子程序 MPS 實際精度配置探測；前置原生載入錯誤分類與回報問題附件。最新相關 87 項及 Qt 預覽 12 項測試通過；沒有把合成 host 判斷當作 Mac 實測。

- CI 39949667020：Tesseract 5.5.3 已真正編譯，CLI / dylib 的 minos 都是 14.0.0、SDK 14.5.0；封裝守門發現 upstream CMake 命名為 ABI 5.5，而 Homebrew autotools 消費端需要 ABI 5。現以已核對的原始碼一處 CMake SOVERSION 設定對齊 major 命名，仍重新編譯，不修改已編譯版本標記。
- 首次安裝額外缺口：原 CPU runtime 解析了 jieba / oss2 / TextGrid / crcmod / antlr4-python3-runtime 五份 sdist，其中 crcmod 含 C 擴充。新增官方來源 SHA 鎖、CI 預編譯與隨包 wheelhouse（逐 wheel／原生檔案驗證）；終端使用者的 pip 僅接受 binary wheels，禁止現場編譯。模型、工程、設定的 schema 不變。

- CI 39951540153 / app f16ca986：已產生真正 DMG（574676443 bytes，SHA f0b17ef7e00485f40ed4a7d6cfa9e01a232336e43ef13ab3f1803aef283bd860）。最終原生門檻、歸檔搬移、/Applications 安裝、正常啟動、空工程、CPU 首次準備、播放像素、雙語保存重開、第二次真實識別、雲端 loopback、Keychain、MLX 及雲端+MLX對齊、12 秒透明動效均通過。VideoToolbox 硬體編碼未通過，保留硬體限制。
- 未宣稱完整流程通過：Studio 驗收在字幕檔案回讀停下，實際 SRT/TXT 正確含兩行，舊驗收 oracle 卻期望原文一行；現在依已明確選定的 translation-first 模式計算獨立期待值，新增實際輸出及故意破壞譯文的回歸，文字與時間檢查不放寬。影片 GUI 匯出因前一斷言停止而未執行，必須重跑。
- 同 DMG 在較新 Mac 正常啟動與靜態檢查通過；外部空工程 fixture checker 缺 PySide6 而停止，並非 App 缺依賴。驗證器新增獨立 venv，只供建立 fixture；App 仍用不含該 venv 的最小 PATH。
- 加入只測既有候選的 frozen MLX/MPS 準備入口（checker 1a46ad77）；App 來源與驗收器來源分開記錄。新增對診斷分類的窄修正，含 arm64 的檔案路徑不再被誤判為架構問題。

- CI 39956542749：自動化基礎流程與較新系統回歸均為 success，但人工檢視上一候選原生截圖發現預覽沒有字幕。原始畫素資料／發布回執都有字幕，整個可見畫布卻被另一 QWidget 的影片重繪蓋住；不能把 CI success 當作完整視覺驗收。
- 已以 Windows 上強制相同 Qt 路徑的完整隔離 Studio 重現：surface 截圖有雙語、canvas 截圖沒有；專項真實 QWidget 畫素測試改前失敗（應為白色字幕，實際被綠色影片蓋住），改後通過。VideoCompositionScene 在 Qt surface 已擁有影像堆疊時只生成／發布與接收互動，不再重畫影片覆蓋字幕；Windows mpv 分支不變。
- 增加實際 canvas 暫隱／恢復現有字幕 slot 的同步像素差檢查，暫停畫面必須穩定且真的有可見字幕；同時保留當下字幕圖像與幾何。雙語階段還必須等到翻譯 companion 準備好。這不是注入畫面，也沒有改工程或播放時間。Windows Qt 完整預覽對照有 13,606 個字幕差異像素；該臨時診斷腳本退場碼 1，不當作正常入口流程通過。
- Qt 預覽與像素回歸 13 項、桌面證據 10 項、影片合成 worker 2 項通過；待下一份 Mac 包取得真正可見的雙語畫面。

- 後續選包審查發現應用與可選執行庫的下限需要分層：macOS 15 正常會選 MLX / mlx-metal 的 15_0 wheel（實際 minos 15.0，已下載核對），不應用 App 的 14.0 固定門檻拒絕它。MLX 安裝改按真實主機完整版本掃描，執行庫身分包含系統版本，重用前核對原生下限；系統降級後不會沿用較新 OS 的 MLX 環境。已驗證較新主機接受、14.4.1 拒絕 15.0 原生碼、未知版本拒絕；56 項相關回歸通過。基本 App 的 14.0 全包守門保持。

- CI 39962892871 / app ab8ac69c：389 個實體 Mach-O、DMG、啟動、CPU / MLX / loopback、動效通過；312 個平台測試通過／2 跳過／1 既有排除。相同 DMG 在 15.7.9 的真實字幕像素、雙語保存與完整導出全部通過。14.8.9 的單語字幕也已可見，但嚴格的新門在暫停切雙語時拒絕空白畫面。
- 第二個 UI 根因已重現：切雙語後 ASS refresh 捕捉到最後的 revision 5，暫停的 raster scene 卻仍停在 revision 4。等待 15 秒仍不恢復；發出一次正常展示請求後 0.203 秒恢復。apply_display 在完成 refresh 後請求最終 caption scene，不尋位、不換播放時鐘。四次完整 Qt 重現均在 0.23–0.27 秒可見，兩行字幕有 10,361 個實際像素差；臨時診斷退場碼仍為 1，僅用作因果／畫素證據。相關 20 項回歸通過，Mac 的 3 秒等待與像素門均未放寬。
