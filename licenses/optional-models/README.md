# 可选 AI 模型与独立许可 / Optional model licenses

本目录的 [manifest.json](manifest.json) 是模型工坊、关于和 worker 共用的固定元数据；`dependencies.lock.json` 同步提供下载清单。每个文件有大小、SHA256、来源 revision 和完整性来源。正式许可证保留上游原文，以下说明不是法律解释。

| 组件 | 固定 revision | 代码 | 权重 / 材料 |
| --- | --- | --- | --- |
| Microsoft VibeVoice-ASR-Streaming-1.5B | `4262d23d8a539a6530cf64fbd0b1751ef9a30853` | MIT | [MIT 原文](vibevoice_1_5b/LICENSE)，[上游说明](vibevoice_1_5b/README.md) |
| Microsoft VibeVoice-ASR-Streaming-7B | `60d858b518b4e19d404af3737f848fc185b30177` | MIT | [MIT 原文](vibevoice_7b/LICENSE)，[上游说明](vibevoice_7b/README.md) |
| BUT-FIT DiariZen WavLM large s80 md v2 | `027b3e221b9d81dce2be794084f1dbd3ba2da403` | MIT | CC-BY-NC-4.0；[MODEL_LICENSE 全文](diarizen/MODEL_LICENSE)，[README 全文](diarizen/UPSTREAM_README.md) |
| pyannote WeSpeaker VoxCeleb ResNet34 LM | `837717ddb9ff5507820346191109dc79c958d614` | 独立上游代码许可 | CC-BY-4.0；[上游说明](diarizen_embedding/README.md) |
| DiariZen PLDA / xvec_transform | 同 DiariZen v2 检查点 | 独立上游代码许可 | CC-BY-4.0；[原文](diarizen/plda/LICENSE) |

DiariZen 上游代码固定 `844f5555b0a98acd0931511fc641a8c5b8ba92c7`；VibeVoice 代码固定 `1541f590c7099820f10ea012f48d2399282df69f`。源地址和逐文件记录见 manifest 的 sources 以及 `third_party/*/UPSTREAM_SOURCE.json`。这些源副本保留作者与 MIT 许可，未改上游文件；本地兼容适配在 GPL-3.0-only 的 `optional_model_worker.py`，包括现代 Torchaudio 的 SoundFile 解码与已校验官方 pickle 权重的 Lightning 加载兼容。DiariZen 使用该固定仓库自带的 pyannote.audio 分支，从保留源码构建；不是 Community-1。

DiariZen 的 MODEL_LICENSE 同时含学术及其他非商用用途、研究用途与许可兼容性说明；README 另有研究/学术说明。这里保留完整材料而不挑选宽松句子。功能默认不启用，仅提供用户明确选择的本地研究/实验入口。首次下载、启用或关联本地权重需确认具体 revision/许可摘要；同版本确认记录保存在用户本地。取消不影响其他后端。

DiariZen v2 的模型权重采用 CC-BY-NC-4.0，上游另有研究用途与许可兼容性说明。本集成提供本地研究/实验入口，不授予额外商业权利。软件免费并不自动代表所有使用方式符合模型条款。商业制作、付费服务等用途应核实具体授权；程序不判定字幕输出的法律性质。独立下载、独立进程和确认提示不自动解决组合许可或正式再分发条件。

自有代码继续 GPL-3.0-only，历史生效分界为 0.2.6-test.3。第三方权重不会因此改授 GPL，DiariZen 的 NC 条件也不套到 VibeVoice 或整个软件。程序不为字幕正文增加水印，也不自动改变字幕输出许可。

两款 VibeVoice 使用一张家族卡，各自固定目录、检查点身份、下载及推理状态；查看版本不改变任务。权重完整、环境准备和实际离线推理通过是不同状态。当前平台未验证不代表可用；Windows 成功不自动代表 Mac 成功。完整模型权重、辅助权重不默认打进安装器或源包。

对应源码与材料须与实际构建输入配对。模型权重、wheel、预编译工具不能一概称为对应源码；既有原生组件源码和组合许可缺口继续保留。正式对外集成/再分发范围、DiariZen 上游表述的兼容性以及既有材料缺口仍待确认。

English: Project-owned code remains GPL-3.0-only since 0.2.6-test.3. Upstream code, model weights, auxiliary weights and binary dependencies retain their separate licenses. DiariZen v2 is an optional local research/experimental feature with CC-BY-NC-4.0 weights and additional upstream research/compatibility wording. The complete originals are retained; consent and process isolation do not settle redistribution compatibility. VibeVoice code and both pinned Streaming checkpoints are marked MIT. No model weights are included by default, and untested platforms remain unverified.

日本語：自有コードは 0.2.6-test.3 以降 GPL-3.0-only を継続します。上流コード、モデル重み、補助重み、バイナリ依存物はそれぞれのライセンスに従います。DiariZen v2 は任意のローカル研究・実験機能で、重みは CC-BY-NC-4.0、上流の研究用途・互換性に関する説明も全文保持します。同意やプロセス分離だけで再配布条件が解決するわけではありません。VibeVoice のコードと固定した両 Streaming チェックポイントは MIT 表記です。重みは既定で同梱せず、未検証のプラットフォームは未検証と表示します。
