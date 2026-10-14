# 申請與設定 API：教程目錄

最後核對：2026-10-14。這些教程與程式裡「申請與設定 API」對話方塊“詳細說明與教程”裡顯示的是同一份文字（打包時一起帶上）。每篇都寫了：它在兔白裡做什麼、官方連結、從零申請的步驟、要不要開通服務 / 充值 / 額外儲存、兔白裡每一欄填什麼、哪些已預填、測試成功時看到什麼、常見失敗與下一步。需要登入才能看到的頁面標為“待核實”，不編按鈕名稱。

## 先選哪一個（語音識別，會上傳音訊）

| 你的情況 | 建議 | 教程 |
| --- | --- | --- |
| 沒有顯示卡，**只想填一把 Key** 就開始 | MOSS-Transcribe-Diarize Pro 雲端（MOSI）：直接上傳本地音訊，有說話人；只有句段時間（要逐字時間再裝本地對齊模型） | [教程](mosi-moss-pro.zh-Hant.md) |
| 需要字/詞級時間，願意設定一次 OSS 私有儲存 | 阿里雲百鍊 · 錄音檔案識別（中國站）或 Qwen Cloud（國際站，新加坡） | [百鍊](bailian-filetrans.zh-Hant.md)、[Qwen Cloud](qwen-cloud-filetrans.zh-Hant.md) |
| 已有訊飛 / Groq / OpenAI 賬號 | 訊飛 Spark-ASR 2.0（每約 55 秒一段文字）、Groq Whisper（句段時間）、OpenAI（預設模型不回時間戳） | [訊飛](iflytek-spark.zh-Hant.md)、[Groq](groq.zh-Hant.md)、[OpenAI](openai-transcribe.zh-Hant.md) |
| 進階：OpenRouter、Azure OpenAI 部署、自定義相容介面 | 需要自己判斷模型與部署；兔白未用真實金鑰實測 | [OpenRouter](openrouter.zh-Hant.md)、[Azure](azure.zh-Hant.md)、[自定義](custom-asr.zh-Hant.md) |

百鍊和 Qwen Cloud 的錄音檔案識別只接受“服務商能讀到的音訊網址”。正式使用要你自己的 OSS 私有儲存（兔白上傳、生成限時簽名連結、取得結果後刪除）。服務商的臨時上傳官方寫明“請勿用於生產環境”，兔白只把它當作明確選擇的“僅供試用”。

## 文字 AI（斷句、校對、翻譯；只發送字幕文字）

| 服務 | 教程 |
| --- | --- |
| DeepSeek | [教程](deepseek.zh-Hant.md) |
| 阿里雲百鍊 · 通義千問 | [教程](bailian-text.zh-Hant.md) |
| OpenAI | [教程](openai-text.zh-Hant.md) |
| Google Gemini | [教程](gemini.zh-Hant.md) |
| xAI Grok API | [教程](xai.zh-Hant.md) |
| 進階：自定義相容服務、賬號登入類 CLI | [自定義](custom-text.zh-Hant.md)、[賬號登入類](cli-accounts.zh-Hant.md) |

各平台能做什麼、哪些已實測，見[沒有 NVIDIA 顯示卡時能做什麼](../architecture/platform-support.md)。
