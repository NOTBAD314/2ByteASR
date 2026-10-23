# 0146：Mac 支援範圍由最終原生檔案與獨立執行證據決定

日期：2026-10-23。狀態：採用；候選執行驗收未完成。

## 問題

公開 0.8.3 宣告 macOS 15.0，但媒體鏈中的 Tesseract 實際 minos 為 15.7.9。把媒體改成 Sonoma 瓶後，Tesseract 仍要求 14.8.5，Remotion 另帶的 FFmpeg 仍要求 15.0。只讀套件版本、SDK 或改 plist 都會漏掉這些限制。

## 決定

- `system/macos_compatibility.py` 統一定義應用與各執行環境的最低完整版本、架構及明確錯誤；數字 tuple 比較保留 patch，判斷未知版本時停止，不將它當作最新。
- GUI 不匯入 PyTorch / MLX。選用後端保持既有子程序與就緒樣本；下載權重前先確認實際 Metal / MPS，沒有驗證的 CPU 路線不自動替代 GPU。
- 安裝器、下載環境、模型準備與最終 App 各自掃描 Mach-O；每個 slice 的 CPU、minos、SDK、連結與 SHA 分開記錄。靜態通過不等於目標系統執行通過，也不等於已檢查全部 OS 符號可用性。
- Mac 本體目標 14.0 / arm64。媒體使用固定 Sonoma 依賴閉包，Tesseract 5.5.3 從鎖定來源真正編譯到 14.0。Remotion JS 與 Rust 保持 4.0.513，只選取官方 4.0.400 套件中相同 FFmpeg 7.1 ABI 的完整九檔媒體組；必須核對每個成員 SHA、dylib 版本，以及目前 compositor 對 FFmpeg 的 63 個匯入符號，再做打包程式的真實渲染。不能只替換單一 DLL／dylib 或重寫版本標記。
- Mac 的媒體、瀏覽器、Node 隨完整 App 交付。原有 Windows 元件更新協議維持；簽章清單可附 `macos_installers`，新 Mac 客戶端只選明確符合系統、架構與 runtime contract 的完整 DMG。舊客戶端忽略新增資訊，需先手動遷移；不假裝新欄位能改變已發佈程式的行為。
- 普通使用者不依賴 Homebrew、CMake 或自己的 Python。這些只可用於受控建置；實際安裝入口用清理後的 PATH 驗證。

## 代價與邊界

維護一份跨平台程式來源，增加 Mac 原生輸入鎖與原生建置步驟，不降低 Windows 依賴。每次更新 Remotion 消費端、媒體或 Python 都必須重新經過靜態與執行守門。macOS 12 / 13、Intel、Rosetta 與精確 14.4.1 未取得對應環境前不承諾通過；Developer ID / 公證、下載隔離屬性與直接啟動是獨立的分發證據。

詳見[任務與失敗保留](../exec-plans/active/2026-10-23-macos-compatibility.md)、[使用者相容性說明](../deployment/macos-compatibility.zh-TW.md)。
