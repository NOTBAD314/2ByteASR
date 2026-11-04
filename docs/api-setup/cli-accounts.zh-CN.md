# 账号登录类文字 AI（Grok Account / OpenAI Codex CLI / Google Antigravity，进阶）

最后核对：2026-10-14。来源见文末。标“待核实”的地方需要登录才能确认。

## 先看结论

| 问题 | 回答 |
| --- | --- |
| 在兔白里做什么 | 文字 AI：AI 断句、字幕校对、翻译。**只发送字幕文字，不上传音频** |
| 和 API Key 方式的区别 | 不填 API Key。兔白调用你电脑上**已安装、已登录**的官方命令行工具（CLI），用你的账号额度完成请求 |
| 在哪里填 | 「AI 智能断句设置」→“AI 服务”选 **Grok Account**、**OpenAI Codex CLI** 或 **Google Antigravity** |
| 要先做什么 | 先在电脑上安装对应的官方命令行工具。安装要在 PowerShell 里执行一行官方命令（见文末“进阶”）；兔白不会替你安装 |
| 适合谁 | 已经在用这些工具、熟悉命令行的人。一般使用者更推荐 DeepSeek、阿里云百炼等 API Key 方式：设置更简单、费用更清楚 |
| 兔白验证状态 | 已有接入；本轮未用真实账号重新实测 |

新安装的兔白，“AI 服务”默认选的就是 **Grok Account**。没装 Grok 命令行工具的话，请改选其他服务。

## 三种方式分别是什么

| 兔白里的名字 | 官方工具 | 程序名 | 登录方式（官方） | 账号与额度（官方，2026-10-14） |
| --- | --- | --- | --- | --- |
| Grok Account | Grok Build（SpaceXSI / x.ai） | `grok` | 第一次启动时打开浏览器验证 | 官方页面没有写需要哪种订阅，待核实 |
| OpenAI Codex CLI | Codex CLI（OpenAI） | `codex` | `codex login` 后在浏览器完成登录；可选“Sign in with ChatGPT” | ChatGPT Free、Go、Plus、Pro、Business、Edu、Enterprise 方案都含 Codex，可用次数随方案、模型和任务不同 |
| Google Antigravity | Antigravity CLI（Google） | `agy` | 在浏览器用个人 Google 账户登录，或选 Business account（Gemini Enterprise） | 个人免费方案有“基础的每周用量限制”；Google AI Pro / Ultra 限额更高。个人方案是否包含 CLI，官方价格页没写，待核实 |

地区限制由各服务自己决定，官方 CLI 页面没有列出可用国家 / 地区，待核实。

## 官方链接

| 用途 | 网址 |
| --- | --- |
| Grok Build 入门（安装、登录） | <https://docs.x.ai/build/overview> |
| Grok Build 命令参考（`grok login`、`grok update`） | <https://docs.x.ai/build/cli/reference> |
| Codex CLI 介绍与安装 | <https://learn.chatgpt.com/docs/codex/cli> |
| Codex 登录方式 | <https://learn.chatgpt.com/docs/auth> |
| Codex 方案与价格 | <https://learn.chatgpt.com/docs/pricing> |
| Antigravity 首页 | <https://antigravity.google/> |
| Antigravity 下载（含 CLI 安装命令） | <https://antigravity.google/download> |
| Antigravity CLI 入门（安装位置、登录） | <https://antigravity.google/docs/getting-started?tab=cli> |
| Antigravity 方案与价格 | <https://antigravity.google/pricing> |

## 从零开始

1. **安装官方工具**：按上表的官方页面安装（PowerShell 命令见文末“进阶”）。装好后最好重新打开兔白，让它找到新装的程序。
2. 打开兔白的「AI 智能断句设置」，任选一种方式：
   - 首页“AI 智能断句”卡片上的“设置 AI”按钮（或直接点这张卡片）
   - 模型工坊 →“AI 模型 / 智能断句”
   - 「申请与设置 API」里这篇教程下方的“去填写这家服务的密钥”（打开后仍要在“AI 服务”里自己选）
3. 在“AI 服务”下拉里选 **Grok Account**、**OpenAI Codex CLI** 或 **Google Antigravity**。卡片会变成命令行页面，显示“CLI：未检测”和“请先检测 CLI 与登录状态”。
4. 点 **重新检测**。找到程序时会显示版本和程序位置，以及“登录/凭据：……”。没找到时会出现 **安装帮助** 按钮（只是一段说明，兔白不会自动安装）。
5. 点登录按钮：Grok 是 **管理 Grok 登录**，Codex 是 **打开官方 Codex 登录**，Antigravity 是 **打开 Google 登录**。浏览器会打开官方登录页；状态行会显示“在浏览器完成登录即可（窗口会自动收尾，无需保持任何外部窗口）”和登录链接。Codex 登录时还会弹出一个命令行小窗，登录完成后会自动关闭。
6. 登录完成后显示“……：登录流程完成；当前配置请求仍需测试”，兔白会自动刷新可用模型列表。
7. 点 **测试连接**，看到“连接测试通过”后，点对话框右下角 **保存设置**。

**一张卡片还是两张**：对话框上方的开关“同一云端模型负责字幕校对与全文断句（推荐）”默认打开，这时只有一张卡片，标题是“统一校对与断句模型”。关掉后会出现“字幕校对模型”和“全文断句模型”两张卡片，各自选服务。

## 需不需要开通服务、充值或储存空间

| 项目 | 是否需要 |
| --- | --- |
| 账号 | 需要对应服务的账号（见上文“三种方式”） |
| 订阅 / 充值 | 由各服务的方案决定；兔白不收费，也看不到你的剩余额度 |
| API Key | 不需要 |
| OSS 等储存空间 | 不需要 |

## 兔白里的每一栏

| 栏位 / 按钮 | 做什么用 | 例子 | 已预填？ |
| --- | --- | --- | --- |
| AI 服务 | 选用哪种方式 | `OpenAI Codex CLI` | 新安装默认是 `Grok Account` |
| 重新检测 | 找本机的官方程序、读版本、看登录状态 | — | — |
| 登录按钮 | 打开官方登录（名字见上文第 5 步）；登录成功后 Codex 的按钮变成“重新登录或切换账号” | — | — |
| 安装帮助 | 没找到程序时出现，只显示说明 | — | — |
| 更新 CLI / 查看方法 | 只有 Grok 有。用官方安装程序装在 `.grok\bin` 的，确认后执行官方自更新；其他安装方式只显示说明 | — | — |
| 退出 Codex 登录 | 只有 Codex 有，执行官方的退出登录 | — | — |
| 复制诊断信息 / 展开诊断详情 | 出问题时把检测结果复制下来反馈 | — | — |
| 模型 | 用哪个模型；留空表示用该工具自己的默认模型（输入框提示“默认模型”） | Antigravity 下拉里有 `gemini-3.8-flash-high`、`gemini-3.7-flash-high` | 留空 |
| 刷新模型 | 让命令行工具列出可用模型 | — | — |
| 进阶设置：Base URL、协议与输出能力 | 命令行方式只用到其中的 JSON Mode、Structured Output，保持勾选即可 | — | 已勾选 |

## 测试时会看到什么

**重新检测**：只检查程序和登录状态，不让模型生成文字。例如 Codex 已登录时显示“Codex CLI 已登录（模型调用待真实请求验证）”；未登录显示“Codex CLI 未登录；点击官方登录完成 OAuth 后重新检测。”

**测试连接**：通过命令行工具发一句很短的固定文字，要求只回一小段 JSON，会消耗极少量账号额度。

- 成功时状态行显示：`连接测试通过 · 中文 JSON 字段正确 · …… · 3.21s`（中间一段说明 JSON 方式，最后是用时），卡片上的“请求：”一行变成“连接测试通过（中文 JSON）”。
- 超过 5 秒还没回应时显示“模型响应较慢，仍在等待… N 秒 · 可取消”，按钮变成“取消测试”。命令行工具冷启动较慢，多等一会儿是正常的。
- 首页 AI 卡片下方会显示“使用账号登录”和“连接正常 / 连接失败”。

## 常见失败与下一步

| 现象 | 可能原因 | 下一步 |
| --- | --- | --- |
| 重新检测后仍是“未检测到”，出现“安装帮助” | 程序没装，或装在兔白找不到的位置 | 按官方页面安装后重新打开兔白再检测。兔白找的位置见文末“进阶”；Codex 在 Windows 上只认 `codex.exe` |
| “未安装官方 Codex CLI；请选择安装帮助。” | 同上（Codex） | 用官方安装方式装好 Codex，再点“重新检测” |
| “……尚未登录”“登录未完成，请重新检测” | 还没登录，或浏览器里没完成登录 | 点登录按钮，在浏览器完成登录后点“重新检测” |
| 登录窗口一直没反应 | 浏览器没有弹出，或登录被取消 | 状态行里有登录链接时，复制到浏览器打开；仍不行就再点一次登录按钮（运行中再点一次会取消） |
| “需更新 CLI；本次请求失败” | 命令行工具版本太旧 | Grok：点“更新 CLI / 查看方法”；Codex、Antigravity：按官方页面更新后点“重新检测” |
| 测试很慢或超时 | 工具冷启动慢、网络慢或服务繁忙 | 再测一次；仍超时就改用 API Key 方式 |
| 提示用量用完、需要升级方案之类 | 账号的方案额度用完 | 等额度恢复，或升级方案；也可改用 API Key 方式 |
| 任务完成页写“原文回退 N 批” | 任务中这些批次的 AI 请求失败，兔白保留了原文 | 先“重新检测”和“测试连接”看原因，处理后重新识别 |

## 隐私与费用

- **传到哪里**：由命令行工具发到它自己的服务（Grok → x.ai；Codex → OpenAI；Antigravity → Google）。
- **传什么**：字幕文字，以及你填写的游戏 / 内容名称和术语提示。**不发送音频**。字幕工作室的“AI 设计”在模型支持看图时，可能附带画面截图或字幕效果预览图。
- **账号凭据**：兔白不保存你的账号密码，也不读取或保存登录令牌；登录状态由官方工具自己保存。例如 Codex 官方说明它把登录信息存在本机 `~/.codex/auth.json`（明文文件）或系统凭据库里。
- **费用**：计入你在该服务的方案额度，兔白看不到也不替你计费。

## 进阶（一般使用者可跳过）

**安装命令（来自官方页面，2026-10-14 核对）**

- Grok Build（<https://docs.x.ai/build/overview>）：Windows PowerShell 执行 `irm https://x.ai/cli/install.ps1 | iex`；macOS / Linux 执行 `curl -fsSL https://x.ai/cli/install.sh | bash`。
- Codex CLI（<https://learn.chatgpt.com/docs/codex/cli>）：macOS / Linux 执行 `curl -fsSL https://chatgpt.com/codex/install.sh | sh`。页面上还有 Windows、npm、Homebrew 分页，本次没能读到这些分页里的命令，请在官方页面查看。
- Antigravity CLI（<https://antigravity.google/download>）：Windows PowerShell 执行 `irm https://antigravity.google/cli/install.ps1 | iex`；macOS / Linux 执行 `curl -fsSL https://antigravity.google/cli/install.sh | bash`。官方说 Windows 上装在 `C:\Users\<用户名>\AppData\Local\agy\bin`。

**兔白去哪里找程序**

- Grok：PATH 里的 `grok`，或 `%USERPROFILE%\.grok\bin\grok.exe`。
- Codex（Windows）：`%LOCALAPPDATA%\Programs\OpenAI\Codex\bin\codex.exe`，或 PATH 里的 `codex.exe`。只有 `.cmd` 包装、没有 `codex.exe` 的安装方式会被判定为未安装。
- Antigravity：PATH 里的 `agy.exe`，或 `%LOCALAPPDATA%\agy\bin\agy.exe`。

**兔白执行的官方命令**

- 登录：Grok `grok login --oauth`；Codex `codex login`（检测时 `codex login status`，退出时 `codex logout`）；Antigravity 直接启动 `agy`，由它带出登录流程。
- 请求时，兔白对 Grok 关掉联网搜索和全部工具、对 Codex 关掉执行命令、浏览器、插件等功能，只让它回答文字；给 Antigravity 的命令只额外加了关闭斜杠命令的 `--disable-slash-commands`。
- “安装帮助”的说明里写着“完成后回到这里点击‘检测 CLI’”，对应的按钮实际叫“重新检测”。

## 来源（2026-10-14 核对）

- Grok Build 入门：<https://docs.x.ai/build/overview>
- Grok Build 命令参考：<https://docs.x.ai/build/cli/reference>
- Codex CLI：<https://learn.chatgpt.com/docs/codex/cli>（原地址 <https://developers.openai.com/codex/cli> 已永久跳转到这里；网页需要浏览器执行脚本，用浏览器打开读取）
- Codex 登录：<https://learn.chatgpt.com/docs/auth>
- Codex 方案与价格：<https://learn.chatgpt.com/docs/pricing>
- Antigravity 首页：<https://antigravity.google/>
- Antigravity 下载：<https://antigravity.google/download>
- Antigravity CLI 入门：<https://antigravity.google/docs/getting-started?tab=cli>
- Antigravity CLI 产品页：<https://antigravity.google/product/antigravity-cli>
- Antigravity 方案与价格：<https://antigravity.google/pricing>
