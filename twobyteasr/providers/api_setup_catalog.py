"""What each cloud provider needs, in the form the setup dialog shows (2026-10-13).

The step-by-step text of every guide lives in ``docs/api-setup/<file>`` (one
source for the repository docs and the in-app guide). This module holds the
structured parts: what the service does in 兔白, official links with the date
they were last checked, the fields to fill, capability limits and cost basis.
Links that need a login to verify are marked ``needs_login``; their exact
console layout is not described anywhere in the app.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

CHECKED = '2026-10-14'


@dataclass(frozen=True)
class Link:
    label: str
    url: str
    checked: str = CHECKED
    needs_login: bool = False


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    help: str
    example: str = ''
    secret: bool = False
    required: bool = True
    prefilled: str = ''
    advanced: bool = False
    choices: tuple = ()       # ((value, label), ...): shown as a choice instead of a text box
    show_when: tuple = ()     # (field_key, value): only shown and used when that field has that value
    hint: str = ''            # one short line under the field; ``help`` is the full text (tooltip)

    @property
    def short_help(self) -> str:
        return self.hint or self.help


@dataclass(frozen=True)
class ModelChoice:
    model: str
    label: str
    summary: str
    speakers: bool
    timestamps: str          # 'word' | 'segment'
    hotwords: bool


@dataclass(frozen=True)
class Shot:
    """A screenshot of the official site (``assets/api-setup/<file>``), 2026-10-18.

    ``ring`` is the button to press as (x, y, width, height) fractions of the
    picture; the dialog draws it in the theme's accent, so one picture serves
    every theme. Pages change: ``source`` and ``captured`` say what was shot
    and when (scripts/capture_api_setup_shots.mjs takes the public ones again).
    """
    file: str
    ring: tuple
    source: str
    captured: str

    def path(self, root=None) -> Path:
        from ..runtime_paths import detect_install_root
        base = Path(root) if root is not None else detect_install_root()
        return base / 'assets' / 'api-setup' / self.file


@dataclass(frozen=True)
class StepText:
    """What one step of a provider's walkthrough says (overrides the defaults).

    ``lines`` are broken by hand at natural pauses, one short phrase each, and
    translated one by one: wrapping a long sentence in a narrow column broke
    it in odd places (user, 2026-10-18).
    """
    role: str                  # account | topup | key | storage
    title: str = ''
    label: str = ''            # the word under its progress segment
    lines: tuple = ()
    note: str = ''
    note_kind: str = ''        # 'free' | 'warn' | ''
    action: str = ''
    shot: Shot | None = None


@dataclass(frozen=True)
class WalkStep:
    role: str                  # account | topup | key | storage | paste | fill
    label: str
    title: str
    lines: tuple = ()
    note: str = ''
    note_kind: str = ''
    url: str = ''
    action: str = ''
    shot: Shot | None = None


@dataclass(frozen=True)
class ProviderGuide:
    key: str
    kind: str                # 'asr' or 'text'
    title: str
    role: str
    guide_file: str
    links: tuple = ()
    fields: tuple = ()
    models: tuple = ()
    uploads: str = ''
    cost: str = ''
    needs_storage: bool = False      # can use the user's own OSS (see uses_own_storage)
    status_note: str = ''
    advanced_only: bool = False
    account_note: str = ''           # which account/key this entry needs and what it cannot share
    # 2026-10-18 walkthrough: a short name and where it lives, honest facts in
    # a few words (about how long, what it costs first), a tag for the
    # provider menu, and per-step texts. ``free_trial``: no top-up step, the
    # service gives free credit to try with first.
    short_title: str = ''
    site: str = ''
    minutes: int = 0
    money: str = ''
    tag: str = ''
    free_trial: bool = False
    after_note: str = ''
    walk: tuple = ()
    # 2026-10-25: 'cn' / 'intl' for the entry offered on two official sites
    # (千问AI平台 / Qwen Cloud); the setup dialog switches between them.
    site_variant: str = ''

    @property
    def name(self) -> str:
        return self.short_title or self.title

    def guide_path(self, root=None) -> Path:
        from ..runtime_paths import detect_install_root
        base = Path(root) if root is not None else detect_install_root()
        return base / 'docs' / 'api-setup' / self.guide_file

    def guide_text(self, root=None, language: str | None = None) -> str:
        path = self.guide_path(root)
        if language is None:
            try:
                from ..i18n import current_language
                language = current_language()
            except Exception:
                language = 'zh'
        if language == 'zh-Hant':
            # Generated by scripts/make_zh_hant.py (2026-10-14).
            hant = path.with_name(path.name.replace('.zh-CN.md', '.zh-Hant.md'))
            if hant.is_file():
                path = hant
        try:
            return path.read_text(encoding='utf-8')
        except OSError:
            return f'（找不到教程文件 docs/api-setup/{self.guide_file}；请在文档目录里查看。）'


_KEY_HELP = '只填你自己账户里创建的 Key。兔白把它加密保存在本机，不写进工程、日志或导出文件。'

# How 录音文件识别 audio reaches the provider (settings ``models.filetrans_upload``).
#
# 2026-10-14 (ADR 0112, supersedes the upload default of ADR 0111): the
# official docs say the temporary ``oss://`` upload expires after 48 hours and
# must not be used in production (“请勿用于生产环境”; upload-credential API
# capped at 100 QPS, no scaling). The regular route is therefore the user's
# own private OSS bucket with short-lived signed links; the temporary upload is
# only used when the user explicitly picks it as a trial. Nothing is chosen
# silently: with neither set up, the run stops before uploading anything.
UPLOAD_PROVIDER = 'provider_temporary'
UPLOAD_OWN_OSS = 'own_oss'
UPLOAD_MISSING = 'missing'
UPLOAD_CHOICES = ((UPLOAD_OWN_OSS, '我自己的阿里云 OSS 私有存储（正式使用）'),
                  (UPLOAD_PROVIDER, '服务商临时上传（仅供试用：48 小时失效，官方说明勿用于生产）'))
_OWN_OSS = ('filetrans_upload', UPLOAD_OWN_OSS)
TEMPORARY_UPLOAD_SOURCE = 'https://help.aliyun.com/zh/model-studio/get-temporary-file-url'
TRIAL_UPLOAD_NOTE = ('服务商临时上传只适合先试试看：官方说明临时链接 48 小时后失效、上传凭证接口限 100 次/秒且不能扩容，'
                     '“请勿用于生产环境”。日常使用请设置自己的 OSS 私有存储（只需设置一次）。')
MISSING_UPLOAD_MESSAGE = ('录音文件识别只接受“服务商能读到的音频网址”，还没有设置音频交给服务商的方式：'
                          '请在“申请与设置 API”里填写你自己的 OSS 私有存储（正式使用），'
                          '或明确选择“服务商临时上传（仅供试用）”。'
                          '只想填一把 Key 的话，可以改用“MOSS Pro 云端（MOSI）”，它直接上传本地音频。')
_UPLOAD_HINT = '正式使用选自己的 OSS（下面几栏，设置一次即可）；临时上传只供试用。'
_UPLOAD_HELP = ('录音文件识别不收本地文件，只收服务商能读到的音频网址。正式使用请选自己的 OSS 私有存储：'
                '兔白上传本次音频、生成限时签名链接交给服务商读取，取得结果后删除。' + TRIAL_UPLOAD_NOTE
                + '只想填一把 Key 的话，可改用 MOSS Pro 云端（直接上传本地音频）。')


def _oss_fields(region_example: str, *, international: bool = False) -> tuple:
    console = '阿里云国际站 OSS 控制台' if international else 'OSS 控制台'
    return (
        Field('oss_region', 'OSS 地域', f'创建 Bucket 时选的地域，例如 {region_example}。在 {console}的 Bucket 概览页可以看到。',
              region_example, show_when=_OWN_OSS, hint='创建 Bucket 时选的地域。'),
        Field('oss_bucket', 'OSS Bucket 名称', '你新建的私有 Bucket 名称（读写权限保持“私有”，不要改成公共读）。', '2byte-asr-temp',
              show_when=_OWN_OSS, hint='私有 Bucket 的名称（保持私有，不要设成公共读）。'),
        Field('oss_prefix', '临时目录', '已预填。只用于存放待识别的临时音频，识别完成后自动删除。', 'asr-temp/',
              prefilled='asr-temp/', advanced=True, show_when=_OWN_OSS, hint='已预填，一般不用改。'),
        Field('oss_access_key_id', 'AccessKey ID', '在 RAM 访问控制里为一个只授权这个 Bucket 临时目录的子用户创建；'
              '不要用主账号 AccessKey。API Key 不能代替它。', 'LTAI…', secret=True, show_when=_OWN_OSS,
              hint='只授权这个 Bucket 的 RAM 子用户的 AccessKey（不要用主账号）。'),
        Field('oss_access_key_secret', 'AccessKey Secret', '与 AccessKey ID 同时生成，只显示一次。', '', secret=True,
              show_when=_OWN_OSS, hint='与 AccessKey ID 一起生成，只显示一次。'))

# 百炼's API Key page (北京), shared by 录音文件识别 and 文字 AI; captured signed in, keys and the
# workspace address blocked out (2026-10-18).
BAILIAN_KEY_SHOT = Shot('bailian-api-keys.jpg', (0.840, 0.386, 0.130, 0.068),
                        'https://bailian.console.aliyun.com/cn-beijing/model/settings/api-key', '2026-10-18')
BAILIAN_ACCOUNT = StepText('account', lines=('用手机号注册阿里云账号，', '已有账号点“前往登录”。'),
                           shot=Shot('bailian-1-register.jpg', (0.418, 0.311, 0.513, 0.411),
                                     'https://account.aliyun.com/register/qr_register.htm', '2026-10-18'))

ASR_GUIDES = (
    ProviderGuide(
        'qwen_cloud_filetrans', 'asr', 'Qwen Cloud（Qwen 官方国际站）· 录音文件识别',
        '云端识别：文字与字/词级时间（Qwen-Audio-3.1 另有说话人），不需要显卡。'
        '正式使用还需要你自己的 OSS 私有存储（阿里云国际站，设置一次）。',
        'qwen-cloud-filetrans.zh-CN.md',
        links=(Link('Qwen Cloud 控制台（注册 / 登录）', 'https://home.qwencloud.com/'),
               Link('API Key 页面', 'https://home.qwencloud.com/api-keys', needs_login=True),
               Link('账单：补全付款信息', 'https://home.qwencloud.com/billing/overview?target=payment', needs_login=True),
               Link('免费额度 / 仅用免费额度开关', 'https://home.qwencloud.com/benefits', needs_login=True),
               Link('获取 API Key（官方说明）', 'https://docs.qwencloud.com/api-reference/preparation/api-key'),
               Link('语音识别模型、限制与价格', 'https://docs.qwencloud.com/developer-guides/speech/speech-to-text-models'),
               Link('录音文件识别 API', 'https://docs.qwencloud.com/api-reference/speech-recognition/fun-asr-recording/restful-api'),
               Link('错误码说明', 'https://docs.qwencloud.com/api-reference/preparation/error-messages'),
               Link('国际站 OSS 控制台', 'https://oss.console.alibabacloud.com/', needs_login=True),
               Link('国际站 RAM 访问控制（创建 AccessKey）', 'https://ram.console.alibabacloud.com/', needs_login=True),
               Link('临时上传的官方限制', TEMPORARY_UPLOAD_SOURCE)),
        fields=(Field('api_key', 'API Key', _KEY_HELP + '在 Qwen Cloud 的 API Key 页面点“Create API key”生成，官方文档写作 sk-xxxxx'
                      '（控制台可能显示为 sk-ws- 开头）；完整密钥只显示一次。不要用 Token Plan 订阅专用 Key（sk-sp- 开头），'
                      '它不能做录音文件识别。', 'sk-ws-…', secret=True,
                      hint='在 Qwen Cloud 的 API Key 页面创建，只显示一次（不要用 sk-sp- 开头的 Token Plan Key）。'),
                Field('url', '服务地址', '已预填 Qwen Cloud 官方地址（新加坡），一般不用改。'
                      '官方命令行工具使用的 dashscope-intl.aliyuncs.com 也可以。',
                      'https://maas.qwencloudapi.com', prefilled='https://maas.qwencloudapi.com', advanced=True,
                      hint='已预填官方地址（新加坡），一般不用改。'),
                Field('filetrans_upload', '音频交给服务商的方式', _UPLOAD_HELP, choices=UPLOAD_CHOICES,
                      prefilled=UPLOAD_OWN_OSS, hint=_UPLOAD_HINT))
        + _oss_fields('ap-southeast-1（新加坡，与 Qwen Cloud 服务同地）', international=True),
        models=(ModelChoice('qwen-audio-3.1-asr-flash-filetrans', 'Qwen-Audio-3.1-ASR-Flash 录音文件识别（推荐）',
                            '字/词级时间与说话人（说话人建议 2 小时内），支持热词与上下文；单文件 12 小时 / 2 GB',
                            speakers=True, timestamps='word', hotwords=True),
                ModelChoice('qwen3-asr-flash-filetrans', 'Qwen3-ASR-Flash 录音文件识别',
                            '字/词级时间（开启 enable_words），不区分说话人，不支持热词；单文件 12 小时 / 2 GB',
                            speakers=False, timestamps='word', hotwords=False)),
        uploads='识别时把本次任务的音频（16 kHz 单声道 WAV，只有声音，不含画面）交给 Qwen Cloud：正式方式是先传到你的 OSS '
                '私有 Bucket，生成限时签名链接交给服务商读取，取得结果后删除；选了“仅供试用”的临时上传时，'
                '音频上传到服务商临时空间，48 小时后由服务商删除。',
        cost='按音频用量计费，以 Qwen Cloud 账单为准；新账号补全付款信息后，每个模型有 90 天免费额度。'
             '单价见官方模型页（2026-10-13 核对）。用自己的 OSS 时另有很少的存储与流量费用（按阿里云国际站 OSS 价格）。',
        needs_storage=True,
        account_note='需要 Qwen Cloud 账号（home.qwencloud.com，用阿里云国际账号登录）；正式使用另需同一国际账号下的 OSS。'
                     'Qwen Cloud 的 Key 与千问AI平台（中国站）、阿里云百炼的 Key 都不能互换；'
                     'Qwen 官网 qwen.ai 的聊天登录也不能用来调用识别接口。',
        status_note='代码与离线测试已完成；本机没有 Qwen Cloud 账号，真实服务尚未验证。',
        short_title='Qwen Cloud 录音文件识别', site='Qwen 官方 API', minutes=15, money='补全付款信息后有免费额度',
        tag='另需国际站 OSS', site_variant='intl',
        walk=(StepText('account', lines=('点右上角“Get Started”，', '用阿里云国际账号登录。'),
                       shot=Shot('qwencloud-1-home.jpg', (0.855, 0.028, 0.124, 0.075), 'https://home.qwencloud.com/',
                                 '2026-10-18')),
              StepText('topup', title='补全付款信息', label='付款信息',
                       lines=('在账单页补全付款信息，', '新账号每个模型有 90 天免费额度。'), action='打开账单页'),
              StepText('key', lines=('打开 API Key 页面，', '点“Create API key”新建一把。'),
                       note='不要用 sk-sp- 开头的 Token Plan Key', note_kind='warn'),
              StepText('storage', lines=('在国际站 OSS 建一个私有 Bucket，', '再为它建一把 AccessKey。')))),
    ProviderGuide(
        'mosi_moss_pro', 'asr', 'MOSS-Transcribe-Diarize Pro 云端（MOSI 平台）',
        '云端多人转写：文字、句段时间与说话人，不需要显卡。只要一把 API Key，直接上传本地音频。'
        '没有逐字时间；要按字剪辑可再配本地对齐。',
        'mosi-moss-pro.zh-CN.md',
        links=(Link('MOSI 平台', 'https://platform.mosi.cn/'),
               Link('API Key 页面', 'https://platform.mosi.cn/app/api-keys/', needs_login=True),
               Link('在线体验', 'https://platform.mosi.cn/app/playground/', needs_login=True),
               Link('价格', 'https://platform.mosi.cn/app/pricing/'),
               Link('转写 API 文档', 'https://platform.mosi.cn/docs/reference/transcriptions/'),
               Link('多人转写教程', 'https://platform.mosi.cn/docs/scenarios/transcribe-diarization/')),
        fields=(Field('api_key', 'API Key', _KEY_HELP + '在 MOSI 控制台的 API Key 页面创建；完整密钥只显示一次。',
                      'sk-…', secret=True, hint='在 MOSI 的 API Key 页面创建，只显示一次。'),
                Field('url', 'API Base URL', '已预填，一般不用改。不要填网站地址 platform.mosi.cn。',
                      'https://api.mosi.cn/v1', prefilled='https://api.mosi.cn/v1', advanced=True,
                      hint='已预填官方地址，一般不用改。')),
        models=(ModelChoice('moss-transcribe-diarize-pro', 'moss-transcribe-diarize-pro',
                            '多人转写，单次最长 60 分钟（更长会自动分段）；热词最多 20 个',
                            speakers=True, timestamps='segment', hotwords=True),),
        uploads='识别时把本次任务的音频（16 kHz 单声道 WAV，只含音频）上传到 MOSI（api.mosi.cn）。',
        cost='MOSI 价格页：¥2.00 / 小时音频（40 积分 / 小时），按实际用量计费；失败任务是否计费官方未写明（2026-10-14 核对，以积分账单为准）。',
        status_note='代码与离线测试已完成；尚未用真实密钥实测。',
        # 2026-10-18 (user): MOSI gives free credit, so trying needs no top-up.
        # Its home page offers 50 credits a day on login (valid that day);
        # diarized transcription costs 40 credits an hour (pricing page).
        short_title='MOSS 云端识别', site='MOSI 平台', minutes=5, money='每天送免费积分，可先试',
        tag='只要一把 Key', free_trial=True, after_note='免费积分用完再充值：¥2 一小时音频。',
        walk=(StepText('account', lines=('点「立即登录领取」，', '用 Mossland 账号登录。'),
                       note='每天登录送 50 积分，约够 1 小时音频', note_kind='free', action='打开 MOSI 网站',
                       shot=Shot('mosi-1-login.jpg', (0.572, 0.84, 0.39, 0.116), 'https://platform.mosi.cn/',
                                 '2026-10-18')),
              # Signed-in pages: captured in the user's own session, keys blocked out (2026-10-18).
              StepText('key', lines=('登录后点「创建 API Key」，', '新建一把，马上复制下来。'),
                       note='完整 Key 只显示这一次', note_kind='warn',
                       shot=Shot('mosi-2-api-keys.jpg', (0.777, 0.079, 0.184, 0.071),
                                 'https://platform.mosi.cn/app/api-keys/', '2026-10-18')))),
    ProviderGuide(
        'qwen31_filetrans', 'asr', '阿里云百炼 · 录音文件识别（Qwen3-ASR / Qwen-Audio-3.1）',
        '云端识别长录音：文字与字/词级时间（Qwen-Audio-3.1 另有说话人），不需要显卡。'
        '正式使用还需要你自己的阿里云 OSS 私有存储（设置一次）。',
        'bailian-filetrans.zh-CN.md',
        links=(Link('百炼 API Key 页面（北京）', 'https://bailian.console.aliyun.com/cn-beijing/model/settings/api-key',
                    needs_login=True),
               Link('注册阿里云账号', 'https://account.aliyun.com/register/qr_register.htm'),
               Link('百炼控制台', 'https://bailian.console.aliyun.com/', needs_login=True),
               Link('获取 API Key（官方教程）', 'https://help.aliyun.com/zh/model-studio/get-api-key'),
               Link('地域与 API Host', 'https://help.aliyun.com/zh/model-studio/regions'),
               Link('Qwen-ASR API 文档', 'https://help.aliyun.com/zh/model-studio/qwen-asr-api-reference'),
               Link('录音文件识别说明', 'https://help.aliyun.com/zh/model-studio/non-realtime-speech-recognition-user-guide'),
               Link('语音识别模型与能力', 'https://help.aliyun.com/zh/model-studio/asr-model'),
               Link('OSS 控制台', 'https://oss.console.aliyun.com/', needs_login=True),
               Link('RAM 访问控制（创建 AccessKey）', 'https://ram.console.aliyun.com/', needs_login=True),
               Link('临时上传的官方限制', TEMPORARY_UPLOAD_SOURCE)),
        fields=(Field('api_host', 'API Host', '百炼控制台创建 API Key 后弹窗里的“API Host”，或“业务空间管理”页的 API Host 列；'
                      '直接贴进来，兔白会生成正确的请求地址。贴成整段网址（含 https://、/api/v1，'
                      '甚至聊天用的 /compatible-mode/v1）也可以，会自动换算。',
                      'llm-xxxxxxxx.cn-beijing.maas.aliyuncs.com',
                      hint='贴控制台里的 API Host（整段网址也行），兔白自动换算。'),
                Field('api_key', 'API Key', _KEY_HELP + '密钥与 API Host 必须是同一地域创建的。', 'sk-…', secret=True,
                      hint='与 API Host 同一地域创建的 Key，只显示一次。'),
                Field('filetrans_upload', '音频交给百炼的方式', _UPLOAD_HELP, choices=UPLOAD_CHOICES,
                      prefilled=UPLOAD_OWN_OSS, hint=_UPLOAD_HINT))
        + _oss_fields('cn-hangzhou（华东1 杭州）'),
        models=(ModelChoice('qwen3-asr-flash-filetrans', 'Qwen3-ASR-Flash 录音文件识别',
                            '字/词级时间戳（开启 enable_words），不区分说话人，不支持热词；单文件 12 小时 / 2 GB',
                            speakers=False, timestamps='word', hotwords=False),
                ModelChoice('qwen-audio-3.1-asr-flash-filetrans', 'Qwen-Audio-3.1-ASR-Flash 录音文件识别',
                            '字/词级时间戳与说话人（建议 2 小时内），支持热词与上下文；单文件 12 小时 / 2 GB',
                            speakers=True, timestamps='word', hotwords=True)),
        uploads='识别时把本次任务音频（16 kHz 单声道 WAV，只有声音，不含画面）交给百炼：正式方式是先传到你的 OSS 私有 '
                'Bucket，生成限时签名链接交给百炼读取，取得结果后删除；选了“仅供试用”的临时上传时，'
                '音频上传到百炼临时空间，48 小时后由百炼删除。',
        cost='百炼按音频时长计费（测试时兔白会从官方模型列表接口读取当前单价）；用自己的 OSS 时另有很少的存储与流量费用。',
        needs_storage=True,
        account_note='需要阿里云账号与百炼服务；密钥、API Host 与模型按地域区分、不能混用，'
                     '也不能和 Qwen Cloud 的 Key 互换。',
        status_note='Qwen-Audio-3.1 路线 2026-10-04 有真实识别记录；Qwen3-ASR 路线代码与离线测试已完成，尚未用真实密钥实测。',
        short_title='阿里云百炼 录音文件识别', site='阿里云', minutes=15, money='按音频时长计费', tag='另需阿里云 OSS',
        walk=(BAILIAN_ACCOUNT,
              StepText('key', lines=('在百炼创建 API Key，', '复制 Key 和弹窗里的 API Host。'),
                       note='Key 与 API Host 要同一地域', note_kind='warn', shot=BAILIAN_KEY_SHOT))),
    ProviderGuide(
        'spark_asr_v2', 'asr', '讯飞 Spark-ASR 2.0',
        '讯飞大模型语音识别（中英）：每约 55 秒一段的文字，没有逐字时间与说话人；按实时速度发送，识别时间约等于音频时长。',
        'iflytek-spark.zh-CN.md',
        links=(Link('服务页：AppID / APIKey / APISecret', 'https://console.xfyun.cn/services/iat_zh_cn_mandarin_spark_asr_v2',
                    needs_login=True),
               Link('讯飞开放平台', 'https://www.xfyun.cn/'),
               Link('快速指引（注册、创建应用）', 'https://www.xfyun.cn/doc/platform/quickguide.html'),
               Link('实名认证说明', 'https://www.xfyun.cn/doc/authentication/authentication.html'),
               Link('产品页：领免费额度 / 购买', 'https://www.xfyun.cn/services/spark_asr_zh_en_v2.0'),
               Link('控制台：我的应用', 'https://console.xfyun.cn/app/myapp', needs_login=True),
               Link('V2.0 接口文档', 'https://www.xfyun.cn/doc/spark/spark_zh_iat_new.html'),
               Link('错误码查询', 'https://www.xfyun.cn/document/error-code')),
        fields=(Field('app_id', 'AppID', '讯飞控制台中“语音听写大模型（中英）V2.0”服务页上的 AppID；三项必须来自同一个应用。', '',
                      hint='服务页上的 AppID（三项来自同一个应用）。'),
                Field('api_key', 'APIKey', '同一服务页上的 APIKey（32 位字符串）。', '32 位字符串', secret=True),
                Field('api_secret', 'APISecret', '同一服务页上的 APISecret（32 位字符串）；只在本机计算签名，不会原样发送。',
                      '32 位字符串', secret=True)),
        uploads='识别时把整段音频（含静音）按约 55 秒一块、以实时速度经 WebSocket 发送到讯飞（iat.cn-huabei-1.xf-yun.com）；'
                '不附文件名或词库。',
        cost='先在产品页领免费额度或购买套餐；价格与额度页面需登录查看，2026-10-14 未能读到具体数字（待核实）。',
        account_note='需要讯飞开放平台账号并完成个人实名认证，在“我的应用”建应用并开通语音听写大模型（中英）V2.0。',
        status_note='已有接入；本轮未用真实密钥重新实测。',
        short_title='讯飞 Spark-ASR 2.0', site='讯飞开放平台', minutes=10, money='先领免费额度', tag='需实名认证',
        walk=(StepText('account', lines=('注册讯飞开放平台账号，', '完成个人实名认证。'),
                       shot=Shot('spark-1-quickguide.jpg', (0.033, 0.455, 0.885, 0.225),
                                 'https://www.xfyun.cn/doc/platform/quickguide.html', '2026-10-18')),
              StepText('topup', title='领免费额度', label='领额度', lines=('在产品页领免费额度，', '或购买套餐。'),
                       action='打开产品页',
                       shot=Shot('spark-2-product.jpg', (0.077, 0.44, 0.184, 0.118),
                                 'https://www.xfyun.cn/services/spark_asr_zh_en_v2.0', '2026-10-18')),
              StepText('key', title='创建应用，复制三项', label='创建应用',
                       lines=('在“我的应用”里建一个应用，', '复制 AppID、APIKey、APISecret。'),
                       note='三项要来自同一个应用', note_kind='warn',
                       shot=Shot('spark-credentials.jpg', (0.0625, 0.236, 0.844, 0.308),
                                 'https://console.xfyun.cn/services/iat_zh_cn_mandarin_spark_asr_v2', '2026-10-18')))),
    ProviderGuide(
        'groq', 'asr', 'Groq Whisper', 'OpenAI 兼容的 Whisper 云端转写：句段时间，没有逐字时间与说话人。', 'groq.zh-CN.md',
        links=(Link('Groq API Key 页面', 'https://console.groq.com/keys', needs_login=True),
               Link('Groq 控制台（注册 / 登录）', 'https://console.groq.com/'),
               Link('你的用量限制', 'https://console.groq.com/settings/limits', needs_login=True),
               Link('语音转文字说明', 'https://console.groq.com/docs/speech-to-text'),
               Link('模型与价格', 'https://console.groq.com/docs/models'),
               Link('速率限制', 'https://console.groq.com/docs/rate-limits'),
               Link('错误码', 'https://console.groq.com/docs/errors')),
        fields=(Field('api_key', 'API Key', _KEY_HELP + '在 console.groq.com/keys 点 Create API Key 创建。', 'gsk_…',
                      secret=True, hint='在 Groq 的 Keys 页面点 Create API Key 创建。'),),
        uploads='识别时把音频分段和提示文字（字幕场景、素材文件名、专名写法）上传到 Groq（api.groq.com）。',
        cost='whisper-large-v3-turbo $0.04/小时音频，每次请求最少按 10 秒计（兔白每段不超过 10 秒，所以约等于段数 × 10 秒）；'
             '有免费档（Groq 模型页，2026-10-14 核对）。',
        account_note='需要 Groq 账号；免费档不需付款方式。中国大陆网络能否直连，兔白未实测。',
        status_note='已有接入；本轮未用真实密钥重新实测。',
        short_title='Groq Whisper', site='GroqCloud', minutes=5, money='有免费档', tag='有免费档',
        walk=(StepText('account', lines=('用 Google、GitHub 或邮箱', '注册并登录 GroqCloud。'),
                       shot=Shot('groq-1-login.jpg', (0.057, 0.087, 0.535, 0.824), 'https://console.groq.com/', '2026-10-18')),)),
    ProviderGuide(
        'openai', 'asr', 'OpenAI 转写',
        'OpenAI 的音频转写接口。默认 gpt-transcribe 只回文字（每段一个时间范围）；要句段时间请改用 whisper-1。',
        'openai-transcribe.zh-CN.md',
        links=(Link('OpenAI API Key 页面', 'https://platform.openai.com/settings/organization/api-keys', needs_login=True),
               Link('快速开始（创建 Key、加值）', 'https://developers.openai.com/api/docs/quickstart'),
               Link('语音转文字说明', 'https://developers.openai.com/api/docs/guides/speech-to-text'),
               Link('价格', 'https://developers.openai.com/api/docs/pricing'),
               Link('支持的国家和地区', 'https://developers.openai.com/api/docs/supported-countries'),
               Link('错误码', 'https://developers.openai.com/api/docs/guides/error-codes')),
        fields=(Field('api_key', 'API Key', _KEY_HELP, 'sk-…', secret=True, hint='在 OpenAI 的 API Key 页面创建。'),
                Field('model', '模型', '留空就用 gpt-transcribe（OpenAI 当前推荐的录音转写模型，2026-10-14 核对），'
                      '它不回时间戳；要句段时间请改填 whisper-1。', 'gpt-transcribe', required=False,
                      hint='留空用 gpt-transcribe（无时间戳）；要句段时间填 whisper-1。')),
        uploads='识别时把音频分段和提示文字（字幕场景、素材文件名、专名写法）上传到 OpenAI（api.openai.com）。',
        cost='预付额度；gpt-transcribe 约 $0.0045/分钟，whisper-1 $0.006/分钟（OpenAI 价格页，2026-10-14 核对）。',
        account_note='需要 OpenAI 开发者平台账号并加值；中国大陆、香港、澳门不在官方支持地区。',
        status_note='已有接入；本轮未用真实密钥重新实测。',
        short_title='OpenAI 转写', site='OpenAI 开发者平台', minutes=5, money='需先加值', tag='不支持中国大陆',
        walk=(StepText('account', lines=('点官方快速开始页的', '「Create an API Key」登录。'),
                       shot=Shot('openai-1-quickstart.jpg', (0.028, 0.227, 0.34, 0.146),
                                 'https://developers.openai.com/api/docs/quickstart', '2026-10-18')),)),
    ProviderGuide(
        # 2026-10-14: there is no "MAI 2.1" transcription model (mai-voice-2.1
        # is text-to-speech). 2026-10-25: MAI-Transcribe 2 is accepted again
        # and preset; one real call returned word times and two speakers.
        'openrouter_word', 'asr', 'OpenRouter 语音转文字（进阶）',
        '经 OpenRouter 调用的转写模型，预设微软 MAI-Transcribe 2：字级时间、区分说话人。也可以填其他模型 ID（兔白未实测）。',
        'openrouter.zh-CN.md',
        links=(Link('OpenRouter API Key 页面', 'https://openrouter.ai/keys', needs_login=True),
               Link('OpenRouter 官网（注册 / 登录）', 'https://openrouter.ai/'),
               Link('充值（Credits）', 'https://openrouter.ai/settings/credits', needs_login=True),
               Link('方案与平台费', 'https://openrouter.ai/pricing'),
               Link('语音转文字模型与单价', 'https://openrouter.ai/collections/speech-to-text-models'),
               Link('语音转文字说明', 'https://openrouter.ai/docs/guides/overview/multimodal/stt'),
               Link('错误码', 'https://openrouter.ai/docs/api_reference/errors-and-debugging')),
        fields=(Field('api_key', 'API Key', _KEY_HELP + '在 openrouter.ai/keys 创建，建议设额度上限。', '（整串贴上）',
                      secret=True, hint='在 OpenRouter 的 Keys 页面创建，建议设额度上限。'),
                Field('model', '模型 ID', '已预填 microsoft/mai-transcribe-2（MAI-Transcribe 2），一般不用改。'
                      '也可以从 OpenRouter 语音转文字模型列表复制其他“厂商/模型”格式的 ID（兔白未实测）；'
                      'microsoft/mai-transcribe-1.5 拿不到时间。',
                      'microsoft/mai-transcribe-2', prefilled='microsoft/mai-transcribe-2',
                      hint='已预填 MAI-Transcribe 2，一般不用改。')),
        uploads='识别时把音频分段上传到 OpenRouter（openrouter.ai）及其转发的模型提供方。',
        cost='按模型单价（美元）：mai-transcribe-2 $0.10/小时、mai-transcribe-1.5 $0.36/小时、whisper-large-v3-turbo 约 $0.012/小时；'
             '买额度另收 5.5% 平台费（2026-10-14 核对，以账单为准）。',
        account_note='需要 OpenRouter 账号并先充值（转写模型没有免费额度）；Key 可设额度上限。',
        status_note='2026-10-25 用真实 Key 识别过一段 20 秒的中英两人录音：MAI-Transcribe 2 返回字级时间并分出两位说话人。其他模型兔白未实测。',
        advanced_only=True,
        site='OpenRouter', minutes=5, money='需先充值',
        walk=(StepText('account', shot=Shot('openrouter-1-home.jpg', (0.888, 0.011, 0.079, 0.06), 'https://openrouter.ai/',
                                            '2026-10-18')),)),
    ProviderGuide(
        'azure', 'asr', 'Azure OpenAI 部署式转写（进阶）',
        '调用你在 Azure OpenAI 资源里部署的转写模型（例如 whisper）：句段时间、无说话人。'
        'MAI-Transcribe 走 Azure Speech 的另一种接口，这一项不能用。', 'azure.zh-CN.md',
        links=(Link('Key 与 Endpoint 位置（官方快速入门）',
                    'https://learn.microsoft.com/en-us/azure/foundry/openai/whisper-quickstart'),
               Link('注册 Azure（免费账户）', 'https://azure.microsoft.com/en-us/pricing/purchase-options/azure-account'),
               Link('Azure 门户', 'https://portal.azure.com/', needs_login=True),
               Link('Microsoft Foundry 门户（部署模型）', 'https://ai.azure.com/', needs_login=True),
               Link('建资源与部署模型（官方教程）',
                    'https://learn.microsoft.com/en-us/azure/foundry-classic/openai/how-to/create-resource'),
               Link('转写接口说明', 'https://learn.microsoft.com/en-us/azure/foundry/openai/reference'),
               Link('价格', 'https://azure.microsoft.com/en-us/pricing/details/azure-openai/')),
        fields=(Field('url', '部署地址', '资源 Endpoint + openai/deployments/<部署名称>/audio/transcriptions?api-version='
                      '2024-10-21，整串贴上；兔白不补路径。',
                      'https://myres.openai.azure.com/openai/deployments/my-whisper/audio/transcriptions?api-version=2024-10-21',
                      hint='整串贴上部署的转写地址（含 api-version）。'),
                Field('api_key', 'API Key', _KEY_HELP + 'Azure 门户 → 资源 → Keys & Endpoint 的 KEY1 或 KEY2。', '',
                      secret=True, hint='资源的 Keys & Endpoint 页里的 KEY1 或 KEY2。'),
                Field('model', '部署名称', '部署模型时自己取的 Deployment name（区分大小写），应与部署地址里 /deployments/ '
                      '后面那一段相同。兔白只用它显示名称；实际调用哪个部署只看部署地址。', 'my-whisper',
                      hint='与部署地址里 /deployments/ 后面那一段相同。')),
        uploads='识别时把音频分段和提示文字（字幕场景、素材文件名、专名写法）上传到你的 Azure 资源。',
        cost='按部署的模型计费；2026-10-14 Azure OpenAI 价格页的转写单价显示为“$-”，未能确定，以 Azure 账单为准。',
        account_note='需要 Azure 订阅、一个 Azure OpenAI 资源和一个转写模型部署（建议 whisper）。',
        status_note='兔白未用真实密钥实测；属于进阶设置。', advanced_only=True,
        site='Azure', minutes=20, money='按部署的模型计费',
        walk=(StepText('account', shot=Shot('azure-1-account.jpg', (0.255, 0.547, 0.207, 0.109),
                                            'https://azure.microsoft.com/en-us/pricing/purchase-options/azure-account', '2026-10-18')),
              StepText('key', title='找到 Key 与 Endpoint', label='找 Key', lines=('官方快速入门写了', 'Key 与 Endpoint 在哪里。'),
                       action='打开快速入门',
                       shot=Shot('azure-2-whisper.jpg', (0.763, 0.433, 0.192, 0.044),
                                 'https://learn.microsoft.com/en-us/azure/foundry/openai/whisper-quickstart', '2026-10-18')))),
    ProviderGuide(
        'custom', 'asr', '自定义 OpenAI 兼容转写', '你自己架设或其他服务商的 OpenAI 兼容 /audio/transcriptions 接口。',
        'custom-asr.zh-CN.md',
        links=(Link('OpenAI 转写接口格式（参考）',
                    'https://developers.openai.com/api/reference/resources/audio/subresources/transcriptions/methods/create'),),
        fields=(Field('url', '完整请求 Endpoint', '原样使用：兔白不会补 /v1 或 /audio/transcriptions；只能 https，不能带 ?参数。',
                      'https://example.com/v1/audio/transcriptions', hint='完整请求地址，原样使用（不会自动补 /v1）。'),
                Field('model', '模型', '放进请求的 model 名称，不能空；照服务说明或它的 /models 列表填写。', 'whisper-1'),
                Field('api_key', 'API Key', _KEY_HELP + '服务不检查 Key 时也要随便填一串（例如 local）——兔白要求不能空。', '',
                      secret=True, hint='服务不检查 Key 时也要随便填一串（例如 local）。')),
        uploads='识别时把音频分段（16 kHz 单声道 WAV）和提示文字（字幕场景、素材文件名、专名写法）上传到你填写的地址。',
        cost='由你使用的服务决定，兔白无法估算。',
        status_note='进阶设置；一般使用者不需要。', advanced_only=True),
)

TEXT_GUIDES = (
    # Links checked 2026-10-14 (official pages; login pages marked).
    ProviderGuide('deepseek', 'text', 'DeepSeek', '文字 AI：AI 断句、字幕校对、翻译。只发送字幕文字，不发送音频。',
                  'deepseek.zh-CN.md', uploads='发送字幕文字到 DeepSeek（api.deepseek.com）。',
                  links=(Link('DeepSeek API Keys 页面', 'https://platform.deepseek.com/api_keys', needs_login=True),
                         Link('注册 / 登录', 'https://platform.deepseek.com/sign_in'),
                         Link('充值', 'https://platform.deepseek.com/top_up', needs_login=True),
                         Link('模型与价格', 'https://api-docs.deepseek.com/zh-cn/quick_start/pricing'),
                         Link('错误码', 'https://api-docs.deepseek.com/zh-cn/quick_start/error_codes')),
                  site='DeepSeek 开放平台', minutes=5, money='先充 10 元',
                  walk=(StepText('account', lines=('用手机号收验证码登录，', '没注册过会自动注册。'),
                                 shot=Shot('deepseek-1-signin.jpg', (0.076, 0.300, 0.479, 0.612),
                                           'https://platform.deepseek.com/sign_in', '2026-10-18')),
                        StepText('topup', title='先充值 10 元', lines=('10 元就够先用一阵，', '用多少扣多少。'),
                                 shot=Shot('deepseek-2-topup.jpg', (0.038, 0.286, 0.072, 0.078),
                                           'https://platform.deepseek.com/top_up', '2026-10-18')),
                        StepText('key', note='完整 Key 只显示这一次', note_kind='warn',
                                 shot=Shot('deepseek-3-api-keys.jpg', (0.806, 0.290, 0.132, 0.070),
                                           'https://platform.deepseek.com/api_keys', '2026-10-18')))),
    ProviderGuide('bailian', 'text', '阿里云百炼（通义千问）', '文字 AI：AI 断句、字幕校对、翻译。可与语音识别共用同一地域的 API Key。',
                  'bailian-text.zh-CN.md', uploads='发送字幕文字到百炼。',
                  links=(Link('百炼 API Key 页面（北京）', 'https://bailian.console.aliyun.com/cn-beijing/model/settings/api-key',
                              needs_login=True),
                         Link('注册阿里云账号', 'https://account.aliyun.com/register/qr_register.htm'),
                         Link('地域与接入域名', 'https://help.aliyun.com/zh/model-studio/regions'),
                         Link('OpenAI 兼容说明', 'https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope'),
                         Link('模型价格', 'https://help.aliyun.com/zh/model-studio/model-pricing'),
                         Link('错误码', 'https://help.aliyun.com/zh/model-studio/error-code')),
                  site='阿里云', minutes=5, money='按用量计费',
                  walk=(BAILIAN_ACCOUNT,
                        StepText('key', note='完整 Key 只显示这一次', note_kind='warn', shot=BAILIAN_KEY_SHOT))),
    ProviderGuide('openai', 'text', 'OpenAI', '文字 AI：AI 断句、字幕校对、翻译。', 'openai-text.zh-CN.md',
                  uploads='发送字幕文字到 OpenAI。',
                  links=(Link('OpenAI API Key 页面', 'https://platform.openai.com/settings/organization/api-keys',
                              needs_login=True),
                         Link('注册 / 登录（OpenAI 平台）', 'https://platform.openai.com/', needs_login=True),
                         Link('账单', 'https://platform.openai.com/settings/organization/billing', needs_login=True),
                         Link('支持的国家和地区', 'https://developers.openai.com/api/docs/supported-countries'),
                         Link('价格', 'https://developers.openai.com/api/docs/pricing'),
                         Link('错误码', 'https://developers.openai.com/api/docs/guides/error-codes')),
                  site='OpenAI 开发者平台', minutes=5, money='需先加值',
                  walk=(StepText('topup', title='先加值', label='加值', lines=('在账单页加值，', '用多少扣多少。'),
                                 action='打开账单页'),)),
    # 2026-10-18: Claude through the Anthropic Messages API; links checked that day.
    ProviderGuide('claude', 'text', 'Anthropic Claude', '文字 AI：AI 断句、字幕校对、翻译、AI 特效字幕。', 'claude.zh-CN.md',
                  uploads='发送字幕文字到 Anthropic（api.anthropic.com）；AI 特效字幕可能附带画面截图。',
                  links=(Link('Claude Console API Keys 页面', 'https://platform.claude.com/settings/keys',
                              checked='2026-10-18', needs_login=True),
                         Link('注册 / 登录（Claude Console）', 'https://platform.claude.com/', checked='2026-10-18'),
                         Link('账单与充值', 'https://platform.claude.com/settings/billing', checked='2026-10-18',
                              needs_login=True),
                         Link('获取 API Key 说明', 'https://platform.claude.com/docs/en/get-api-key', checked='2026-10-18'),
                         Link('支持的国家和地区', 'https://www.anthropic.com/supported-countries', checked='2026-10-18'),
                         Link('价格', 'https://platform.claude.com/docs/en/about-claude/pricing', checked='2026-10-18'),
                         Link('错误码', 'https://platform.claude.com/docs/en/api/errors', checked='2026-10-18')),
                  site='Claude Console', minutes=5, money='需先充值',
                  walk=(StepText('account', lines=('用 Google 或电子邮箱', '注册并登录 Claude Console。'),
                                 shot=Shot('claude-1-login.jpg', (0.233, 0.364, 0.534, 0.406),
                                           'https://platform.claude.com/', '2026-10-18')),)),
    ProviderGuide('gemini', 'text', 'Google Gemini', '文字 AI：AI 断句、字幕校对、翻译（OpenAI 兼容接口）。', 'gemini.zh-CN.md',
                  uploads='发送字幕文字到 Google。',
                  links=(Link('Google AI Studio API Key 页面', 'https://aistudio.google.com/apikey', needs_login=True),
                         Link('API Key 说明', 'https://ai.google.dev/gemini-api/docs/api-key'),
                         Link('可用地区', 'https://ai.google.dev/gemini-api/docs/available-regions'),
                         Link('价格', 'https://ai.google.dev/gemini-api/docs/pricing'),
                         Link('错误码', 'https://ai.google.dev/gemini-api/docs/api-errors')),
                  site='Google AI Studio', minutes=5, money='按用量计费',
                  walk=(StepText('account', lines=('用 Google 账号登录，', '没有就点“创建账号”。'),
                                 shot=Shot('gemini-1-google.jpg', (0.704, 0.66, 0.228, 0.083),
                                           'https://aistudio.google.com/apikey', '2026-10-18')),)),
    ProviderGuide('xai', 'text', 'xAI Grok API', '文字 AI：AI 断句、字幕校对、翻译。', 'xai.zh-CN.md', uploads='发送字幕文字到 xAI。',
                  links=(Link('xAI API Keys 页面', 'https://console.x.ai/team/default/api-keys', needs_login=True),
                         Link('xAI 控制台（注册 / 登录）', 'https://console.x.ai/'),
                         Link('入门', 'https://docs.x.ai/docs/tutorial'),
                         Link('模型与价格', 'https://docs.x.ai/docs/models'),
                         Link('错误码', 'https://docs.x.ai/docs/key-information/debugging')),
                  site='xAI 控制台', minutes=5, money='按用量计费',
                  walk=(StepText('account', lines=('点“Create an account”注册，', '已有账号点“Sign in”。'),
                                 shot=Shot('xai-1-console.jpg', (0.039, 0.446, 0.472, 0.107), 'https://console.x.ai/',
                                           '2026-10-18')),)),
    ProviderGuide('custom', 'text', '自定义 OpenAI 兼容服务', '你自己架设或其他服务商的 OpenAI 兼容聊天接口。', 'custom-text.zh-CN.md',
                  uploads='发送字幕文字到你填写的地址。', advanced_only=True),
    ProviderGuide('cli_accounts', 'text', '账号登录类（Grok / Codex / Antigravity CLI）',
                  '用你已登录的命令行工具账号调用文字 AI，不需要 API Key。', 'cli-accounts.zh-CN.md',
                  uploads='发送字幕文字到对应账号的服务。', advanced_only=True,
                  links=(Link('Grok Build 入门', 'https://docs.x.ai/build/overview'),
                         Link('Codex CLI', 'https://learn.chatgpt.com/docs/codex/cli'),
                         Link('Antigravity CLI 入门', 'https://antigravity.google/docs/getting-started?tab=cli'))),
)

# List order in the dialog (2026-10-14, ADR 0112): the one-key route first,
# then the two 录音文件识别 entries that also need the user's own OSS.
_FIRST = ('mosi_moss_pro', 'qwen_cloud_filetrans', 'qwen31_filetrans')
ASR_GUIDES = tuple(sorted(ASR_GUIDES, key=lambda g: _FIRST.index(g.key) if g.key in _FIRST else len(_FIRST)))
ALL_GUIDES = ASR_GUIDES + TEXT_GUIDES
# 录音文件识别 entries: audio is handed over by URL (official temporary upload or own OSS).
FILETRANS_GUIDES = frozenset({'qwen_cloud_filetrans', 'qwen31_filetrans'})

# 2026-10-25: the official Qwen API on its mainland site, 千问AI平台. It is the
# same entry as Qwen Cloud (same key, models and protocol, different host,
# account and keys): the setup dialog switches between the two, the saved
# address says which one is in use, and the Simplified Chinese interface starts
# here. Not in ALL_GUIDES, so the provider list keeps one row for both.
# Sources (checked 2026-10-25): https://platform.qianwenai.com/docs/api-reference/preparation/api-key ,
# .../speech-recognition/fun-asr-recording/restful-api , .../preparation/error-messages ,
# https://platform.qianwenai.com/docs/developer-guides/speech/speech-to-text-models
_QWEN_CLOUD = next(g for g in ASR_GUIDES if g.key == 'qwen_cloud_filetrans')
QIANWEN_CHECKED = '2026-10-25'
QIANWEN_FILETRANS_GUIDE = ProviderGuide(
    'qwen_cloud_filetrans', 'asr', '千问AI平台（Qwen 官方中国站）· 录音文件识别',
    '云端识别：文字与字/词级时间（Qwen-Audio-3.1 另有说话人），不需要显卡。'
    '正式使用还需要你自己的阿里云 OSS 私有存储（设置一次）。',
    'qianwen-filetrans.zh-CN.md',
    links=(Link('千问AI平台控制台（注册 / 登录）', 'https://platform.qianwenai.com/home', checked=QIANWEN_CHECKED),
           Link('API Key 页面', 'https://platform.qianwenai.com/home/api-keys', needs_login=True, checked=QIANWEN_CHECKED),
           Link('账单：实名认证与充值', 'https://platform.qianwenai.com/home/billing/overview', needs_login=True,
                checked=QIANWEN_CHECKED),
           Link('新用户体验额度', 'https://www.qianwenai.com/benefits', checked=QIANWEN_CHECKED),
           Link('获取 API Key（官方说明）', 'https://platform.qianwenai.com/docs/api-reference/preparation/api-key',
                checked=QIANWEN_CHECKED),
           Link('语音识别模型与限制', 'https://platform.qianwenai.com/docs/developer-guides/speech/speech-to-text-models',
                checked=QIANWEN_CHECKED),
           Link('模型价格', 'https://platform.qianwenai.com/pricing/api', checked=QIANWEN_CHECKED),
           Link('录音文件识别 API',
                'https://platform.qianwenai.com/docs/api-reference/speech-recognition/fun-asr-recording/restful-api',
                checked=QIANWEN_CHECKED),
           Link('错误码说明', 'https://platform.qianwenai.com/docs/api-reference/preparation/error-messages',
                checked=QIANWEN_CHECKED),
           Link('OSS 控制台', 'https://oss.console.aliyun.com/', needs_login=True, checked=QIANWEN_CHECKED),
           Link('RAM 访问控制（创建 AccessKey）', 'https://ram.console.aliyun.com/', needs_login=True, checked=QIANWEN_CHECKED),
           Link('临时上传的官方限制', TEMPORARY_UPLOAD_SOURCE, checked=QIANWEN_CHECKED)),
    fields=(Field('api_key', 'API Key', _KEY_HELP + '在千问AI平台的 API Key 页面点“创建 API Key”生成，sk-ws- 开头'
                  '（早期创建的是 sk- 开头）；完整密钥只显示一次。不要用 Token Plan 订阅专用 Key（sk-sp- 开头），'
                  '它不能做录音文件识别。', 'sk-ws-…', secret=True,
                  hint='在千问AI平台的 API Key 页面创建，只显示一次（不要用 sk-sp- 开头的 Token Plan Key）。'),
            Field('url', '服务地址', '已预填千问AI平台官方地址（北京），一般不用改。',
                  'https://maas.qianwenaiapi.com', prefilled='https://maas.qianwenaiapi.com', advanced=True,
                  hint='已预填官方地址（北京），一般不用改。'),
            Field('filetrans_upload', '音频交给服务商的方式', _UPLOAD_HELP, choices=UPLOAD_CHOICES,
                  prefilled=UPLOAD_OWN_OSS, hint=_UPLOAD_HINT))
    + _oss_fields('cn-beijing（华北2 北京，与千问AI平台服务同地）'),
    models=_QWEN_CLOUD.models,
    uploads='识别时把本次任务的音频（16 kHz 单声道 WAV，只有声音，不含画面）交给千问AI平台：正式方式是先传到你的 OSS '
            '私有 Bucket，生成限时签名链接交给服务商读取，取得结果后删除；选了“仅供试用”的临时上传时，'
            '音频上传到服务商临时空间，48 小时后由服务商删除。',
    cost='按音频用量计费，以千问AI平台账单为准；新用户注册有体验额度（哪些模型可用以控制台为准）。'
         '单价见官方定价页。用自己的 OSS 时另有很少的存储与流量费用。',
    needs_storage=True,
    account_note='需要千问AI平台账号（platform.qianwenai.com，用阿里云账号或手机号登录）；正式使用另需阿里云 OSS。'
                 '千问AI平台的 Key 与 Qwen Cloud（国际站）、阿里云百炼的 Key 都不能互换；'
                 '千问 App 的聊天登录也不能用来调用识别接口。',
    status_note='接口与 Qwen Cloud 相同，代码与离线测试已完成；本机没有千问AI平台账号，真实服务尚未验证。',
    short_title='千问AI平台 录音文件识别', site='Qwen 官方 API', minutes=15, money='新用户有体验额度',
    tag='另需阿里云 OSS', site_variant='cn',
    walk=(StepText('account', lines=('点右上角“登录”，', '用手机号或阿里云账号登录。'),
                   shot=Shot('qianwen-1-home.jpg', (0.855, 0.024, 0.124, 0.08), 'https://platform.qianwenai.com/home',
                             '2026-10-25')),
          StepText('topup', title='认证与充值', label='充值',
                   lines=('新用户先有体验额度；', '用完后完成实名认证并充值。'), action='打开账单页'),
          StepText('key', lines=('打开 API Key 页面，', '点“创建 API Key”新建一把。'),
                   note='不要用 sk-sp- 开头的 Token Plan Key', note_kind='warn'),
          StepText('storage', lines=('在阿里云 OSS 建一个私有 Bucket，', '再为它建一把 AccessKey。'))))
QWEN_SITE_GUIDES = {'cn': QIANWEN_FILETRANS_GUIDE, 'intl': _QWEN_CLOUD}
QWEN_SITES = (('cn', '中国站（千问AI平台）'), ('intl', '国际站（Qwen Cloud）'))


def qwen_site_for(url: str = '', language: str | None = None) -> str:
    """'cn' or 'intl' for the Qwen entry: a saved address decides, otherwise
    the interface language (Simplified Chinese starts on 千问AI平台)."""
    if str(url or '').strip():
        from .api_endpoints import EndpointInputError, parse_dashscope_address
        try:
            address = parse_dashscope_address(url)
        except EndpointInputError:
            address = None
        if address is not None and address.qwen_site:
            return address.qwen_site
        if address is not None and address.host == 'dashscope-intl.aliyuncs.com':
            return 'intl'
    if language is None:
        try:
            from ..i18n import current_language
            language = current_language()
        except Exception:
            language = 'zh'
    return 'cn' if language == 'zh' else 'intl'


def guide_for(key: str, kind: str = 'asr', *, url: str = '') -> ProviderGuide | None:
    """The guide of one entry; ``url`` (a saved address) picks the Qwen site."""
    if kind == 'text' and key in {'grok_account', 'codex_cli', 'antigravity'}:
        key = 'cli_accounts'
    if kind == 'asr' and key == 'qwen_cloud_filetrans' and url:
        return QWEN_SITE_GUIDES[qwen_site_for(url, language='')]
    return next((g for g in ALL_GUIDES if g.key == key and g.kind == kind), None)


# Default step texts of the walkthrough; a guide's ``walk`` overrides them.
TOPUP_WORDS = ('充值', '账单', 'Credits', '积分', '领免费额度')
_STEP_DEFAULTS = {
    'account': StepText('account', title='注册并登录', label='注册登录', lines=('打开官网，', '注册一个账号并登录。'),
                        action='打开官网'),
    'topup': StepText('topup', title='先充值', label='充值', lines=('登录后先充值一点，', '用多少扣多少。'),
                      action='打开充值页'),
    'key': StepText('key', title='创建 API Key', label='创建 Key', lines=('在 API Key 页面新建一把，', '马上复制下来。'),
                    action='打开 API Key 页面'),
    'storage': StepText('storage', title='建私有 OSS 与 AccessKey', label='建 OSS',
                        lines=('建一个私有 Bucket，', '再为它建一把 AccessKey。'),
                        note='只授权这个 Bucket，不要用主账号', note_kind='warn', action='打开 OSS 控制台'),
}
FILL_TITLE = '贴到“AI 智能断句设置”并测试'
FILL_LINES = ('到“AI 智能断句设置”里', '贴上密钥，按“测试连接”。')
FILL_NOTE = '文字 AI 只发送字幕文字'
FILL_ACTION = '去填写这家服务的密钥'


def paste_title(guide: ProviderGuide) -> str:
    if guide.key == 'spark_asr_v2':
        return '把三项贴到这里'
    if guide.needs_storage:
        return '贴上 Key 和存储信息'
    if guide.key in {'custom', 'azure'}:
        return '填写接口信息'
    return '把 Key 贴到这里'


def walkthrough(guide: ProviderGuide | None, *, can_fill: bool = False) -> list[WalkStep]:
    """The steps a first-time user follows, in order (2026-10-18 redesign).

    注册登录 › (先充值, unless the service gives free credit to try) › 创建 Key
    › (录音文件识别: 私有 OSS) › 贴上检查 (语音识别) or 去填写 (文字 AI, whose
    key is entered in “AI 智能断句设置”). Each web step opens the official page
    from ``links``. Services without official links (自定义、账号登录类) have
    no walkthrough: the dialog shows their form or notes directly.
    """
    if guide is None or not guide.links or guide.key in {'custom', 'cli_accounts'}:
        return []
    links = list(guide.links)
    if guide.kind == 'asr':
        key_link = next((item for item in links if 'key' in item.label.lower() or 'AppID' in item.label), links[0])
        signup = next((item for item in links if '注册' in item.label),
                      next((item for item in links if not item.needs_login and item is not key_link), key_link))
    else:
        key_link = next((item for item in links if 'key' in item.label.lower()), links[0])
        signup = next((item for item in links if '注册' in item.label), key_link)
    plan = [('account', signup.url)]
    topup = None if guide.free_trial else next(
        (item for item in links if any(word in item.label for word in TOPUP_WORDS)), None)
    if topup is not None:
        plan.append(('topup', topup.url))
    plan.append(('key', key_link.url))
    if guide.kind == 'asr' and guide.needs_storage:
        oss = next((item for item in links if 'OSS 控制台' in item.label), None)
        if oss is not None:
            plan.append(('storage', oss.url))
    overrides = {text.role: text for text in guide.walk}
    steps = []
    for role, url in plan:
        base, own = _STEP_DEFAULTS[role], overrides.get(role)
        if own is None:
            steps.append(WalkStep(role, base.label, base.title, base.lines, base.note, base.note_kind, url, base.action))
            continue
        note, kind = (own.note, own.note_kind) if own.note else (base.note, base.note_kind)
        steps.append(WalkStep(role, own.label or base.label, own.title or base.title, own.lines or base.lines,
                              note, kind, url, own.action or base.action, own.shot))
    if guide.kind == 'asr':
        steps.append(WalkStep('paste', '贴上检查', paste_title(guide)))
    else:
        steps.append(WalkStep('fill', '去填写', FILL_TITLE, FILL_LINES, FILL_NOTE, '',
                              action=FILL_ACTION if can_fill else ''))
    return steps


def model_choice(guide: ProviderGuide, model: str) -> ModelChoice | None:
    return next((m for m in guide.models if m.model == model), None)


def visible_field(spec: Field, values: dict) -> bool:
    if not spec.show_when:
        return True
    key, wanted = spec.show_when
    return str(values.get(key) or '') == wanted


def resolve_upload_mode(models: dict, provider: str = '', *, has_oss_credentials: bool | None = None) -> str:
    """``own_oss``, ``provider_temporary`` or ``missing`` for a 录音文件识别 run.

    An explicit choice is kept (``provider_temporary`` only ever comes from the
    user picking the trial upload). ``auto`` uses a complete OSS setup (bucket
    and AccessKey saved) and otherwise reports ``missing``: the trial upload is
    never chosen on the user's behalf (ADR 0112). Bailian and Qwen Cloud share
    the same rule.
    """
    models = models or {}
    choice = str(models.get('filetrans_upload') or 'auto')
    if choice in {UPLOAD_PROVIDER, UPLOAD_OWN_OSS}:
        return choice
    if not str(models.get('oss_bucket') or '').strip():
        return UPLOAD_MISSING
    if has_oss_credentials is None:
        try:
            from .llm_config import read_oss_credentials
            has_oss_credentials = all(read_oss_credentials())
        except Exception:
            has_oss_credentials = False
    return UPLOAD_OWN_OSS if has_oss_credentials else UPLOAD_MISSING


def upload_mode_label(mode: str) -> str:
    """Plain words for the pre-run summary and diagnostics."""
    return {UPLOAD_OWN_OSS: '你自己的 OSS 私有存储（正式）',
            UPLOAD_PROVIDER: '服务商临时上传（仅供试用，官方说明勿用于生产）',
            UPLOAD_MISSING: '尚未设置（识别前会停下说明）'}.get(str(mode), str(mode))


def uses_own_storage(guide: ProviderGuide | None, values: dict) -> bool:
    return bool(guide is not None and guide.needs_storage
                and str(values.get('filetrans_upload') or '') == UPLOAD_OWN_OSS)


def oss_endpoint_for_region(region: str) -> str:
    region = str(region or '').strip()
    return f'https://oss-{region}.aliyuncs.com' if region else ''
