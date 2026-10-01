# macOS 实验验证状态（0.5.0）

本轮新授权的一次私有原生 CI 已执行并失败：run `36882470527` / attempt `1`，工作流与源码同为 `d41b3359985d6bc5e82f55b96dbf316b30a30a08`，workflow ref 为专用私有分支；main 未改。macOS `15.7.9` / arm64 / Python `3.10.11`。失败发生在固定 Homebrew core 前：runner 预置 core 带 `rustup.rb` 修改与额外 `openssl@1.1.rb`，脚本过严要求干净目录，尚未下载/倒入媒体。当前没有 `.app`、安装 ZIP 或 DMG；本轮运行和以下本地后修订不能互相移植结论。

本轮媒体准备失败；Python CPU运行库、Node/Chromium、PyInstaller、搬移启动、模型、Studio、内嵌预览与硬件均未执行。四件诊断载荷9135bytes、原始Actions ZIP11056bytes已逐SHA保全，artifact `11171454141`，SHA `398b709ccce6f83143dfe93e4046dad3984cd9a8f9b5cb374c5a9b783cf76cd8`；应用上传步骤无文件不代表存在应用。

之后本地修订：在独立目录取得准确官方core快照，临时切换媒体配方目录，完整保留并在成功/失败后恢复runner原目录，包含上述改动；不删除任何无关keg或工具。builder继续只消费已验证receipt和准确工具路径。24项定向测试通过（含真实文件移动/失败恢复/旧keg/摘要/架构）；本轮执行前准确私有快照在清除继承凭据的本机环境中53通过1跳过。该目录切换修订未经过原生CI，不能宣称媒体安装已通过。原始失败本机回执已脱敏，零AI请求。

以下是首次 run `36875057224` / 源码 `596bc062d1e7c0f72508c8edcb60c0fbbe965eb2` 的历史有效结果；不充当新源码验收。已关闭 Windows repair 保留。

| 层级 | 当前状态 | 边界 |
|---|---|---|
| A 原生依赖和 .app | CPU运行库与导入通过；38回归通过、2跳过；构建失败 | 媒体版本锁在PyInstaller启动前阻止构建 |
| B 解压移动启动 | 未执行 | 没有真实.app；不生成占位安装包 |
| C GUI模型准备和中文识别 | 未执行 | 原生CLI依赖准备通过，不代替GUI/模型；未下载模型 |
| D Home→Studio编辑/导出 | 未执行 | 后续步骤skipped；没有注入字幕或云端请求 |
| E 内嵌预览/同步/特效 | Windows真帧28项与56回归通过；Mac headed未执行 | 原生offscreen控制器测试不等于Studio音画/特效验收 |
| F 真人/硬件/长任务 | MPS可用与tensor探测通过；其余未验 | 没有整模型CPU/MPS比较、实际硬件编码、IME、听感或长任务 |

准确失败是 runner 的 FFmpeg `9.0.1_1` / mpv `0.41.0_9` 与已锁定 `9.0.2_0` / `0.41.0_10` 不同。版本校验保持有效，未改用latest、未下调锁、未关闭校验。Node/Chromium准备、PyInstaller、Mach-O、签名和搬移均未执行。6件原生产物回执共1,193,755字节已下载并逐件对照上传SHA，Actions artifact `11168791260` 仅含回执，没有应用；线上保留1天，本地交接持久保留。

首次后本地9项公式检查仍不足；本轮改为锁定官方core0211e9c2及两份配方SHA，原目标版本/bottle摘要保持，两个原官方归档已经实际下载校验可取得。新同版本runner镜像明确预置2026-09-07 core a7496e08、HOMEBREW_NO_AUTO_UPDATE=1；官方该core定义为9.0.1_1/0.41.0_9，匹配首次实际倒入。首次未保存API缓存/完整环境，不能排他断言缓存导致。确定问题是旧brew install未消费锁；安装后公式版本不是已装revision证据。后续原生运行必须有新的单次授权及新额度复核，本轮不重跑。

产品0.5.0，Mac独立build_id；原Windows Setup和旧C封存。没有公开Mac下载链接，内部实验与有限源码C的范围分开。
