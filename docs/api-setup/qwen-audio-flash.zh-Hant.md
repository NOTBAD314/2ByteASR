# 阿里雲百煉 Qwen Audio Flash

最後核對：2026-11-28

## 在兔白裡做什麼

用百煉的 HTTP 介面把音訊片段轉成文字。兔白在 HTTPS 請求中傳送音訊片段。使用前請確認素材可以傳送給百煉。

## 從零開始

1. 登入阿里雲並開通百煉，在所選區域的工作空間建立 API Key。
2. 在模型頁確認已開通模型，並核對計費。用量會計入你的百煉帳戶。
3. 在兔白的語音辨識 API 設定中選取「阿里雲百煉｜Qwen Audio Flash HTTP」，填入 Key 後用一段短音訊測試。

## 每個欄位

- **API Key** 填入百煉工作空間建立的 Key。
- **服務位址** 已預填北京區域的 HTTP 介面。使用其他區域或專用工作空間時，從該工作空間的官方文件複製完整位址。
- **模型** 預設使用 `qwen-audio-3.1-asr-flash`。

## 測試會看到什麼

連線測試應回傳一段可讀的轉寫。儲存後可在辨識方案中選取這項雲端服務。

## 常見失敗

Key 無效時，核對 Key 和介面的區域。模型沒有權限時，回百煉確認模型開通及帳戶狀態。音訊超限時，先用較短的片段重試。下一步可在百煉控制台核對請求錯誤與用量。

## 來源

[取得 API Key](https://help.aliyun.com/zh/model-studio/get-api-key) · [模型與計費](https://help.aliyun.com/zh/model-studio/qwen-audio-3-1-asr-flash) · [HTTP 介面](https://help.aliyun.com/en/model-studio/qwen-audio-asr-http-api)
