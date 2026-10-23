# macOS 实验验证状态（0.5.0）

2026-10-23：当前检查对象已是公开 0.8.3 与 Sonoma 相容候选，请先看[新版相容性与证据矩阵](macos-compatibility.zh-TW.md)。以下保留 0.5.0 历史结果，不移植为当前候选或 14.4.1 的通过结论。

## 2026-10-02 原生CPU主流程验收通过（历史）

用户授权顺序CI直到验证成功或实际新增计费10USD。本次三场均attempt1；最终run36975908980/job110739579529严格success，已停止新增测试。专用分支codex/macos-desktop-0.5.0-20261001普通追加；最终工作流与准确完整私有源码均cfe9b13dafa7c4aa068034a7a9fd9fcf601c6f1b，没有把旧结果移植给新源码。

| 范围 | 最终真实状态 | 原生证据 |
|---|---|---|
| 固定媒体与真实.app | 通过 | 官方固定core/ffmpeg-full9.0.2_0/mpv0.41.0_10，bottle归档摘要、实际keg/receipt/工具路径与执行摘要分开；arm64、动态库和ad hoc签名 |
| 解压搬移和正常启动 | 通过 | 独立中日文目录，脱离源码/构建venv/Homebrew PATH；二进制和LaunchServices两正常入口 |
| GUI冷准备SenseVoice | 通过 | 同一venv入口安装、登记、真实生产worker导入FunASR1.4.1和模型就绪 |
| 无密钥中文首页识别 | 通过 | 实际Start触发正式CPU模型非缓存推理，非注入字幕，原识别“兔白”→“to白”偏差保留 |
| Studio画面与编辑 | 通过 | 四处decoded/composed彩色画面及原生整窗截图；中文修改、两次剪切、撤销重做、保存重开 |
| 四格式实际字幕按钮 | 通过 | ASS/JSON/SRT/TXT各4cue，中文、时间轴、说话人映射回读 |
| 实际字幕短视频 | 通过 | 12秒、360帧、640×360 H.264与AAC，全流解码；实际帧显示编辑后的中文，音频RMS0.044796 |
| 正常退出和重启新任务 | 通过 | 另一10秒媒体实际SenseVoice非缓存推理；runtime/model文件SHA/大小/mtime及登记完全相同，无override或重下载 |
| 定向回归 | 通过 | 本机及准确冻结90pass/1skip；Mac原生89pass/2明确平台skip；不等于全仓库宽测 |
| 额外范围 | 未验 | 整模型MPS、人工听感、物理IME、长任务、Developer ID/公证；已有MPS可用/tensor和原生VideoToolbox独立证据保留 |

最终CI真实应用ZIP485597331bytes，SHA256643070ba92ae46233e5a802963b2c9723606cec0cd97f926ef738bf7c1236b94。CI先归档应用再执行GUI/model，前两场包均保留；本地传输/成员SHA/CRC状态及准确路径见内部releases/0.5.0-macos-continuation-20261002-r6/HANDOFF.md。这是私有ad hoc实验候选，尚无公开安装包或下载按钮，未发布Release/DMG。

首场36973039995/61ee011849f235c55e316a72d8a9ed4b8c40132f虽CI success、实际视频导出通过，Studio整窗主预览黑，未视为完整成功。第二场36974301563/e0e8c5ceb360bc0d53f400709b7cb654179100e8避开winId后，实际decoded0.990723/148帧/painted59且非native，但composed0，严格失败，编辑导出未执行；独立模型/Home/restart通过。生产SubtitlePositionOverlay透明Source fill会擦除下方Qt共享backing store的视频；真实Qt控件反例可重复，修正仅Qt分支，Windows mpv原清空行为不变。第三场保持原彩色门：ready/cut-before/cut-after/reopened composed比例0.641113/0.647949/0.648682/0.617432，原生PNG/整窗/成片均可见真实视频与中文，验证此修订。

结束观察1725.7/2000included、gross10.37及discount10.37、实际应付0，显示可能滞后。三个job按整分12/13/14合39分钟，保守未结算计算毛额2.418USD；现存所有产物未来费用上界约0.03882USD，仍低于10USD。本次账号Actions0→10且StopYes/通知保留，仓库10/其他产品0保持；预算不是充值余额证明。每场600MiB/1天只应用和必要诊断，诊断先上传，不删旧Actions，不上传模型/venv/cache。没有云端AI、WindowsSetup重建、Docker/VM恢复、main/可见性/Release/GPL/旧refs改写。有限C仅允许源码增量，完整私有输入/品牌/样本/运行对象不因验收成功而自动公开。

## 2026-10-02 r5五次追加测试结束状态（历史快照）

用户追加五次、最多10美元测试授权已全部实际执行，均attempt1/严格failure，没有第六次。最接近完整验收的是第四场；第五场在新的媒体取得前门停止，不覆盖或借用第四场结果。

| 次序 / run | source = workflow SHA | 实际停止位置 |
|---|---|---|
| 1 / 36965034989 | 4f00e5cd8bafca7ae580228e5e1f17ebf08ee567 | 音频worker继承GUI audit，QApplication/QCoreApplication单例冲突 |
| 2 / 36966259582 | 227d457083cec999ca480298f825c8e9a8815bbe | Studio编辑保存通过；导出面板误用Windows ffmpeg.exe路径 |
| 3 / 36967650706 | 84a840663e1a067fb07558360aa92537dc2b840b | 音频正常，暂停视频最新栅格被背压下的心跳覆盖；就绪超时 |
| 4 / 36969434185 | b407cae9f6919a2227dfa1d2d64e8c2f3119a639 | Studio/四字幕导出通过；短视频实际报No such filter: ass |
| 5 / 36971433917 | 6bab5e71cffc2496137f518eb484d35ebb2ada89 | 官方full bottle安装和真实FFmpeg运行完成；新滤镜解析器误拒绝两列标志输出，无.app |

第四场真实应用472759515bytes，SHA25620a97ca290ad4cb5ccd3af756d3e589c619624508a8dbfa05d59b75c8a503e39，已下载官方Actions归档、逐文件摘要/大小与.app ZIP18620成员CRC核验。第五场仅有258253bytes诊断归档（SHAff0637f32435f2cbb110954b844ae4a45cbc2a92000a29b8ae62d9407bb914ff），没有应用。

| 范围 | 第四场实际状态 | 第五场实际状态 |
|---|---|---|
| 媒体身份、arm64.app、动态库/ad hoc签名 | 通过（标准FFmpeg锁） | 媒体前门失败；应用未执行 |
| Unicode解压搬移、脱离构建环境两路正常启动 | 通过 | 未执行 |
| 冷GUI工坊SenseVoice CPU、正式worker导入 | 通过 | 未执行 |
| 无密钥Home实际Start、中文非缓存识别/保存 | 通过 | 未执行 |
| Studio准备、编辑/两剪切/撤销重做/保存重开 | 通过（ready5612.806ms，真实CoreAudio缓冲/NoError与暂停帧就绪） | 未执行 |
| 实际ASS/JSON/SRT/TXT字幕按钮和内容/时间轴回读 | 通过（四种各四cue，中文编辑与时间轴/说话人校验） | 未执行 |
| 短视频按钮压制 | 实际执行并失败：缺ass滤镜；后续解码未执行 | 未执行 |
| 正常退出/重启，另一10秒媒体真实新推理 | 通过；同profile，runtime/model文件和登记不变，无重下载/override | 未执行 |
| 独立QVideoSink真帧/中文栅格与VideoToolbox探针 | 通过，不能代替实际Studio完整音画验收 | 未执行 |
| 整模型MPS/人工听感/物理IME/长任务 | 未验；保留先前MPS可用与tensor证据 | 未验 |

真实Studio截图02-recognized-edited-reopened.png及cut-frame截图中主预览区是黑色；现有readiness与独立真帧探针不能证明这条产品流程可见画面正确。保存这一观察，尚未分解绘制/截图机制原因，不把Studio完整音画显示声明为通过。

媒体功能修订只切换到同一固定官方core的ffmpeg-full9.0.2_0 arm64_sequoia bottle，mpv0.41.0_10不变，详见[准确媒体输入](../../packaging/macos/MEDIA_INPUTS.md)。第五场归档/bottle、keg/receipt/core、FFmpeg执行路径/SHA/arm64/版本输出已取证，但滤镜检查错误要求三列标志，真实FFmpeg9为两列，七种所需滤镜实际均在原始输出中。本地已修正解析并用本场完整输出回放和回归验证：85通过1跳过；初次复测另有Windows临时venv清理锁失败，随后独立6项与完整85项复测通过，原失败XML保留。修正未推送、未新原生运行；full库打包/搬移/视频仍未验，不将旧应用标为已含full媒体。

原生定向测试前四场依次74/76/78/79通过，各2平台跳过；第五场只有早期真实双venv身份6项通过，昂贵运行库与完整套件未执行。本轮零云端LLM调用。结束账单新观察1322.7/2000included分钟，gross7.95USD全部折扣、应付0，Actions存储取整0/0.5GB（8%），25live产物5306815812bytes；仓库10USD/账号0USD StopYes原样保留，未改预算或将预算当充值余额。四份新应用、五份诊断和五份可信私有源码bundle全部保留，线上1天留存、本地完整归档。未公开安装包、未发布Release/改可见性/main/旧refs、未恢复Docker/VM或重打Windows Setup。有限C只补允许提供的自有修复代码，私有完整输入/品牌/QA样本/运行产物不进入其范围。

## 2026-10-02 前两次worker修复原生结果（历史快照）

最新run36960889684 / attempt1，source与workflow commit均ce3f9ff58da7f9c6353e7ebd61ff3e6d6fe46952。首场36958646030 / 6252d6c59d85bdda494a3a848de15ce7d1718fe9给出新失败后，定点修正再使用第二场。两次新授权全部使用，均严格failure；没有第三次或自动重跑。

| 范围 | 真实状态 | 边界 |
|---|---|---|
| 固定媒体、arm64.app、外链/签名 | 通过 | 保持既有媒体输入，ad hoc签名，不是Developer ID/公证 |
| Unicode解压搬移、正常入口启动 | 通过 | 新目录；最小PATH；二进制和LaunchServices两路可见窗口/资源并正常退出 |
| GUI工坊冷准备SenseVoice CPU | 通过 | 固定五文件、生产worker真实加载/推理ready；安装/返回/登记同一venv |
| 首页无密钥中文识别、工程保存 | 通过 | 实际Start、独立生产worker非缓存推理，四条中文cue；原始“兔白→to白”偏差保留 |
| 识别工程进入Studio | 失败 | 等待匹配工程且readiness.ready超时；缺准备子阶段证据，尚不能断言具体根因 |
| 中文编辑、剪切、撤销/重做、保存重开 | 未执行 | Studio未就绪 |
| 四格式字幕GUI导出、短带字幕视频/解码 | 未执行 | 无对应输出，不使用独立栅格探针代替 |
| 正常退出重启、同profile第二短任务 | 通过（缓存复用） | 登记/runtime/model大小SHA/mtime不变，无override/重下载；相同媒体ASR缓存命中，非第二次新推理 |
| QVideoSink真帧/中文栅格、VideoToolbox短探针 | 通过 | 独立机制检查，不是完整Studio或整模型MPS |
| 整模型MPS、物理IME、人工听感、长任务 | 未验 | 既有MPS可用/tensor结果保留，未扩矩阵 |

真实应用ZIP472754080bytes，SHA-2568a88b57947bc132b3dbd0b51fb7c27b18f9e6a4d9422f833bfe79ccb4df979b8；先归档后验收，失败仍保留。产品版本0.5.0，私有实验候选，无公开安装包/Release/失效下载按钮。最新原生72通过2跳过，早期真实POSIX6通过；Windows130通过1跳过，准确私有输入本机128通过1跳过/2明确Windows夹具排除。

在该次真实安装，venv入口与其resolve后的基础Python二进制相同，但环境不同：保留入口时sys.prefix与site-packages为venv、FunASR1.4.1实际导入；resolve反事实prefix为base且find_spec为空。这证明入口解析故障机制，旧baseline未留argv/prefix，不能断言为旧失败唯一原因。共享安全边界与冻结子进程分流保留。

Action固定为支持Node24的已审阅revision；产品Node/Remotion不变。两次均60分钟单job上限；诊断先上传、真实app后上传，600MiB合计上限/1天留存按当次额度核算，不上传模型/环境/私人缓存。结束账单新观察744/2000min、应付0、预算0StopYes、storage取整0/0.5GB(7%)，未改预算。旧五份应用、两份新应用、回执和完整私有源码长期保留；私有refs/品牌/样本不自动纳入有限C或可公开历史。

## 以下为前五次运行的历史快照

最新私有原生run `36893768101` / attempt1，workflow ref为 `codex/macos-desktop-0.5.0-20261001`，source与workflow commit均 `61ccea07e22ba8434030a2561779da801b4ad7c4`。标准macos-15 Apple Silicon单job、60分钟上限；main保持。本轮先追加两次、再追加三次，五槽均实际使用，没有自动重跑。

| 层级 | 最新真实状态 | 证据边界 |
|---|---|---|
| A 媒体、运行库和.app | 通过 | 固定公式/bottle/keg/receipt/路径/执行SHA、arm64、外部动态库与ad hoc签名 |
| B 解压搬移启动 | 通过 | ZIP在新中文/日文路径解压；两路最小PATH正常入口，实际MainWindow和资源回执、正常退出0 |
| C GUI SenseVoice准备 | 失败 | 工坊冷安装依赖、五模型文件校验完成，加载worker报No module named funasr；ready未取得 |
| D 中文Home→Studio | 未执行 | 模型未ready；识别、编辑/剪切/撤销重做/保存重开/实际字幕按钮及短视频不伪造通过 |
| E 独立内嵌预览 | 通过 | Mac Qt QVideoSink真帧、暂停seek、中文栅格/合成、焦点/QWE、保存/撤销重做/Replace、倍速/EOF/EOF后seek；不代表完整Studio音画/特效 |
| F 硬件/MPS/人工 | 分列 | VideoToolbox实际25帧且禁软件fallback通过；MPS可用/tensor通过；整模型MPS、听感、物理IME、长任务未验 |

最新真实应用ZIP `472740506` bytes，SHA256 `860d351369eec2583d7b89387d50a4304310176fe5dd7c4185d736f1f7914cd6`。应用先归档，后续失败保留；内部包没有公开下载按钮、Release或DMG。原生定向回归61通过/2平台跳过；冻结准确源码本机62通过/1跳过独立记录，不移植平台结果。整job严格failure，continue-on-error步骤的API success不代表全流程通过。

工坊日志证明funasr1.4.1安装完成、pip check通过、SenseVoice固定五文件校验完成；随后正式worker报ModuleNotFoundError。worker完整解释器/前缀未保留，当前代码候选Path.resolve可能追随venv符号链接成为基础Python是待验证推断。保留失败前有效结果；没有把100%文件进度改成模型ready，没有注入识别文本或云端AI请求。

## 本轮其余准确源码

| run（均attempt1） | source = workflow commit | 真实结果 |
|---|---|---|
| 36886410053 | e132fda98f284928771e8a7c2e3bf6f77773d275 | app/媒体/签名/搬移通过；正常启动缺回执，焦点探针失败；模型/Studio未执行 |
| 36888709835 | e0a4994cae658d657705921a90a510837e741c17 | app/媒体/签名/搬移通过；启动工坊badge缺platform_unavailable而KeyError；预览仅Replace失败；模型/Studio未执行 |
| 36890647270 | 5a499d6e75a4c2251bd610dfc7046e1661a7d78e | app和全部独立预览通过；两路实际窗口/资源可见但75秒超时，startup仍失败 |
| 36892355738 | ce9874df73954de8c05ff9f7c71a026fd9137ca2 | app和全部独立预览通过；SpringDialog动画finished前退出后重进事件循环，两路超时仍失败 |

工坊徽标、Qt无Mac Replace标准绑定时Command-Option-F回退、真实SpringDialog结束后的探针退出分别定点修订；槽5原生通过。先前标准QDialog测试没有覆盖关闭动画，换真实SpringDialog确实复现失败后才修订；旧失败回执不改写。新分支四个普通追加提交，旧push CI暂时暂停后每次恢复active；所有旧运行、附件、refs保持。

## 首次媒体失配的历史证据

首次 `36875057224` / source `596bc062d1e7c0f72508c8edcb60c0fbbe965eb2` 在PyInstaller前失败：未消费锁的brew install倒入FFmpeg9.0.1_1/mpv0.41.0_9，目标是9.0.2 revision0/0.41.0 revision10。当次CPU导入、38回归/2跳过与MPS tensor有效，但无.app/GUI模型/Studio。首次API缓存、完整环境、installed-before、实际receipt/路径/摘要未保存，不能断言缓存是排他根因。

后续同镜像原生观察有Sept7 core a7496e08与NO_AUTO_UPDATE=1，该官方快照定义匹配旧版本；这是后次观察，不倒填成首次证据。原目标版本/bottle摘要仍可取得，保持不变，新增准确官方core0211e9c2及两公式SHA。安装消费固定官方输入，由Homebrew处理依赖/重定位，隔离并恢复runner原tap；归档SHA与解压后执行SHA分别验证，builder仅消费已验证准确路径。

第二次旧run `36882470527` / source `d41b3359985d6bc5e82f55b96dbf316b30a30a08` 在媒体前因runner原core的rustup/额外openssl配方被干净检查拒绝，无.app；该次诊断保留，随后独立core隔离修订已在本轮实际原生通过。

五份应用和诊断长期留本地，线上仅1天；仅应用ZIP与必要浅层回执，不上传模型、构建runtime或私人缓存。每次新读取当次免费额度和0美元Stop预算；结束显示310/2000分钟、Actions应付0、预算0StopYes，存储0/0.5GB有取整与延迟。2GiB脚本防护上限不是账户容量，实际大小/留存按当次核算。

产品0.5.0、Mac独立build_id，Windows repair/Setup封存，Docker和VM不恢复。完整私有输入、品牌、CI样本、refs/运行/应用不属于有限公开C。有限C仅沿用允许范围增量提供自有修复源/测试/说明与必要GPL/第三方声明，不证明全部远端历史可公开。
