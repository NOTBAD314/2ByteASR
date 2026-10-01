"""Phase budgets and the bounded subtitle-only authoring contract."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ThemeGenerationLimits:
    concepts: float = 90.
    theme: float = 90.
    inactivity: float = 45.
    read_idle: float = 120.
    warning: float = 120.

    @classmethod
    def from_settings(cls, models, override=None):
        mode = models.get('ai_design_wait_mode', 'configured')
        value = override or {'long15':900, 'long30':1800, 'long60':3600}.get(mode) or models.get('ai_design_cli_timeout_seconds') or models.get('ai_design_timeout_seconds') or 90
        # Respect the existing user setting. The authored route must not turn
        # a configured 300 s CLI budget into an unconditional 89/90 s limit.
        try: base = max(1., min(3600., float(value)))
        except (ValueError, TypeError): base = 90.
        idle = min(base, float(models.get('ai_design_no_response_seconds', 600 if base>900 else 240 if base>90 else 45)))
        return cls(base, base, max(1.,idle), min(base,max(1.,float(models.get('ai_design_read_idle_seconds',300)))), min(120.,base))

    def transport_policy(self):
        return DesignTransportPolicy(total=self.concepts,read_idle=self.read_idle,queue=min(30.,self.concepts))


@dataclass(frozen=True)
class DesignTransportPolicy:
    connect: float = 15.
    read_idle: float = 300.
    total: float = 1800.
    queue: float = 30.
    deadline_monotonic: float | None = None


def authored_request_budget(provider, models, override=None, *, candidate_count=3):
    """Reasoning and final artwork share the provider's completion allowance.

    DeepSeek's full-design route enables reasoning. Reserve room for both phases
    and expose the effective deadline without mutating the user's configuration.
    An explicit per-request deadline remains absolute; precision patches do not
    use this policy.
    """
    limits=ThemeGenerationLimits.from_settings(models,override)
    tokens=24000 if candidate_count==3 else 10000
    if provider=='deepseek':
        tokens=48000 if candidate_count==3 else 32000
        # Reasoning changes the output allowance, never the user's total wait.
    return tokens,limits


SUBTITLE_CODE_SYSTEM = '''你是字幕主题设计师。只实现输入 selected_concept 的一个完整轻量主题。
用户 brief 的主体、配色、构图、透明范围和三段动作优先。不要再次构思候选，不解释过程。
只输出以下九个分节（全部出现），不要 Markdown 围栏、不要脚本，不要网络资源：
===NAME===
主题短名
===CONCEPT===
实现承诺清单：标注实际背景、内外边界、文字材质、关键词、局部效果与三段主题动作的 .class。默认有风格依据的概念化 UI 字幕；抽象概念表达不等于抽象画或像素小插画。没有角色也要保留充分的框体、字面和动作设计。花色、筹码纹理、贴签与封签可服务字幕；仅按当前用户明确要求启用角色主角。
===PALETTE===
primary=#RRGGBB secondary=#RRGGBB background=#RRGGBB accent=#RRGGBB text=#RRGGBB
===APPEARANCE===
fontFamily="Microsoft YaHei UI", "Noto Sans SC", sans-serif
fontSize=58
color=#RRGGBB
strokeColor=#RRGGBB
strokeWidth=3
letterSpacing=1
===STAGE_HTML===
===STAGE_CSS===
===CUE_HTML===
字幕簇 HTML，正文用 {{text}} 或直接放在行容器中的 {{words}}。
===CUE_CSS===
完整 CSS
===NOTES===
一句使用说明

约束：
- stage 两节使用空 div 和 display:none CSS 保持透明；不添加暗角、全屏光晕、背景板。全部可见元素留在 x=5%..95%、y=75%..95%，紧贴字幕。
- 必须声明 .wt-cue{position:absolute;inset:0;width:100%;height:100%} 建立全画布坐标；内层字幕簇 bottom:5%，left:50%，用 translateX(-50%) 居中。字不能被物件遮挡。
- 文本必须消费 font-family:var(--wt-font);font-size:var(--wt-size)，中文粗体与清晰描边。保留用户显式换行；长句在安全区域内显示前稳定软换行，字号保持，不裁字。
- 使用 HTML div/span/i/b/strong 或内联 SVG；SVG 必须 viewBox。禁止 script/事件属性/@import/外链 url。CSS 括号配对。
- 所有 keyframes 以 wt- 开头；入场和出场作用于内层字幕簇，transform/opacity 为主；出场 delay:calc(var(--wt-dur) - 0.4s)。同元素的延迟出场使用 forwards，不能用 backwards/both 覆盖入场。正文不循环。
- 阅读期最多一个有语义的局部细节动作；禁止infinite、随机粒子、正文弹跳。默认设计明确主体轮廓、内外边框、明暗层次、边角与文字留白；材质与 brief 一致，不能只有黑条白字黄块。入场分层落位、正文随后稳定；阅读期局部活性；出场分层收束且在终点前完成。不要整块闪现、硬切或仅透明度变化。
- 用 calc(N * var(--wt-u)) 表示尺寸（1u=1080高画布的12px）；字号用 var(--wt-size)。总 HTML+CSS<=18000字符，优先简洁完整。
'''
