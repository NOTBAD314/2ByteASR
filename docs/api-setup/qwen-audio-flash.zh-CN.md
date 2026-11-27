# 阿里云百炼 Qwen Audio Flash

最后核对：2026-11-28

## 在兔白里做什么

用百炼的 HTTP 接口把音频片段转成文字。兔白在 HTTPS 请求中发送音频片段。使用这项功能前，请确认素材可以发送给百炼。

## 从零开始

1. 登录阿里云，开通百炼，进入所选地域的工作空间并创建 API Key。
2. 在模型页确认模型已开通，并核对计费。用量计入你的百炼账户。
3. 在兔白的语音识别 API 设置中选择「阿里云百炼｜Qwen Audio Flash HTTP」，填入 Key 后用一段短音频测试。

## 每一栏

- **API Key** 填入百炼工作空间创建的 Key。
- **服务地址** 已预填北京地域的 HTTP 接口。使用其他地域或专用工作空间时，从该工作空间的官方文档复制完整接口地址。
- **模型** 默认使用 `qwen-audio-3.1-asr-flash`。

## 测试会看到什么

连接测试应返回一段可读的转写。保存后可在识别方案中选择该云端服务。

## 常见失败

Key 无效时，核对 Key 和接口的地域。提示模型无权限时，回百炼确认模型开通和账户状态。音频超限时，先用一段较短的音频复测。下一步可在百炼控制台核对请求错误与用量。

## 来源

[获取 API Key](https://help.aliyun.com/zh/model-studio/get-api-key) · [模型与计费](https://help.aliyun.com/zh/model-studio/qwen-audio-3-1-asr-flash) · [HTTP 接口](https://help.aliyun.com/en/model-studio/qwen-audio-asr-http-api)
