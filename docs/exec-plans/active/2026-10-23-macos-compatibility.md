# macOS 14.4.1 相容性與可驗證的系統下限

日期：2026-10-23。獨立分支 `codex/macos-compatibility-20261023`，基於公開 v0.8.3 / 7c7302f568d47428ddcf299a2b5dece3b249fa58。共享開發樹 1,937 項變更、Windows 日常程式與使用者資料保留原樣。

## Goal

查清已發佈 DMG 的真實門檻；優先準備 14.4.1 原生 arm64 候選，按證據評估 13 / 12 / Intel；安裝、啟動、模型與更新遵守一致的相容性要求。

## Non-goals

不改工程、識別結果或設定格式；不靜默切換雲端，不呼叫付費 API；不公開正式 Release，不替換日常。靜態掃描不冒充舊系統實測。

## Acceptance criteria

- [x] 現有 DMG 的 SHA、來源、架構、逐層最低版本、簽章可追溯。
- [x] 修正實際依賴，最終 app / runtime 的 Mach-O 掃描守門。
- [x] 選擇與下載前檢查模型條件，原生探測隔離。
- [x] 更新不選錯系統或架構，核對舊客戶端。
- [x] 候選 DMG 與安裝說明、真實回執；缺少的真機測試具體列明。
- [x] 聚焦回歸通過；支援文件、矩陣與現狀符合證據。
- [ ] 精確 macOS 14.4.1／M3 Max 真機驗收，以及 Developer ID／公證；目前沒有可用條件，保留 active。

## Current state

2026-10-24：候選來源 `0ba0b48dd5b3a7017e1f9c77bfbe5512d0536379`，run 39982963356。同一 DMG 已在 14.8.9／15.7.9 完成基礎與真識別／編輯輸出；MLX 的已安裝下載／載入／樣本與 Metal probe 兩系統均通過，MOSS＋FireRed MPS 全流程在 15.7.9 通過。14 的 8 GB runner 仍在 MPS 小張量回報記憶體不足，未開始下載大型權重，因此整個 run 保留 failure。

本地交付 `releases/0.8.3-macos14-candidate-20261024/`，包含 DMG、同來源 ZIP、SHA256SUMS、安裝回退說明、完整矩陣與原生回執。349 項原生聚焦測試通過；389 個 Mach-O 符合 arm64／14.0 靜態條件。精確 14.4.1／36 GB M3 Max、Developer ID／公證、實體輸入法／聽審／長任務仍未完成。12／13／Intel 不支援本輪包，沒有虛構舊系統通過。共享開發樹的程式與 Windows 日常未由本輪替換。

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

- CI 39956542749：自動化基礎流程與較新系統回歸均為 success，但逐張檢視上一候選原生截圖發現預覽沒有字幕。原始畫素資料／發布回執都有字幕，整個可見畫布卻被另一 QWidget 的影片重繪蓋住；不能把 CI success 當作完整視覺驗收。
- 已以 Windows 上強制相同 Qt 路徑的完整隔離 Studio 重現：surface 截圖有雙語、canvas 截圖沒有；專項真實 QWidget 畫素測試改前失敗（應為白色字幕，實際被綠色影片蓋住），改後通過。VideoCompositionScene 在 Qt surface 已擁有影像堆疊時只生成／發布與接收互動，不再重畫影片覆蓋字幕；Windows mpv 分支不變。
- 增加實際 canvas 暫隱／恢復現有字幕 slot 的同步像素差檢查，暫停畫面必須穩定且真的有可見字幕；同時保留當下字幕圖像與幾何。雙語階段還必須等到翻譯 companion 準備好。這不是注入畫面，也沒有改工程或播放時間。Windows Qt 完整預覽對照有 13,606 個字幕差異像素；該臨時診斷腳本退場碼 1，不當作正常入口流程通過。
- Qt 預覽與像素回歸 13 項、桌面證據 10 項、影片合成 worker 2 項通過；待下一份 Mac 包取得真正可見的雙語畫面。

- 後續選包審查發現應用與可選執行庫的下限需要分層：macOS 15 正常會選 MLX / mlx-metal 的 15_0 wheel（實際 minos 15.0，已下載核對），不應用 App 的 14.0 固定門檻拒絕它。MLX 安裝改按真實主機完整版本掃描，執行庫身分包含系統版本，重用前核對原生下限；系統降級後不會沿用較新 OS 的 MLX 環境。已驗證較新主機接受、14.4.1 拒絕 15.0 原生碼、未知版本拒絕；56 項相關回歸通過。基本 App 的 14.0 全包守門保持。

- CI 39962892871 / app ab8ac69c：389 個實體 Mach-O、DMG、啟動、CPU / MLX / loopback、動效通過；312 個平台測試通過／2 跳過／1 既有排除。相同 DMG 在 15.7.9 的真實字幕像素、雙語保存與完整導出全部通過。14.8.9 的單語字幕也已可見，但嚴格的新門在暫停切雙語時拒絕空白畫面。
- 第二個 UI 根因已重現：切雙語後 ASS refresh 捕捉到最後的 revision 5，暫停的 raster scene 卻仍停在 revision 4。等待 15 秒仍不恢復；發出一次正常展示請求後 0.203 秒恢復。apply_display 在完成 refresh 後請求最終 caption scene，不尋位、不換播放時鐘。四次完整 Qt 重現均在 0.23–0.27 秒可見，兩行字幕有 10,361 個實際像素差；臨時診斷退場碼仍為 1，僅用作因果／畫素證據。相關 20 項回歸通過，Mac 的 3 秒等待與像素門均未放寬。

## 候選 ba23be11 與已安裝模型補測

- CI 39973611420：真正 DMG 為 574556314 bytes，SHA `5290c7c08917d4c40a9a653a924c1785a32ec480381e5a580ed8c5d60a478765`；389 個實體 Mach-O 全部符合 arm64／14.0，325 項平台測試通過／2 跳過／1 既有排除。14.8.9 與 15.7.9 的同包 DMG 安裝、正常啟動／重啟、工程、真識別、中文／雙語編輯剪切保存、四種字幕與 12 秒成片、透明字效執行均通過。14 的雙語與重開畫布有 6200／6335 個真實字幕像素差，已檢視整窗與輸出 PNG。較新系統的 Gatekeeper 評估 exit 3，Developer ID／公證仍未取得，瀏覽器隔離下載未驗。
- CI 39977625974 是同包額外模型驗收，不重建 App。14.8.9 的 MLX 在權重下載前，被既有隔離保護擋住驗收器錯放的 `out/models`（隔離邊界為 `out/profile`）。只修外部驗收器到 `profile/models`，新增生產路徑守門回歸；不放寬 App 的保護。額外支援只補測 MLX，避免將未請求的 MPS 寫為通過。
- 同場 14.8.9 的 8 GB runner，MPS float16 小張量僅配置 256 bytes 即回報 backend out of memory；權重下載與模型初始化未開始。保留 stderr，不依第三方提示取消記憶體上限，也不改為靜默 CPU。此為該 CI 環境失敗，不推廣成 36 GB M3 Max 或所有 macOS 14 不支援。
- 同場 15.7.9 的 **MPS 後端獨立 passed=true**：工坊首次準備 MOSS、FireRed、VAD、說話人模型成功；正常 Home 真識別、4 條字幕全部有 measured words、可見雙語、剪切／保存重開、字幕及 12 秒成片、重啟第二項任務通過。MOSS 回執為 bfloat16／mps，FireRed worker 明確回報 float16／mps:0。已看實際雙語與成片 PNG。整個 job 因獨立 MLX 驗收器路徑問題為 failure，不能忽略它，也不能抹掉獨立 MPS 的完整證據。
- 外部 checker 4446e4f2 的工作流步驟縮進錯誤使派送被拒，未消耗 Mac 模型執行；修正為 4f4e3163 並完成 YAML 解析後，派送 39979414374，只補測同一 ba23be11 DMG 的 MLX。驗收器的 15 項邊界測試通過；不重打 App，不改模型流程或隔離保護。

## 已安裝 MLX 的隔離初始化修正

- 補測 39979414374 在兩個系統都正確進入鎖定下載，卻在 Python 原生層 abort：`test_isolation.install()` 主動匯入 QtCore。MLX 獨立環境沒有 Qt，但打包 App 的 resource path 可見不完整的 PySide6 namespace；Shiboken bootstrap 因 None 路徑中止，無法用捕捉 ImportError 處理。這解釋來源入口通過、已安裝且隔離的入口失敗，不能冒充 Metal／模型不支援。
- 保留全部隔離資料／快取／token 路徑與下載守門；QSettings 改在 Qt 真正被匯入時才套用。新子程序反例故意放入一匯入就退出的 PySide6 namespace，證明 headless 入口不載入它；另用真正 QtCore 確認延後匯入後 QSettings 仍只寫隔離目錄。沒有關掉測試隔離或將開發來源注入安裝包。
- 同輪修正既有診斷誤標：SenseVoice readiness 不再把主機 MPS 能力當作實際裝置；PROCESS 只採 worker 回報的 CPU／MPS／CUDA，沒有回報就是 unknown；建置套件清單改名 build_python_packages，與 GUI 實際套件 metadata 分開。識別結果、工程、設定格式不變。
- 聚焦 61 項通過。擴展檢查另外發現兩個既有問題：Windows 沙箱讀不到真實 LocalAppData，該環境探測斷言未通過；舊 Qwen UTF-8 fixture 缺目前必需的 context／evidence_root 與 PCM policy 回執，已對照 ba23be11 確認原本即過時並修正 fixture。沒有修改或放寬生產 Qwen 校驗。
- 下一份候選重新打包。工作流在產生 DMG 後自動用該 run 的相同 artifact，在 14／15 啟動已安裝 MLX／MPS 補測；App／checker 身分繼續分開記錄。

- 2026-10-24：新來源 `0ba0b48dd5b3a7017e1f9c77bfbe5512d0536379` 已派送 run `39982963356`，只用標準 Mac runner；建置完成後以同一 artifact 自動補驗基礎、MLX／MPS。前一份 ba23be11 安裝包與回執保存在本機交付目錄並標示為前候選，沒有用它代替新來源驗收。

- 新候選實體 DMG：574734802 bytes，SHA `5f78bb4ba86be0016b8458a826d61427bfb07c1552e0f691781b875a70edd05f`，來源摘要 `cc5ba8b868abe7f6b4e27b5dda6dc964a7d7114348b9c6652df144327b23df02`。389 個原生檔案通過；349 項原生聚焦測試通過／4 平台跳過／1 既有排除。14.8.9 與同包 15.7.9 的安裝、正常啟動、工程、SenseVoice、可見雙語、剪切保存、四種字幕、12 秒成片與透明動效全部通過。新包的 SenseVoice readiness 與實際 PROCESS 都回報 CPU／CUDA false；雙語 PNG 與成片已逐張檢視。
- 新包在 14.8.9 的 frozen MLX 獨立項目 **passed=true**：正式下載流程、0.6B 真實樣本識別、ForcedAligner 13 個樣本單位與 GPU／Metal worker probe 通過，不再觸發 Qt abort。此 job 因獨立 MPS 小張量仍回報同樣記憶體不足而為 failure；MPS 權重未下載，不取消限制、不重試相同硬體失敗。15.7.9 的新包 MLX／MPS 結果等待該 job 完成。

## 本輪可交付結果（2026-10-24）

- 最後 15.7.9 的新包 MLX／MPS job 為 success，兩後端獨立 passed=true；MPS 正常 GUI 流程含 4 條 measured-words 字幕、保存重開、雙語畫面、字幕與成片、第二項真識別，退出碼 0。原生雙語及成片 PNG 已逐張檢視，並非真人在 M3 Max 操作過。
- 新 DMG 已下載到交付目錄，SHA 與 producer 完全一致；基礎 14／15 的 162＋115 份回執檔案逐一校驗。新來源 ZIP 174617247 bytes，SHA `39549b994c665bb07f981424edcaab3c2ceda9eb84b875200800cd9edd05013e`。前候選與全部失敗保留，不用新資料覆寫舊包。
- GitHub Latest 在交付前再次確認仍為 v0.8.3。沒有建立正式 Release、更新公開附件、合入 main 或替換日常。修正在隔離分支分段提交；共享工作區只更新本輪擁有的文件段落與新文件。
- 文件索引在完整共享工作區執行 build/check；公開來源快照缺少原本的 document-library-overrides.json，不把該快照的缺項冒充驗證通過。精確 14.4.1 的未驗條件仍在，因此不把計畫移入 completed。
