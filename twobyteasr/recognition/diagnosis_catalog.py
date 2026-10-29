"""Known recognition problems, written once for people and for the AI (2026-10-23).

Each entry is a problem users have actually hit: what they saw, why it
happens, and what to do. ``diagnosis_checks`` recognizes an entry from a task
report; entries with ``ai_only`` have no reliable local signal and only go to
the AI analysis as knowledge. Texts are Simplified Chinese source strings
(translated through the locale files like other UI text).

Add an entry when a new user report is understood; keep ``fixed`` honest (the
date and channel it was fixed in, never a guess).
"""
from __future__ import annotations

from dataclasses import dataclass

# Buttons a finding can offer; the window maps them to existing app actions.
ACTION_LABELS = {
    "ai_settings": "设置 AI 与 API Key…",
    "cloud_asr_setup": "配置在线识别服务…",
    "choose_plan": "更换识别方案…",
    "pick_primary": "选择主力转写模型…",
    "pick_timeline": "选择字幕时间轴模型…",
    "pick_review": "选择文字复核模型…",
    "model_workshop": "打开模型工坊",
    "retry": "重试失败项",
    "mosi_resplit": "切成小段再交 MOSI…",
    "recover": "恢复已有识别结果…",
    "glossary_proofread": "AI 词库校对…",
    "studio": "打开字幕工作台",
    "update": "检查更新",
    "support": "回报问题…",
}

STAGES = {
    "input": "素材与音频",
    "environment": "运行环境与模型",
    "asr": "语音识别",
    "timing": "字词时间与时间轴",
    "ai_text": "AI 断句与校对",
    "segmentation": "断句与字幕保真",
    "output": "保存与输出",
    "settings": "设置",
}


@dataclass(frozen=True)
class KnownIssue:
    id: str
    stage: str
    severity: str
    title: str
    # What the user saw (quoted text or a plain description).
    symptom: str
    # Why it happens, in plain words.
    cause: str
    # What the user can do.
    advice: str
    actions: tuple[str, ...] = ()
    # One plain line for the completion page strip ("" = title only).
    short: str = ""
    # When it was fixed ("" = not fixed / not a bug). Shown as a note.
    fixed: str = ""
    # More specific entries hide these generic ones when both match.
    supersedes: tuple[str, ...] = ()
    # No reliable local signal: knowledge for the AI only.
    ai_only: bool = False


# How the program works, for the AI. Keep it short and factual.
PIPELINE_OVERVIEW = """\
2ByteASR 是 Windows 上的本地字幕软件（也有 macOS 版）：把视频里的话变成可编辑的字幕工程，再在「字幕工作台」里修改、导出。

一个文件的识别流程（任务报告 stages[] 里能看到各步）：
1. 准备音频：统一成 16 kHz；同时做语音活动检测（FireRedVAD），找出有人说话的区间。
2. 主力转写：写出文字主稿。可选本机 MOSS-Transcribe-Diarize（质量最好，要 NVIDIA 显卡约 10 GB 显存，同时分辨说话人）、本机 SenseVoice（快、显存小，但没有字级时间）、Qwen3-ASR、FireRedASR2-LLM，或在线 API（MOSS Pro 云端转写、通义 Qwen 在线识别、讯飞等，需要对方的 API Key）。设置在 settings.models.primary_asr_backend。
3. 字幕时间轴（字词时间）：给每个字找到它在录音里的时刻。中文用 FireRedASR2-AED（settings.models.firered_asr_backend），日语、英语等改用 Qwen3-ForcedAligner 对齐模型，日语可再加 CTC 校正句首；也可选 MFA（实验）。时间轴设为 off 时没有字级时间，字幕起止只能按主力转写的段落估算或均分，字幕时间会不准、长句会被硬切。
4. 文字复核：Qwen3-ASR 等第二个模型再听一遍，三路（主稿 + 字级证据 + 复核）对照，只在有把握时改字。
5. 词库：启用的术语库把常见误识别替换成正确写法。
6. AI 校对（可选，settings.switches.enable_ai_polish）：用户配置的文字 AI（DeepSeek、通义等，需要 API Key）按词库和上下文改错字，受保护规则限制，不合规的修改会被拒绝；失败或没有 Key 时回到原文。
7. 断句（settings.switches.use_ai_grouping 决定是否用 AI）：把长段切成一条条字幕（中文约 8–16 字、最长约 5 秒）。AI 断句失败、超时或结果不合规时退回本地规则断句。
8. 字幕保真检查：最后核对成片字幕的文字、数字与原文逐字一致；不一致时依次用断句阶段的字幕、本地重建来恢复，仍不一致才让整个文件失败（报「字幕保真检查未通过」）。这是保护：宁可失败也不交出丢字、改字的字幕。
   最常见的诱因：没有字级时间（时间轴关闭、SenseVoice / 在线 API 主力）+ 不开 AI 断句时，本地规则只能按字数硬切，稀疏的说话会被切成一字一条，数字和量词容易被拆开。
9. 定稿时间、翻译（可选）、保存字幕工程（.2byteproj）并写任务报告。

几个概念：
- 文字 AI 的 API Key 在「设置 → AI 模型与密钥」；AI 校对和 AI 断句共用。没有 Key 时这两步改用本地规则，任务照样完成，但字幕断句与错字处理会差一些。
- 在线识别服务（MOSS Pro、Qwen 在线识别等）的 Key 是另一套，在首页「识别方案」里配置。
- 「联网核验」是可选的术语联网查证，没配置或服务商不支持时只是没执行，不影响字幕。
- 任务报告 JSON 里：status 是总状态；result.error 是失败原因；stages[] 是每一步的状态与耗时；events[] 是详细事件（带 fallback / failed / rejected 的多半是问题）；review_items[] 是需要人工检查的字幕；settings 是这次实际用的模型与开关（不含 API Key）。
- 读报告时要注意：失败的任务 review_items 是空的，原因只在 result.error、stages[] 和 events[]；settings 里没有语言，语言看 TASK_LANGUAGE 事件（requested 是用户选的，disagrees_with_transcript 表示识别出的文字其实是另一种语言）；没填 Key 和手动关掉 AI 在报告里看起来一样（enable_ai_polish / use_ai_grouping = false，polish_provider = disabled）；报告不记录程序版本；开跑前就失败（环境检查、缺模型、没有 NVIDIA、云端识别没配置）的任务没有报告，只有一句错误。
- 在线识别失败的错误里常带 [2BYTEASR_API_ERROR] {"category": …}，category 是 key / permission / balance / rate_limit / network / file_access / server / resubmit_needed / content_blocked 之一；code 是 content_blocked 或 content_rejected 时，是服务商的内容安全审查拦下了那段音频（原样重交多半还会被拦）。
"""


def _issues(*entries: KnownIssue) -> dict[str, KnownIssue]:
    table: dict[str, KnownIssue] = {}
    for entry in entries:
        if entry.id in table:
            raise ValueError(f"duplicate known-issue id: {entry.id}")
        table[entry.id] = entry
    return table


ISSUES: dict[str, KnownIssue] = _issues(
    # Order = display order among findings of the same severity and certainty.
    # ---- 素材与音频 ------------------------------------------------------
    KnownIssue(
        "media_unreadable", "input", "blocker", "素材读不出声音",
        "任务很快失败，错误里有 Invalid data、moov atom not found、没有音频流、ffmpeg 失败之类的字样。",
        "视频文件损坏、还没下载或录制完，或者里面没有音轨（例如只录了画面），软件取不到声音。",
        "先用播放器确认视频能正常播放、有声音；录制中的文件等录完再识别；可以用剪辑软件重新导出一份再试。",
        supersedes=("worker_crashed", "unknown_failure"),
        short="视频文件损坏、没录完或没有音轨，取不到声音。",
    ),
    KnownIssue(
        "language_mismatch", "input", "problem", "字幕语言和视频里说的话不一致",
        "选的字幕语言（例如日语）和视频里实际说的语言（例如中文）不同；字幕很少、乱码，或断句、保真检查失败。",
        "软件按首页「字幕语言」选择识别和断句规则。选错语言时，模型会用错误的语言去听、断句规则也对不上，结果往往很差甚至失败。",
        "在首页把「字幕语言」改成视频里实际说的语言（不确定就选「自动」），再重新识别。",
        actions=("choose_plan",),
        short="首页选的字幕语言和视频里实际说的语言不同。",
    ),
    KnownIssue(
        "empty_result", "input", "blocker", "没有识别出任何字幕",
        "任务结束了，但字幕是 0 条，或报「没有生成有效文字」。",
        "这段音频里没有识别出人声：可能整段是音乐或游戏声、声音太小、视频的音轨是空的，或者字幕语言选错，模型认不出这种语言。",
        "播放素材确认人声清楚；检查首页「字幕语言」是否和视频里说的语言一致；多音轨的视频先导出包含人声的那一轨。",
        actions=("choose_plan",),
        short="这段音频里没有找到人声，或字幕语言和视频里说的话不一致。",
    ),
    KnownIssue(
        "sparse_result", "input", "quality", "字幕比正常少很多",
        "字幕条数和视频长度相比很少（每分钟只有几条），很多说话的地方没有字幕。",
        "常见原因：字幕语言和实际语言不一致；背景音乐或游戏音效盖过人声；主力转写模型对这种语言支持差；在线识别服务只返回了一部分。",
        "先确认首页「字幕语言」；人声小的素材可换「本地识别」方案（MOSS）；外语视频选对应的方案（「日语」或「外语」）。",
        actions=("choose_plan",),
        short="和视频长度相比字幕太少，可能语言选错或人声被背景声盖住。",
    ),
    KnownIssue(
        "media_decode_stall", "input", "blocker", "读取音频太久没有反应",
        "报「音频解码长时间无响应（超过 N 秒），ffmpeg 已被终止」。",
        "素材在很慢的网络盘、移动硬盘或同步盘上，或者文件本身有损坏，解码一直卡着。",
        "把视频复制到本机硬盘后再识别；仍然卡住就用剪辑软件重新导出一份。",
        actions=("retry",),
        supersedes=("worker_crashed", "unknown_failure"),
        short="读取音频卡住了，素材可能在慢速磁盘上或已损坏。",
    ),
    KnownIssue(
        "studio_input_changed", "input", "blocker", "识别过程中素材或时间轴变了",
        "报「识别启动后素材已改变」「当前时间轴为空，无法识别字幕」「时间轴音频准备失败」或「时间轴音频长度与剪辑快照不一致」。",
        "在字幕工作台里识别时，软件会先锁定当时的素材和剪辑；识别中移动、改写了素材，或时间轴是空的、音频导不出来，就会停止，避免字幕和画面对不上。",
        "识别期间不要移动、替换或编辑素材；确认时间轴上有带声音的片段后重新识别。",
        actions=("studio",),
        supersedes=("unknown_failure",),
        short="识别期间素材或时间轴被改动，或时间轴没有可用的音频。",
    ),
    KnownIssue(
        "vad_lightweight_fallback", "input", "tip", "人声检测改用了轻量备用方案",
        "报告里有 vad_backend_selected（reason = main_runtime_missing），或第 3 步是「轻量静音与人声区间检测」。",
        "FireRedVAD 要用主运行环境；环境不可用时软件改用轻量静音检测，字幕照常生成，但人声区间没那么准。",
        "在模型工坊修复主运行环境后再识别。",
        actions=("model_workshop",),
    ),
    # ---- 运行环境与模型 --------------------------------------------------
    KnownIssue(
        "model_missing", "environment", "blocker", "模型没有下载或文件不完整",
        "错误里提到「未完整安装，请先在模型工坊下载」、找不到模型或权重文件、model not found。",
        "这次方案要用的本机模型还没下载，或者下载中断、文件被杀毒软件删掉了一部分。",
        "打开模型工坊，找到这次用的模型，点「安装」或「修复」；下载慢可以在下载窗口换下载来源，断点会继续。",
        actions=("model_workshop",),
        supersedes=("worker_crashed", "unknown_failure"),
        short="要用的本机模型没有下载完整。",
    ),
    KnownIssue(
        "runtime_broken", "environment", "blocker", "模型运行环境缺少组件或损坏",
        "错误里有 No module named、DLL load failed、ImportError、worker runtime missing、缺少新流水线组件。",
        "模型在自己的 Python 运行环境里运行；这个环境没装完、被移动或删除，或者缺少系统组件（例如 VC++ 运行库）。",
        "打开模型工坊，在对应模型卡片上点「修复独立环境」；仍不行就把程序更新到最新版后再修复一次。",
        actions=("model_workshop", "update"),
        supersedes=("worker_crashed", "unknown_failure"),
        short="模型的运行环境没装完或被移动、损坏。",
    ),
    KnownIssue(
        "no_primary_model", "environment", "blocker", "还没有可用的主力转写模型",
        "报「当前没有可运行的主力转写模型」或「尚未选择主力转写模型」。",
        "首页的主力转写没有选，或者选的模型还没下载、这台电脑跑不了。第一次下载完模型后，首页有时要去一次模型工坊才会显示已选择。",
        "打开模型工坊选好并下载一个主力转写模型，或配置在线识别服务；然后回到首页确认显示已选择。",
        actions=("pick_primary", "model_workshop", "cloud_asr_setup"),
        supersedes=("worker_crashed", "unknown_failure"),
        short="主力转写模型没有选或没有下载。",
    ),
    KnownIssue(
        "model_dir_unavailable", "environment", "blocker", "模型所在的磁盘找不到了",
        "报「已登记的模型目录不可用：<路径>。请恢复磁盘连接或在路径登记中更正位置」。",
        "模型放在移动硬盘或另一个盘上，这个盘没接上或盘符变了。",
        "接回磁盘，或在模型工坊的「存储管理」里改成新的位置；不需要重新下载。",
        actions=("model_workshop",),
        supersedes=("model_missing", "worker_crashed", "unknown_failure"),
        short="放模型的磁盘没接上或盘符变了。",
    ),
    KnownIssue(
        "model_download_failed", "environment", "blocker", "模型或运行环境下载失败（模型工坊）",
        "在模型工坊下载时出现「所有下载来源都没有连通」「权重不完整」，或进度一直停在 Downloading torch。",
        "网络连不上下载来源，或代理、加速器拦截；有些模型（例如 MFA）只在 Hugging Face 上。",
        "在下载窗口里换下载来源（ModelScope / HF 镜像），断点会继续；需要时打开代理的 TUN 模式；仍失败可以「导出部署诊断」发给开发者。",
        actions=("model_workshop",),
        fixed="2026-10-22 起下载窗口会显示卡在哪一步并可一键换来源",
        ai_only=True,
    ),
    KnownIssue(
        "no_cuda", "environment", "blocker", "这台电脑没有可用的 NVIDIA 显卡",
        "错误里有 CUDA not available、no CUDA GPUs、Torch not compiled with CUDA、未检测到 NVIDIA。",
        "MOSS、FireRed 等本机模型需要 NVIDIA 显卡和驱动；这台电脑没有，或者显卡驱动太旧、没装好。",
        "没有 NVIDIA 显卡时改用「API 转写」方案（在线识别），或在模型选择里换成 SenseVoice；有显卡的话先更新 NVIDIA 驱动再试。",
        actions=("choose_plan", "cloud_asr_setup"),
        supersedes=("worker_crashed", "unknown_failure"),
        short="本机模型需要 NVIDIA 显卡，这台电脑没有或驱动不可用。",
    ),
    KnownIssue(
        "gpu_out_of_memory", "environment", "blocker", "显存不够",
        "错误里有 CUDA out of memory、显存不足、分配失败。",
        "本机模型（尤其 MOSS，约需 10 GB 显存）一次要占用很多显存；同时开着游戏、直播软件或其他 AI 程序时更容易不够。",
        "关掉占显存的程序后重试；显存小于 8 GB 的电脑改用「API 转写」方案，或在模型选择里换成 SenseVoice。",
        actions=("retry", "choose_plan"),
        supersedes=("worker_crashed", "unknown_failure"),
        short="显存不够，模型没能加载或运行。",
    ),
    KnownIssue(
        "pagefile_too_small", "environment", "blocker", "电脑可用内存（虚拟内存）不够",
        "错误里有 WinError 1455、os error 1455、页面文件太小、paging file is too small。",
        "加载模型时 Windows 的内存加虚拟内存（页面文件）用完了；页面文件被手动设得很小或放在快满的磁盘上时常见。",
        "关闭游戏等占内存的程序；在 Windows「高级系统设置 → 性能 → 虚拟内存」里改成「系统管理的大小」，重启电脑后再识别。",
        actions=("retry",),
        supersedes=("worker_crashed", "unknown_failure"),
        short="Windows 内存和虚拟内存不够，模型加载失败。",
    ),
    KnownIssue(
        "moss_too_long", "environment", "blocker", "录音太长，超过 MOSS 单次输入上限",
        "错误里有 prompt/audio sequence exceeds max_length 或 131072。",
        "很长的录播一次送进 MOSS 会超过模型的输入上限。新版本会先计算长度再自动分段。",
        "更新到最新版；临时可以把视频剪成几段分别识别。",
        actions=("update",),
        fixed="2026-10-17 起的版本先计数再自动分段",
        supersedes=("worker_crashed", "unknown_failure"),
        short="录音太长，超过了 MOSS 一次能处理的长度。",
    ),
    KnownIssue(
        "worker_timeout", "environment", "blocker", "识别模型太久没有完成",
        "错误里有 worker timeout、「子进程超过 N 分钟未完成」、「连续 N 分钟没有任何进度输出」。",
        "模型进程卡住或者跑得太慢：显卡被其他程序占满、电脑进入睡眠、用 CPU 跑大模型，或者驱动问题。",
        "关闭占用显卡的程序、确认电脑不会睡眠后重试；没有独立显卡的电脑改用轻量或在线方案。",
        actions=("retry", "choose_plan"),
        supersedes=("worker_crashed", "unknown_failure"),
        short="模型进程长时间没有进展，被停止。",
    ),
    KnownIssue(
        "worker_crashed", "environment", "blocker", "识别模型的进程意外退出",
        "错误里有「worker failed (exit N)」「退出码」「子进程未返回具体异常」「进程退出后未生成结果文件」，或 0xC0000005 之类的代码。",
        "模型进程在运行中崩溃了；常见于显卡驱动问题、内存不足、杀毒软件拦截，少数是程序缺陷。",
        "先重启电脑再试一次；更新显卡驱动；把软件目录加入杀毒软件白名单。仍失败请用「回报问题」把诊断包发给开发者。",
        actions=("retry", "support"),
        short="模型进程中途崩溃，没有给出结果。",
    ),
    # ---- 语音识别（本机） ------------------------------------------------
    KnownIssue(
        "host_filter_empty", "asr", "blocker", "「只要主播」没有筛出可用的字幕",
        "报「MOSS 没有筛出可用的主播字幕」或「覆盖筛选未保留可靠对白」。",
        "对白范围选了只保留主播，但这段录音里没能可靠认出主播（声纹对不上、主播很少说话或多人轮流说话）。",
        "把首页的「对白范围」改成「全部对白」再识别，然后在字幕工作台的说话人管理里确认谁是主播。",
        actions=("studio",),
        supersedes=("unknown_failure",),
        short="只保留主播时没认出主播，结果被全部筛掉。",
    ),
    KnownIssue(
        "primary_incomplete", "asr", "problem", "主力转写没有覆盖到最后，结尾可能少了字幕",
        "待检查项里有「主力转写提前结束」（例如「api 到 218.54s，FireRedVAD 人声到 236.69s」）或「主力转写不完整」。",
        "人声检测发现后面还有人在说话，但主力转写的结果在那之前就结束了（在线服务提前截断、模型生成到上限）。软件不会凭空补字，这一段会没有字幕。",
        "打开字幕工作台检查结尾那一段；重新识别通常能补上，也可以手动添加字幕。",
        actions=("studio", "retry"),
        short="主力转写在人声结束前就停了，结尾一段可能没有字幕。",
    ),
    KnownIssue(
        "moss_long_audio", "asr", "tip", "长录音分段识别，跨段说话人需要抽查",
        "待检查项里有「长音频分段识别」或「MOSS分段生成需要复核」。",
        "录音超过这台电脑一次能处理的长度，MOSS 分几段识别，跨段的说话人靠声纹拼接，可能把同一人分成两个编号或把两人合并。",
        "在字幕工作台的说话人管理里抽查每个编号；需要的话合并或改名。",
        actions=("studio",),
    ),
    KnownIssue(
        "speakers_need_review", "asr", "tip", "说话人需要确认",
        "待检查项里有「说话人需要确认」「主播人数不足」「主要说话人候选需要确认」「说话人重叠」之类。",
        "软件对说话人的划分没有把握（声音相近、多人同时说话、主播很少开口），所以标出来让你确认。字幕文字本身不受影响。",
        "打开字幕工作台的说话人管理，确认或合并说话人。",
        actions=("studio",),
    ),
    KnownIssue(
        "cloud_asr_auth", "asr", "blocker", "在线识别服务的 API Key 不对或没有开通",
        "在线识别失败，错误里有 401、403、InvalidApiKey、Unauthorized、AccessDenied、鉴权失败。",
        "在线识别（MOSS Pro、通义 Qwen 在线识别、讯飞等）要用你在对方网站申请的 Key；Key 填错、过期，或者对应模型或服务没有开通。",
        "在「配置在线识别服务」里重新粘贴 Key 并点「测试」；到服务商控制台确认这个模型已开通。",
        actions=("cloud_asr_setup",),
        supersedes=("cloud_asr_failed", "worker_crashed", "unknown_failure"),
        short="在线识别的 API Key 不对、过期或服务没开通。",
    ),
    KnownIssue(
        "cloud_asr_quota", "asr", "blocker", "在线识别服务余额不足或欠费",
        "错误里有 Arrearage、欠费、余额不足、insufficient balance、quota、402。",
        "在线识别按时长收费，账户余额用完或欠费后服务商拒绝请求。",
        "到服务商控制台充值后再识别；或者先改用本机识别方案。",
        actions=("cloud_asr_setup", "choose_plan"),
        supersedes=("cloud_asr_failed", "worker_crashed", "unknown_failure"),
        short="在线识别服务的余额不足或已欠费。",
    ),
    KnownIssue(
        "cloud_asr_failed", "asr", "blocker", "在线识别请求失败",
        "在线识别（API 转写）阶段失败，错误里是服务商返回的报错、上传失败或超时。",
        "可能是网络或代理不稳定、音频上传到临时存储失败、服务商暂时故障，或者文件超过服务的时长、大小限制。",
        "检查网络后重试；用了代理的话试试关掉或换节点；长视频可以剪短再试；一直失败就换本机方案。",
        actions=("retry", "cloud_asr_setup", "choose_plan"),
        supersedes=("worker_crashed", "unknown_failure"),
        short="在线识别服务的请求没有成功（网络、上传或服务商故障）。",
    ),
    KnownIssue(
        "cloud_asr_upload_setup", "asr", "blocker", "录音文件识别的音频上传方式没设置好",
        "报「OSS 设置不完整」「还没有设置音频交给服务商的方式」或「Bucket 或 AccessKey 还没填完整」。",
        "「录音文件识别」要先把音频放到服务商读得到的地方：默认是服务商临时空间；选了你自己的 OSS 时，Bucket 和 AccessKey 都要填好。",
        "在「申请与设置 API」里补全 OSS，或把「音频交给服务商的方式」改成「服务商临时空间」（不用 OSS）。",
        actions=("cloud_asr_setup",),
        supersedes=("cloud_asr_failed", "worker_crashed", "unknown_failure"),
        short="录音文件识别的音频上传方式没设置好。",
    ),
    KnownIssue(
        "cloud_asr_rate_limited", "asr", "blocker", "在线识别请求太频繁或并发已满",
        "报 HTTP 429、「请求过于频繁或并发已满」「请求太频繁或配额暂时用尽」「没有成功返回任何短块」。",
        "服务商限制了同时进行的任务数或每分钟请求数；免费或新账户的限额更低。部分短块失败时，那几段会没有字幕。",
        "过几分钟后重试；经常遇到的话到服务商那里提高限额。",
        actions=("retry", "cloud_asr_setup"),
        supersedes=("cloud_asr_failed", "worker_crashed", "unknown_failure"),
        short="在线识别服务限流，请求没有完成。",
    ),
    KnownIssue(
        "cloud_asr_network", "asr", "blocker", "连不上在线识别服务",
        "报「连不上 <服务器>」「上传时网络中断」或 CERTIFICATE_VERIFY_FAILED。",
        "网络、代理或杀毒软件的 HTTPS 检查拦住了连接；Qwen Cloud 服务器在新加坡，大陆网络常常连不稳。",
        "检查网络和代理后重试（已提交的任务会继续查询，不会重复收费）；大陆用户优先用阿里云百炼（中国站）或 MOSS Pro。",
        actions=("retry", "cloud_asr_setup"),
        supersedes=("cloud_asr_failed", "worker_crashed", "unknown_failure"),
        short="电脑连不上在线识别服务。",
    ),
    KnownIssue(
        "cloud_asr_resubmit", "asr", "blocker", "在线识别任务需要你确认后重新提交",
        "报「上次提交是否受理未知，已阻止自动重复收费」「已保存远端终态」「查不到这个任务」「本地等待达到时限」。",
        "在线识别任务的状态不确定（可能已经扣费），或者服务商那边的任务已过期、失败；为了避免重复收费，软件不会自动再提交。",
        "如果确定要再识别一次，在完成页点「重试失败项」并确认重新提交（会再次上传，可能再次计费）。",
        actions=("retry",),
        supersedes=("cloud_asr_failed", "worker_timeout", "worker_crashed", "unknown_failure"),
        short="在线识别任务状态不确定，为避免重复扣费没有自动重交。",
    ),
    KnownIssue(
        "cloud_asr_content_blocked", "asr", "blocker", "在线识别服务的内容审查拦下了一段音频",
        "报「被 MOSI 的内容安全审查拦下」，或 MOSI 返回 safety guardrail blocked / safety policy error（17001）。",
        "在线识别服务会对上传的音频和识别出的文字做内容安全审查，这一段里有它不接受的内容；具体是哪一句，服务商不会说明，软件这边也改不了审查规则。这一段没有字幕。",
        "同一段音频原样重新提交多半还会被拦下，也可能再次计费，不建议直接「重试失败项」。可以改用本地识别，或换别的在线识别服务，再重新识别这个视频；是否扣了积分请到服务商控制台查看。",
        actions=("pick_primary", "mosi_resplit", "cloud_asr_setup"),
        # A refusal at upload is an HTTP 403 too; it is not a key problem.
        supersedes=("cloud_asr_resubmit", "cloud_asr_auth", "cloud_asr_failed", "worker_crashed", "unknown_failure"),
        short="在线识别服务的内容审查拦下了一段音频，这一段没有字幕。",
    ),
    # 2026-10-24: a blocked range no longer fails the task; it is filled
    # locally when a model can (recognition/cloud_gap_fill.py).
    KnownIssue(
        "cloud_asr_gap_filled", "asr", "problem", "有一段被在线识别的内容审查拦下，已用本地模型补上",
        "完成页提示有一段被 MOSI 的内容安全审查拦下；字幕工作台的审核里有「这一段由本地模型补识别」。",
        "在线识别服务（MOSS Pro 云端）会对上传的音频和识别出的文字做内容安全审查，这一段没有通过，服务商没有返回字幕。其余段照常识别；这一段改用这台电脑上的本地主力模型识别，字和说话人分辨可能跟其他段不同。",
        "在字幕工作台里检查这一段。想用 MOSS Pro 再试，可以「切成小段再交 MOSI」：被拦的那段切成约 3 分钟的小段重新上传，会再次计费，能不能通过不确定，仍被拦下的小段继续用本地模型补。",
        actions=("studio", "mosi_resplit"),
        supersedes=("cloud_asr_content_blocked", "cloud_asr_resubmit", "cloud_asr_failed"),
        short="有一段被在线识别服务拦下，已用本地模型补上；请在工作台检查这一段。",
    ),
    KnownIssue(
        "cloud_asr_gap_unfilled", "asr", "problem", "有一段被在线识别的内容审查拦下，这一段没有字幕",
        "完成页提示有一段被 MOSI 的内容安全审查拦下；字幕工作台的审核里有「这一段没有字幕」。",
        "在线识别服务（MOSS Pro 云端）的内容安全审查拦下了这一段，服务商没有返回字幕。其余段照常识别；这台电脑上没有能补这段语言的本地主力模型，或者本地补识别失败，所以这一段空着。",
        "在模型工坊下载一个本地主力模型（例如 SenseVoice 或 Whisper，没有 NVIDIA 显卡也能用）后再识别这个视频：被拦的段会自动用它补上，已完成的段不会重新上传。也可以「切成小段再交 MOSI」：会再次计费，能不能通过不确定。",
        actions=("model_workshop", "mosi_resplit"),
        supersedes=("cloud_asr_content_blocked", "cloud_asr_resubmit", "cloud_asr_failed"),
        short="有一段被在线识别服务拦下，这一段没有字幕。",
    ),
    # 2026-10-25, a user's English singing stream: MOSS Pro timed a sentence
    # past the audio of its request. 0.8.4 failed the task on it, and as the
    # result was not kept, every new start failed the same way.
    KnownIssue(
        "cloud_asr_timing_rejected", "asr", "blocker", "MOSS Pro 有一句时间超出上传的音频，旧版本因此让识别失败",
        "报「MOSS Pro 句段时间越出提交的音频」，重新开始也一样。",
        "MOSS Pro 云端偶尔把个别句子的时间标到上传的这段音频之外，多在唱歌、音乐处。旧版本只要有一句这样，就判这一段的结果无效；结果又没有存下来，每次重新开始都取回同一份结果、再失败一次（不会再次计费）。",
        "更新后再识别这个视频：超出的句子截短或去掉，其余照常。MOSI 还保留这个任务时直接取回结果，不重新上传；查不到时会先问你要不要重新提交（会再次计费）。等不及更新，可以先改用本地识别。",
        actions=("update", "pick_primary"),
        fixed="2026-10-25 已在源码修正，随之后的更新提供",
        supersedes=("cloud_asr_failed", "worker_crashed", "unknown_failure"),
        short="MOSS Pro 有一句时间超出上传的音频，旧版本因此让识别失败。",
    ),
    KnownIssue(
        "cloud_asr_timing_repaired", "asr", "tip", "MOSS Pro 有几句时间超出上传的音频，已截短或去掉",
        "排查原因里列出 MOSS Pro 截短或去掉的句数和所在的段。",
        "MOSS Pro 云端偶尔把个别句子的时间标到上传的这段音频之外，或者起止颠倒，多在唱歌、音乐处，常是模型把歌词重复了几遍。结尾超出的截到音频结尾；时间不在这段音频里的句子找不到位置，没有放进字幕。",
        "在字幕工作台里听一下这几段，缺的字幕手动补上；其余字幕不受影响。",
        actions=("studio",),
        short="MOSS Pro 有几句时间超出上传的音频，已截短或去掉。",
    ),
    KnownIssue(
        "cloud_asr_input_limit", "asr", "blocker", "素材超过在线识别服务的限制",
        "报「超过 MOSI 512 MB 上传限制」「单个文件最长 N 小时」「原生说话人任务限 2 小时」「超过 Filetrans 2GB 限制」。",
        "在线识别服务对单个文件的大小、时长有上限，这个素材超过了。",
        "在字幕工作台里只识别一段范围，或者先把视频剪成几段分别识别。",
        actions=("studio",),
        supersedes=("cloud_asr_failed", "worker_crashed", "unknown_failure"),
        short="素材的大小或时长超过了在线识别服务的上限。",
    ),
    KnownIssue(
        "cloud_asr_hotwords", "asr", "blocker", "热词（词库）不符合在线识别服务的限制",
        "报「热词不符合 MOSI 限制」「预编译热词库绑定未确认」「热词总计超过 2000 项」「每轮上下文不得超过 400 字符」。",
        "启用的词库会作为热词发给在线识别服务；词太多或太长时服务商不接受。",
        "少启用几个词库，或把很长的词条改短，然后再识别。",
        actions=("retry",),
        supersedes=("cloud_asr_failed", "worker_crashed", "unknown_failure"),
        short="发给在线识别服务的热词太多或太长。",
    ),
    KnownIssue(
        "cloud_long_speakers", "asr", "tip", "MOSS Pro 超过 60 分钟时说话人编号可能不一致",
        "用 MOSS Pro 识别很长的录音，同一个人在不同段落编号不同，「只要主播」时漏掉了人。",
        "MOSS Pro 把长录音分段识别，各段的说话人编号不会自动对齐。",
        "用「全部对白」识别后在说话人管理里合并；或把录音剪成一小时以内的几段。",
        actions=("studio",),
        ai_only=True,
    ),
    # ---- 字词时间与时间轴 ------------------------------------------------
    KnownIssue(
        "no_word_timing", "timing", "quality", "没有字级时间轴，字幕时间只能估算",
        "字幕出现得早或晚、和声音对不上，长句被切在词中间；方案里「字幕时间轴」是关闭的。",
        "这次的主力转写（例如 SenseVoice、在线 API）只给出整段的起止时间，没有每个字的时刻；字幕时间轴（FireRed / Qwen3 对齐）又是关闭的，"
        "所以每条字幕的时间只能按字数均分估算，切点也找不到真正的停顿，数字和长句更容易被切坏。",
        "在首页把「字幕时间轴」打开：中文选 FireRedASR2-AED，日语、英语等选 Qwen3 对齐；或者直接选「本地识别」「API 转写」「日语」「外语」这些方案（都带字级时间轴），再重新识别。",
        actions=("pick_timeline", "choose_plan"),
        short="主力转写没有字级时间，字幕时间轴又关着，字幕时间只能按字数估算。",
    ),
    KnownIssue(
        "alignment_degraded", "timing", "problem", "字词时间对齐没有完成，部分字幕时间是估算的",
        "报告里时间轴阶段失败，或有 forced_alignment_failed、model_degraded、timeline_result_discarded、「时间轴模型失败」。",
        "对齐模型没有装好、加载失败（常见于内存或显存不够），或者某些片段对不上，这些片段退回到主力转写的粗时间。",
        "确认模型工坊里时间轴模型（FireRed / Qwen3 对齐 / MFA）显示已就绪；关闭占内存的程序后重新识别；只差几条的话在字幕工作台手动调整即可。",
        actions=("model_workshop", "studio"),
        short="对齐模型没有完全成功，部分字幕的时间是估算的。",
    ),
    KnownIssue(
        "review_model_failed", "timing", "problem", "文字复核模型没有完成",
        "报告里文字复核阶段（Qwen3-ASR 等）失败，或有「文字复核模型 Qwen3 未完成」。",
        "第二个模型没跑成（模型没装好、内存或显存不够），这次只有主力转写的文字，少了一路对照，错字可能多一些。",
        "在模型工坊确认文字复核模型已就绪后重新识别；不需要复核时也可以在首页把它关掉。",
        actions=("model_workshop", "pick_review"),
        short="文字复核模型没跑成，少了一路文字对照。",
    ),
    KnownIssue(
        "timeline_rerouted", "timing", "tip", "中文时间轴模型不用于这种语言",
        "选了 FireRed（中文）时间轴，但这次是日语、英语等任务，报告里有 timeline_backend_rerouted。",
        "FireRed 时间轴只适用于中文；其他语言会自动改用 Qwen3 对齐模型。这是正常行为。",
        "不需要处理。想避免误会，可以选对应语言的方案（「日语」或「外语」）。",
        actions=("choose_plan",),
    ),
    KnownIssue(
        "sensevoice_chunk_overlap", "timing", "problem", "SenseVoice 分块重叠打乱了字幕顺序",
        "用 SenseVoice 识别的长视频，断句退回整段（报告里有 grouping_postprocess_rejected、grouping_local_source_boundary_fallback；"
        "旧版报「Stage 9后处理违反原文逐字符守恒」），出来的字幕一条长达 20 秒左右再被硬切。",
        "SenseVoice 每 45 秒一块识别，相邻两块共用 0.5 秒；两块的结果时间重叠，排序后文字顺序和原文不一致，断句只好退回整段。",
        "更新到包含这项修正的版本后重新识别；在那之前可以打开字幕时间轴（Qwen3 对齐）或改用 MOSS 方案。",
        actions=("update", "pick_timeline"),
        fixed="2026-10-21 已找到原因并在源码修正，随之后的更新提供",
        short="SenseVoice 相邻分块的时间重叠，打乱了字幕顺序。",
    ),
    KnownIssue(
        "incremental_fallback", "asr", "quality", "分块识别失败，改成了整段识别",
        "报告里有 incremental_asr_fallback（例如 sensevoice worker returned no parsed text）。",
        "SenseVoice 等主力会先一块一块识别；某一块没有人声时打包版会把整个分块结果丢掉，改成整段再识别一遍。"
        "整段识别的相邻段落时间可能重叠，后面断句和保真检查更容易出问题。",
        "更新到包含修正的版本；在那之前打开字幕时间轴或改用 MOSS 方案可以避开。",
        actions=("update", "pick_timeline"),
        fixed="2026-10-23 已在源码修正，随之后的更新提供",
    ),
    # ---- 语音识别（在线服务） ----------------------------------------------
    KnownIssue(
        "mfa_experimental", "timing", "tip", "MFA（实验）时间轴的已知限制",
        "选了 MFA（实验）做字幕时间轴，部分字幕时间偏差或对齐失败。",
        "MFA 是实验功能：背景声大时准确度下降；只支持中文和日语（其他语言自动改用 Qwen3 对齐）；模型只在 Hugging Face 上。",
        "效果不好时改回 Qwen3 对齐。",
        actions=("pick_timeline",),
        ai_only=True,
    ),
    KnownIssue(
        "ja_timing_quality", "timing", "tip", "日语字幕时间的已知精度",
        "日语字幕的结尾略早、切点和声音差一点。",
        "Qwen3 对齐的时间精度约 80 毫秒；日语 CTC 校正的是句首，句尾可能早 0.2–0.4 秒。2026-10-18 前的版本还会出现一闪而过或叠在一起的重复字幕，旧工程要重新识别才会变好。",
        "在字幕工作台微调即可；遇到闪字或重复叠字请更新后重新识别。",
        actions=("studio", "update"),
        ai_only=True,
    ),
    KnownIssue(
        "flv_gap_sync", "timing", "tip", "直播录播 FLV 的字幕整体偏移（旧版）",
        "断流过的长 FLV 字幕越往后越偏，剪辑过的 FLV 字幕整体提前十几秒。",
        "FLV 的时间戳在断流处跳变，旧版按另一种时钟计算。",
        "更新后重新识别。",
        actions=("update",),
        fixed="2026-10-08 起的版本",
        ai_only=True,
    ),
    # ---- AI 断句与校对 ---------------------------------------------------
    KnownIssue(
        "ai_key_missing", "ai_text", "quality", "没有设置文字 AI 的 API Key，AI 断句和 AI 校对没有运行",
        "任务报告里 AI 断句、AI 校对都是关闭的（use_ai_grouping、enable_ai_polish = false），字幕断句生硬、错别字没人改。",
        "AI 断句和 AI 校对要用文字 AI（推荐 DeepSeek）的 API Key。没有 Key 时软件改用本地规则：字幕照样生成，但句子切得不如 AI 自然，"
        "游戏术语和同音错字也不会被修正；没有字级时间时，本地断句更容易把数字和词切坏。",
        "在「设置 AI 与 API Key」里填好 Key（推荐 DeepSeek，先充值 10 元）并点「测试连接」，然后重新识别；已有的字幕也可以在完成页用「AI 词库校对」补做校对。",
        actions=("ai_settings", "glossary_proofread"),
        short="没填文字 AI 的 API Key，这次断句和校对用的是本地规则。",
    ),
    KnownIssue(
        "ai_steps_off", "ai_text", "tip", "这次没有用 AI 断句或 AI 校对",
        "任务报告里 AI 断句或 AI 校对是关闭的，而现在已经设置了 API Key。",
        "可能是识别时还没有 Key，或者在 AI 设置里关掉了这两步。用 AI 时断句更自然，错字和术语会按词库修正。",
        "在 AI 设置里打开「AI 断句」「AI 校对」后重新识别；已有的字幕可以用「AI 词库校对」补做校对。",
        actions=("ai_settings", "glossary_proofread"),
    ),
    KnownIssue(
        "ai_auth_failed", "ai_text", "problem", "文字 AI 的 API Key 不对、过期或没有权限",
        "AI 断句或 AI 校对没有完成并退回本地规则，报告里的类别是 auth_error、auth_config（401、403、Invalid API key）。",
        "填的 Key 被服务商拒绝：复制时多了空格、Key 已删除或过期、Key 和所选服务或模型不匹配。",
        "在「设置 AI 与 API Key」里重新粘贴 Key，选对服务和模型，点「测试连接」变绿后重试。",
        actions=("ai_settings", "retry"),
        short="文字 AI 的 API Key 被服务商拒绝。",
    ),
    KnownIssue(
        "ai_quota", "ai_text", "problem", "文字 AI 的余额不足",
        "AI 断句或 AI 校对没有完成，报告里的类别是 quota_exhausted（402、Insufficient Balance、余额不足）。",
        "文字 AI 按用量收费，账户没有余额时请求会被拒绝；新注册的 DeepSeek 账户要先充值才能用。",
        "到服务商网站充值（10 元够用很久），然后在完成页点「重试失败项」补做。",
        actions=("retry", "ai_settings"),
        short="文字 AI 账户余额不足，请求被拒绝。",
    ),
    KnownIssue(
        "ai_rate_limited", "ai_text", "problem", "文字 AI 请求太频繁被限流",
        "AI 断句或 AI 校对部分没有完成，报告里的类别是 rate_limited（429、Too Many Requests）。",
        "服务商限制了每分钟的请求数；同时跑多个任务或账户等级低时容易遇到。",
        "过几分钟后在完成页点「重试失败项」；经常遇到可以换一个限额更高的服务或模型。",
        actions=("retry",),
        short="文字 AI 服务限流，部分请求没有完成。",
    ),
    KnownIssue(
        "ai_timeout", "ai_text", "problem", "文字 AI 太久没有回应",
        "AI 断句或 AI 校对部分没有完成，报告里的类别是 timeout、total_timeout、read_idle_timeout，或者提示共享总时限已用完。",
        "网络慢、服务商繁忙，或者选了推理很慢的模型（例如带深度思考的模型），请求在时限内没有返回。",
        "检查网络和代理后在完成页点「重试失败项」；长期慢的话在 AI 设置里换成更快的模型（例如 DeepSeek 的普通对话模型）。",
        actions=("retry", "ai_settings"),
        short="文字 AI 在时限内没有回应。",
    ),
    KnownIssue(
        "ai_connection", "ai_text", "problem", "连不上文字 AI 服务",
        "AI 断句或 AI 校对没有完成，报告里的类别是 connection_error、tls_error、connect_timeout，错误里有 SSL、代理、无法解析域名。",
        "电脑连不上服务商：网络断开、代理或加速器拦截、公司或校园网屏蔽，或者服务地址填错。",
        "确认能打开服务商网站；有代理时试试关闭或切换；在 AI 设置里点「测试连接」确认通了再「重试失败项」。",
        actions=("ai_settings", "retry"),
        short="电脑连不上文字 AI 服务。",
    ),
    KnownIssue(
        "ai_bad_output", "ai_text", "problem", "文字 AI 的回答不符合要求，已退回本地规则",
        "AI 断句或 AI 校对部分退回，报告里的类别是 parse_failure、format_mismatch、empty_response、structured_output_truncated、contract 之类。",
        "AI 返回的内容格式不对、被截断、漏了字或改了原文，软件的保护规则拒绝采用（宁可用本地规则也不交出丢字的字幕）。"
        "小模型、本地模型或非推荐模型更容易出现。",
        "在 AI 设置里换成推荐的模型（例如 DeepSeek）后「重试失败项」；偶尔几批退回不影响字幕可用。",
        actions=("ai_settings", "retry"),
        short="AI 的回答不合格，被保护规则拒绝，这部分用了本地规则。",
    ),
    KnownIssue(
        "ai_request_too_large", "ai_text", "problem", "这批内容对所选 AI 模型太长",
        "报告里的类别是 request_too_large，或提示单条完整字幕超过模型预算。",
        "所选模型能接收的内容太短（上下文窗口小），装不下一批字幕。",
        "在 AI 设置里换成上下文更长的模型（例如 DeepSeek）；超长的单条只会用本地规则处理，不影响其他字幕。",
        actions=("ai_settings",),
        short="内容超过了所选 AI 模型能处理的长度。",
    ),
    KnownIssue(
        "ai_model_config_rejected", "ai_text", "problem", "AI 服务拒绝了所选模型",
        "AI 断句或 AI 校对退回本地规则，报告里的类别是 configuration_error 或 model_not_supported（HTTP 400、404），"
        "或提示「本任务此阶段的模型配置已被服务端拒绝」。",
        "模型名写错、这个账户没有该模型的权限，或者服务地址和模型不匹配。",
        "在 AI 设置里从列表重新选择模型，点「测试连接」通过后再「重试失败项」。",
        actions=("ai_settings", "retry"),
        short="AI 服务不接受所选的模型。",
    ),
    KnownIssue(
        "ai_model_retired", "ai_text", "blocker", "选的 AI 模型已经下线",
        "开始识别时报「选择的模型 <模型> 已不可用（服务商已下线）」。",
        "服务商停用了这个模型，再发请求也不会成功。",
        "在 AI 设置里换一个现在可用的模型（例如 DeepSeek 的普通对话模型）。",
        actions=("ai_settings",),
        supersedes=("unknown_failure",),
        short="选的 AI 模型已被服务商下线。",
    ),
    KnownIssue(
        "ai_cli_login", "ai_text", "blocker", "账号登录方式的 AI 当前不可用",
        "开始识别时报「使用账号登陆传输（…），当前不可用」。",
        "AI 断句或 AI 校对设成了用账号登录的命令行工具（Grok、Codex 等），但它没有安装、没有登录或版本太旧。",
        "在 AI 设置里完成登录；或者改选 DeepSeek 等服务并填写 API Key。",
        actions=("ai_settings",),
        supersedes=("unknown_failure",),
        short="账号登录方式的 AI 没装好或没登录。",
    ),
    KnownIssue(
        "term_search_polish_off", "ai_text", "blocker", "开了联网核验但关了文字校对（旧版会失败）",
        "识别了几分钟后失败，报「Text AI stage is disabled for this task: polish」。",
        "0.8.0–0.8.2 的联网补充核验借用文字校对的 AI 服务；关掉文字校对时它找不到服务，整个任务失败。",
        "更新到最新版（现在只会跳过联网核验）；或者关掉联网补充核验、或打开文字校对后再识别。",
        actions=("update", "ai_settings"),
        fixed="2026-10-22 起的版本只跳过联网核验，不再让任务失败",
        supersedes=("unknown_failure",),
        short="旧版在关掉文字校对时，联网核验让整个任务失败。",
    ),
    KnownIssue(
        "old_batch_index_crash", "ai_text", "blocker", "旧版断句批次编号出错（0.7.1）",
        "任务最后报「invalid literal for int() with base 10: '2.1.2'」。",
        "0.7.1 处理拆开的 AI 断句批次编号时出错。",
        "更新到 0.8.0 或更新的版本。",
        actions=("update",),
        fixed="0.8.0 起",
        supersedes=("unknown_failure",),
        short="0.7.1 的断句批次编号缺陷。",
    ),
    KnownIssue(
        "local_linebreak_quality", "ai_text", "tip", "不用 AI 时快语速处会切在词中间",
        "没开 AI 断句时，说得快的地方出现「银河｜联军」「最终｜决战」这类切在词中间的字幕。",
        "本地断句规则只看字数和停顿，说得快、没有停顿时找不到好的切点。",
        "填好文字 AI 的 API Key 打开 AI 断句；或在字幕工作台里手动合并、拆分。",
        actions=("ai_settings", "studio"),
        ai_only=True,
    ),
    KnownIssue(
        "glossary_runtime_defects", "ai_text", "tip", "词库替换的旧缺陷",
        "旧版本里出现词被错误替换（例如「叠势」被换成「地刺」）、隐藏的词条仍被使用、热词被按字典顺序截断。",
        "早期版本的词库匹配规则有缺陷。",
        "更新到最新版；在术语库里检查对应词条。",
        actions=("update",),
        fixed="0.7.5 起",
        ai_only=True,
    ),
    KnownIssue(
        "ai_partial_fallback", "ai_text", "problem", "部分 AI 断句或 AI 校对没有完成",
        "完成页写「部分AI文字校对未完成」或「AI 断句未完成，使用本地规则」。",
        "有几批请求失败后退回了本地规则（具体原因见同一份报告里的类别）。字幕仍可用，只是这几段没有经过 AI。",
        "在完成页点「重试失败项」补做；或者打开「AI 词库校对」，用「AI 校对建议」补做后勾选写回。",
        actions=("retry", "glossary_proofread"),
        short="有几批 AI 请求没有成功，这几段用了本地规则。",
    ),
    KnownIssue(
        "ai_edits_rejected", "ai_text", "tip", "部分 AI 修改被保护规则拒绝",
        "完成页写「AI建议被保护规则拒绝 N 处」。",
        "AI 想改的数字、人名或原文意思超出了允许范围（例如把「十分」改成「10分」），软件保留了原文。这是保护，不是故障。",
        "不需要处理；想看具体是哪几处，可以在字幕工作台的待检查项里查看。",
        actions=("studio",),
    ),
    KnownIssue(
        "search_not_configured", "ai_text", "tip", "联网核验没有执行",
        "完成页写「联网核验未配置」或「联网核验未执行（当前通道不支持）」。",
        "联网核验是可选的术语查证，需要支持联网搜索的 AI 服务。没执行不影响字幕本身。",
        "不需要处理；想用的话在 AI 设置里换成支持联网搜索的服务。",
        actions=("ai_settings",),
    ),
    KnownIssue(
        "translation_failed", "ai_text", "problem", "字幕翻译没有完成",
        "报告里有 subtitle_translation_failed，或「翻译未完成」的待检查项。",
        "翻译也用文字 AI；Key、余额、网络或模型的问题都会让它失败。原文字幕不受影响。",
        "解决 AI 的问题后，在字幕工作台的「双语 / 翻译」里重新翻译。",
        actions=("ai_settings", "studio"),
        short="翻译请求没有成功，原文字幕不受影响。",
    ),
    # ---- 断句与字幕保真 --------------------------------------------------
    KnownIssue(
        "fidelity_numbers", "segmentation", "blocker", "数字在断句时被切开，字幕保真检查未通过",
        "报「字幕保真检查未通过：S1 123.456s…」，同一份报告里 final_content_conservation_recovery 记录的数字前后不一致。",
        "断句把一个数字从中间切开（例如 20 被切成 2 | 0），或把数字和前后说明它是数字的字分到两条（例如「第｜十九题」），"
        "最后核对时读出的数字和原文对不上，本地重建也没有成功；软件宁可让这个文件失败，也不交出数字读错的字幕。"
        "数字很多的讲课、没有字级时间或不开 AI 断句时最容易遇到。",
        "更新到最新版后重新识别（这类切点已陆续修正）；打开字幕时间轴或 AI 断句也能避开。仍失败请用「回报问题」发送诊断包，并告诉开发者报错里的时间点。",
        actions=("pick_timeline", "ai_settings", "update", "support"),
        fixed="2026-10-16 起（0.7.4）修正了不开 AI 断句时数字被切开；2026-10-23 修正了稀疏说话时单独一个字被读成数字（例如「两」读成 2）；"
              "2026-10-28 已在源码修正数字很多的长讲课整份失败：字幕跨段后读出的数字不再算错，本地重建时的时间小问题会自动修整，随之后的更新提供",
        supersedes=("fidelity_failed",),
        short="一个数字在断句时被切开，最后核对时对不上。",
    ),
    KnownIssue(
        "fidelity_failed", "segmentation", "blocker", "字幕保真检查未通过",
        "报「字幕保真检查未通过：<说话人> <时间>s；原文和阶段记录已保留」，整个文件没有字幕。",
        "最后一步会核对成片字幕和识别原文逐字一致。某一段在断句、合并或时间整理后丢字、多字或数字对不上，"
        "软件尝试了断句阶段的字幕和本地重建都不合格，于是让这个文件失败，避免交出错字的字幕。这是保护机制，说明那一段的处理有缺陷。",
        "先更新到最新版再识别一次（这类问题多数已修正）；打开字幕时间轴或 AI 断句通常能避开。仍失败请用「回报问题」发送诊断包，并告诉开发者报错里的时间点。",
        actions=("pick_timeline", "ai_settings", "update", "support"),
        short="最后核对时某一段字幕和原文对不上，软件为了不交出错字的字幕让文件失败。",
    ),
    KnownIssue(
        "stage9_conservation", "segmentation", "blocker", "旧版断句的逐字检查失败",
        "报「Stage 9后处理违反原文逐字符守恒；停止返回错误字幕。」",
        "0.8.1 及更早版本的断句后处理会按时间重新排序，遇到时间重叠的段落时文字顺序被打乱，最后的逐字检查失败。",
        "更新到最新版后重新识别。",
        actions=("update",),
        fixed="0.8.2 起不再整份失败（改为退回该段）",
        short="旧版断句后处理打乱了文字顺序。",
    ),
    KnownIssue(
        "hard_split_dead_end", "segmentation", "blocker", "旧版硬切兜底没有覆盖完整原文",
        "在「锁定最终字幕时间轴」报「Qwen 单条本地修复未覆盖完整原文」，前面有「[硬切兜底]」的提示。",
        "某一段没有可用的字级时间又超过 5 秒（例如拖长音），0.8.0 / 0.8.1 的硬切规则选到了走不通的切点。",
        "更新到 0.8.2 或更新的版本后重新识别；这和 API Key 无关。",
        actions=("update",),
        fixed="0.8.2 起",
        supersedes=("unknown_failure",),
        short="0.8.0 / 0.8.1 的硬切规则选错切点。",
    ),
    KnownIssue(
        "grouping_refused", "segmentation", "blocker", "断句结果没通过来源与时间核对",
        "报「断句阶段结果未通过来源正文、归属与时间校验」（常见于俄语、韩语等按单词断句的语言）。",
        "对齐模型给单词的时间超出了句子范围，断句结果被核对拒绝；本地规则也一样会被拒绝，和 AI 无关。",
        "更新到最新版后重新识别（2026-10-22 起已修正）；关掉 AI 没有帮助。",
        actions=("update", "support"),
        fixed="2026-10-22 起的版本（公开 0.8.2 还没有）",
        supersedes=("unknown_failure",),
        short="单词时间超出句子范围，断句结果被拒绝。",
    ),
    KnownIssue(
        "ja_number_timing_old", "segmentation", "blocker", "旧版日语数字改写后时间对不上",
        "日语任务报「本地修复的文字与时间单元不一致」，或保真检查失败。",
        "0.7.3 及更早会把中文的数字改写规则用在日语上，而且没把假名算进字级时间。",
        "更新到 0.7.4 或更新的版本。",
        actions=("update",),
        fixed="0.7.4 起",
        supersedes=("unknown_failure",),
        short="旧版把中文数字规则用在了日语上。",
    ),
    KnownIssue(
        "final_hard_limit", "segmentation", "blocker", "最终字幕超过长度上限（旧版）",
        "报「最终字幕超过硬性长度上限」。",
        "旧版的断句在某些情况下留下超长字幕，最后检查拒绝交付；英语任务曾全部受影响。",
        "更新到最新版后重新识别。",
        actions=("update",),
        fixed="2026-10-14 起",
        supersedes=("unknown_failure",),
        short="旧版断句留下了超长字幕。",
    ),
    KnownIssue(
        "fidelity_comma_numeral", "segmentation", "blocker", "逗号被清掉后数字连在一起",
        "保真检查失败，原文是「二十，然后…」这样数字后面紧跟逗号。",
        "清理标点时去掉了逗号，前后两个数字被读成一个，核对对不上。目前还没有修正，很少见。",
        "可以打开 AI 断句再试；仍失败请回报问题。",
        actions=("ai_settings", "support"),
        ai_only=True,
    ),
    KnownIssue(
        "moss_duplicate_segments", "segmentation", "blocker", "MOSS 返回重复片段（旧版）",
        "8–9 月的版本里出现「1 秒几十字」的重复字幕或保真失败。",
        "MOSS 对同一说话人返回了部分重复的片段。",
        "更新到最新版。",
        actions=("update",),
        fixed="2026-09 起",
        ai_only=True,
    ),
    KnownIssue(
        "japanese_fragmented", "segmentation", "tip", "日语 AI 断句太碎",
        "日语字幕很多只有三四个字。",
        "旧的日语 AI 断句提示词偏向短句。",
        "更新到 2026-10-22 之后的版本（会合并过短的日语字幕）。",
        actions=("update",),
        fixed="2026-10-22 起的日常版（公开 0.8.2 还没有）",
        ai_only=True,
    ),
    KnownIssue(
        "japanese_morphology_failed", "segmentation", "quality", "日语分词工具没能运行",
        "报告里有 japanese_morphology_unavailable（日语分词失败）。",
        "日语断句要先用分词工具找出词的边界；它没能运行时只能按字数切，容易切在词中间。视频其实不是日语时也会出现。",
        "先确认视频确实是日语；是的话在模型工坊修复主运行环境后重新识别。",
        actions=("model_workshop", "choose_plan"),
        short="日语分词工具没能运行，断句只能按字数切。",
    ),
    KnownIssue(
        "grouping_local_fallback", "segmentation", "quality", "部分段落的断句退回了整段",
        "报告里有 grouping_postprocess_rejected、grouping_local_source_boundary_fallback 或很多 local_hard_split_recovery，有些字幕切在词中间。",
        "断句结果没通过检查（常见原因：段落时间重叠、没有字级时间），这些段落保留了原来的整段再按长度硬切。",
        "打开字幕时间轴后重新识别通常能改善；少量几条可以在字幕工作台里手动拆分、合并。",
        actions=("pick_timeline", "studio"),
        short="部分段落的断句没通过检查，保留了整段再硬切。",
    ),
    # ---- 保存与输出 ------------------------------------------------------
    KnownIssue(
        "disk_full", "output", "blocker", "磁盘空间不够",
        "错误里有 No space left、磁盘空间不足、WinError 112。",
        "缓存、模型或工程写到的磁盘满了。",
        "清理磁盘空间（模型和缓存可以在设置里改到别的盘），然后重试。",
        actions=("retry",),
        supersedes=("worker_crashed", "unknown_failure"),
        short="磁盘满了，结果写不进去。",
    ),
    KnownIssue(
        "project_save_failed", "output", "blocker", "字幕工程没能保存",
        "完成页写「识别结果工程保存失败」或「工程无法载入」。",
        "识别已经做完，但写工程文件时失败：工程库所在磁盘满了、没有写入权限、被同步盘（OneDrive 等）或杀毒软件占用、路径太长，"
        "或者同一个输出位置正被另一个任务使用。",
        "先用「更多操作 → 恢复已有识别结果」找回这次的结果；然后检查工程库所在磁盘的空间和权限，必要时在设置里把工程库换到别的文件夹。",
        actions=("recover",),
        short="识别完成了，但字幕工程文件没能写入。",
    ),
    KnownIssue(
        "studio_result_mismatch", "output", "blocker", "识别结果和当前工程对不上，没有写入",
        "在字幕工作台识别时报「工程交付的任务 ID 与当前任务不一致」或「识别提交后工程已有人工修订，已停止打开过期结果」。",
        "识别期间工程被手动改过或换了一个工程，为了不覆盖你的修改，软件没有把这次结果写进去。",
        "在当前工程里重新识别一次；之前的结果可以用「恢复已有识别结果」找回。",
        actions=("recover", "studio"),
        supersedes=("unknown_failure",),
        short="识别期间工程被改过，结果没有覆盖你的修改。",
    ),
    KnownIssue(
        "skipped_existing", "output", "tip", "已经有字幕结果，这次跳过了",
        "报「已存在字幕结果」。",
        "这个视频已经识别过，覆盖策略设为不覆盖。",
        "需要重新识别时在设置里改覆盖策略，或打开已有的工程。",
        actions=("studio",),
    ),
    KnownIssue(
        "cancelled", "output", "tip", "任务被取消",
        "完成页写「任务已取消」。",
        "识别中途点了取消，或者关闭了程序。已经完成的步骤会留在缓存里。",
        "重新开始同一个视频会复用已完成的步骤，通常比第一次快。",
    ),
    # ---- 设置 ------------------------------------------------------------
    KnownIssue(
        "settings_warnings", "settings", "tip", "设置文件里有读不懂的项目",
        "报告的 settings.config_warnings 不是空的。",
        "设置文件里有旧版本留下或手动改坏的项目，软件用了默认值代替。",
        "一般不影响识别；如果识别方案和你选的不一样，在首页重新选一次方案即可。",
        actions=("choose_plan",),
    ),
    KnownIssue(
        "unknown_failure", "output", "blocker", "失败原因不在已知问题里",
        "任务失败，但错误不属于上面任何一类。",
        "可能是新的问题，本地清单还认不出来。",
        "可以点下面的「让 AI 分析」看看；也可以用「回报问题」把诊断包发给开发者，附上这份排查报告。",
        actions=("support",),
    ),
)


def catalog_strings() -> tuple[str, ...]:
    """Every user-facing catalog text (the localization test reads this)."""
    texts = list(ACTION_LABELS.values()) + list(STAGES.values())
    for issue in ISSUES.values():
        texts += [issue.title, issue.symptom, issue.cause, issue.advice]
        texts += [text for text in (issue.short, issue.fixed) if text]
    return tuple(dict.fromkeys(texts))
