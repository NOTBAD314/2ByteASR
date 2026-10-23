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
`n- CI 39944894726 在媒体准备前停下：ca-certificates 使用不分架构的 all 瓶，第一版闭包检查只允许 arm64_sonoma。现已明确允许 all 数据瓶（仍拒绝其他 OS / CPU），新增回归；没有生成候选。未重复相同失败做法。
