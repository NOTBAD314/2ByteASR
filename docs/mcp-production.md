# 独立制作 MCP 工具

外部 AI 客户端现在可以创建、打开和保存工程，独立调用识别、AI 校对、AI 断句、口吃文字整理、停顿分析、剪切和视频导出。客户端自行组合这些步骤，也可以只调用其中一项，不需要运行固定制作流程。

连接仍使用应用设置中的“外部 AI（MCP）”与现有 `--mcp-stdio` 入口。新增13个工具与原18个工具一起提供，没有额外插件目录、批次令牌或逐功能授权系统。原 `preview_*`、`apply_plan`、`get_plan_status`、`undo_plan` 和 `export_subtitles` 保留原参数和行为：旧计划仍由用户在软件内批准。

## 开关与配置

MCP默认关闭。新增制作与修改操作受现有 `allow_edits` 控制，视频导出受 `allow_export` 控制，术语库读取仍受 `allow_glossary` 控制。设置页明确说明哪些操作直接执行。关闭访问、撤回相关权限或改变范围会取消相应的在途任务；已生成的结果文件保留，取消或撤权后的识别结果不会继续替换当前工程。

`scope=current` 仍只允许当前打开的工程，不能通过新接口切换到其他工程；新建和打开工程库内其他工程需要已有的 `scope=library`。工具不会自动修改这个选择。未授予词库权限时，复核摘要返回有限状态和未知计数，不读取独立词库或公开词库身份。

识别使用软件中保存的模型与服务配置；文字校对、断句使用原生文字服务。缺少模型、依赖、服务或凭据时返回 `configuration_required` 和配置位置。既有原生确认缺失时返回实际确认原因，不自动写入同意。鉴权、限流、余额、网络、响应格式和执行失败分别报告，客户端不应自动切换供应商或反复提交收费请求。

## 工具

| 工具 | 行为 |
| --- | --- |
| `create_media_project(media_path, name)` | 新建单素材工程，验证媒体并通过原生控制器打开；不识别，不覆盖同名工程 |
| `open_project(project_path)` | 打开原生工程；拒绝丢弃未保存编辑或接管其他任务 |
| `save_project(project_id, revision)` | 原生正式保存，核实磁盘与内存内容一致，返回内容指纹 |
| `start_recognition(project_id, revision)` | 启动原生识别，跟踪原生任务，结果真正进入Studio后才完成 |
| `start_glossary_proofread(...)` | 对全部或指定字幕独立进行AI校对；可指定词库，不重跑识别 |
| `start_sentence_refine(...)` | 对现有字幕独立进行AI断句/句内节奏优化，保留字级时间规则 |
| `cleanup_stutter(...)` | 本地口吃文字建议/采用；不发AI请求，也不剪音视频 |
| `detect_speech_pauses(...)` | 调用原生停顿分析，返回带ID的候选，不执行剪切 |
| `apply_pause_cuts(project_id, revision, job_id, candidate_ids)` | 对明确候选执行原生可撤销剪切，拒绝锁定或已变化的工程 |
| `export_video(project_id, revision, name, destination)` | 使用原生渲染器导出视频，不覆盖已有文件 |
| `get_review_summary(project_id, revision)` | 只读复核证据和新鲜度，不打开页面或启动AI；未知计数为null |
| `get_job(job_id)` | 查询本MCP任务、进度、错误、结果及输出身份 |
| `cancel_job(job_id)` | 请求取消指定MCP任务，不停止其他原生任务或清理输出 |

完整参数以MCP工具发现返回的schema为准。`project_id`、`revision` 来自原 `get_status`；新增操作的回执同时提供 `project_path` 和 `project_fingerprint`。异步结果采用前检查工程身份、内容指纹、revision、锁定和所依赖的词库，避免将旧结果套到人工修改后的工程。

### 文字建议与采用

三个文字工具使用 `action="preview"` 生成结果，返回 `job_id`。等待该任务完成，核对 `api_status`、失败明细和 `snapshot_fresh` 后，通过同一个工具以 `action="apply", job_id="..."` 采用结果；采用时不要再次传入字幕/词库选择。这个动作不会发第二次AI请求。成功但没有修改的结果无需采用。

部分失败不等于全部校对成功。客户端应明确选择保留原文或处理失败，不能将未知计数填成零。口吃整理改变的是字幕文字；停顿剪切才改变音视频时间轴。

### 作业与恢复

返回作业表示操作已经启动，不表示已完成。主要状态为 `running`、`cancelling`、`completed`、`failed`、`cancelled`；程序重启时未完成作业标为 `interrupted`。取消请求要等原生任务确认，不能把 `cancelling` 当作最终结果。

作业记录保存在本机MCP数据目录，用于恢复查询，不保存密钥或额外权限。重启不自动重发识别、AI或导出；先检查已保存结果。AI预览的原生采用对象只保存在进程内，重启后不能假装旧预览仍可直接应用。错误和部分产物保留供核对。

取消后收到的AI结果仅形成可查询摘要，不应用字幕修改；摘要随job保存并可在重启后读取。没有收到结果、或不能确定外部请求是否已完成时明确标为未知，不把请求数填零，也不自动重试。

一个客户端可串行处理多个视频。每个视频开始前查询当前工程，完成当前job后再进入下一步；人工识别、断句和校对任务占用时拒绝重复启动。

### 示例流程

1. `create_media_project` → 查询创建作业，取得工程身份。
2. `start_recognition` → 查询作业至完成，重新读取当前工程身份。
3. 按需要单独调用校对、断句或文字口吃工具；核对预览后采用同一job结果。
4. `detect_speech_pauses` → 检查候选 → `apply_pause_cuts`。
5. `save_project` → `export_video` → 原 `export_subtitles`，核对前后工程指纹及输出文件。

标题、简介、封面、批量调度、素材归位和发布不属于这些工具，由客户端负责。工具不接受任意代码、shell命令或整份工程JSON替换。

## 复用本地模型与独立数据目录

模型及模型运行环境沿用应用已有的路径解析和注册机制，不随MCP模块复制或下载。需要独立数据目录时，可使用已有的 `2BYTEASR_USER_DATA_ROOT`、`2BYTEASR_MODEL_ROOT`、`2BYTEASR_RUNTIME_ROOT` 配置；GUI与stdio必须使用相同的数据根。设置页复制的MCP配置会包含显式数据根，不包含API密钥。

显式数据根下，GUI的Qt设置也写入该根下的INI文件；默认启动不改变原有设置位置。同一安装目录仍遵循原生单实例规则。本地模型路径存在不代表可运行，仍需检查所选环境和真实作业回执。

## 实现与验证入口

新增代码位于 `twobyteasr/local_mcp/production*.py`，通过stdio注册和GUI桥接有限分发挂接。工程控制器和Readiness的内部交接守卫只在MCP调用提供时使用；普通GUI入口保持原默认行为。识别、文字服务、停顿算法、撤销命令、保存器和渲染器仍由原生模块负责。

聚焦检查：

```text
python -m pytest tests/test_mcp_bridge.py tests/test_mcp_clients.py tests/test_mcp_production.py tests/test_mcp_production_media.py tests/test_mcp_production_recognition.py tests/test_mcp_production_text.py
```

合成媒体集成测试可通过 `TWOBYTEASR_TEST_FFPROBE` 指向现有FFprobe；缺依赖时明确跳过，不代表真实视频验收通过。没有真实模型、文字服务和输出回执时，单元测试不构成完整制作验证。
