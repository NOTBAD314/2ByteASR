"""One explicitly bounded Grok repair using necessary browser screenshots."""
import json,os,sys,time
from pathlib import Path
from dataclasses import asdict

def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    source=Path(sys.argv[1]);out=source/'repair-1';out.mkdir(exist_ok=True)
    os.environ.update(LOCALAPPDATA=str(out/'local'),APPDATA=str(out/'roaming'),QT_QPA_PLATFORM='offscreen')
    from PIL import Image
    # Actual browser screenshots, cropped to necessary artwork; exclude chat,
    # author avatar and all browser/system UI from the repair payload.
    Image.open(source/'browser/light-hold.png').crop((24,166,810,698)).save(out/'position.png')
    Image.open(source/'browser/game-hold.png').crop((310,395,720,478)).save(out/'type-detail.png')
    scores=dict(readability=7,hierarchy=6,theme_relevance=8,typography=5,material=5,color_restraint=8,motion=7,originality=6,subject_clearance=2,sticker_restraint=7)
    review=dict(reviewer='Codex native visual inspection',passed=False,scores=scores,
        defects=['字幕整组错误居中，遮挡游戏主体；必须回到底部安全区','字体仍像普通直播描边字，材质对比不够精细'])
    (out/'before-scores.json').write_text(json.dumps(review,ensure_ascii=False,indent=2),encoding='utf8')
    instruction='根据附带真实浏览器截图，只修以下失败项，保留雪绒刹停的白熊头、雪镜、浅雪痕、滑入刹停和三段动作，不改为其他构图。'+json.dumps(review,ensure_ascii=False)+'''。
1. 第一张图是实际浅色画布，整组错误在y50%。仅把内部.wt-row改为下方布局，使文字包围框位于y82%..92%，水平居中；主熊与文字仍左侧并排。不可修改宿主subtitle-placement，不可把位置写入关键帧。
2. 第二张图是游戏背景文字细节。保留白熊尺寸不抢字，字体改为精细雪绒感的圆润重字：克制冷灰薄边、暖雪白字面，避免粗灰描边/厚阴影。字体与镜片、雪痕统一，不加底条、发光或新装饰。
3. 保持段正文必须完整清晰，只有熊的微动和镜片细节运动。保持现有透明背景、离线资源、时钟和退场时序。长句换行及100ms短字幕不能隐字。
输出九个完整分节，每个===TITLE===单独一行，下一行直接写内容，不要name=前缀。不要解释，不查文件或工具。'''
    if len(sys.argv)>2 and sys.argv[2]=='--contrast':
        Image.open(source/'browser/light-hold.png').crop((300,588,730,670)).save(out/'position.png')
        Image.open(source/'browser/game-hold.png').crop((300,588,730,670)).save(out/'type-detail.png')
        review.update(scores=dict(readability=5,hierarchy=8,theme_relevance=8,typography=7,material=7,color_restraint=8,motion=8,originality=7,subject_clearance=9,sticker_restraint=8),
            defects=['浅色背景中文字边缘与背景接近，无法轻松读清；游戏高光处也会失去字缘'])
        (out/'before-scores.json').write_text(json.dumps(review,ensure_ascii=False,indent=2),encoding='utf8')
        instruction='第二轮截图修复，只修文字对比这一个失败项。'+json.dumps(review,ensure_ascii=False)+'''。
第一张是真实浏览器浅底保持截图，第二张是游戏背景。保持现在y82%..92%的布局、白熊、所有动画时序和内部DOM不变。
仅将文字最外缘改为冷深炭色#203943，在960x540画布下约1px的清晰细边（1080p约2px），字面保留暖雪白。使用paint-order:stroke fill避免笔画变粗。同步APPEARANCE与实际.wt-w，关键帧的text-shadow也不能在保持时重新覆盖成浅灰。
不要加黑条、粗阴影、发光、更多符号或彩虹色。需要浅奶油背景及游戏亮区都轻松读清，同时保持字面清楚。
不要改构图和位置；不要改白熊与镜片；不要改任何keyframe的transform或时长，只准改字缘颜色和描边宽度等文字颜色属性。输出完整九分节，每个===标题===单独一行。'''
    (out/'necessary-repair.txt').write_text(instruction,encoding='utf8')
    settings=json.loads((root/'2byteasr_settings.json').read_text('utf8'))
    from twobyteasr.llm_config import activate_ai_service,update_active_profile
    activate_ai_service(settings,'grok_account');update_active_profile(settings,model='grok-4.6')
    from twobyteasr.studio_ai import refine_web_theme_design
    start=time.monotonic();print('EVIDENCE',out,flush=True)
    result=refine_web_theme_design(json.loads((source/'theme.json').read_text('utf8')),instruction,
        cue_text='啊感觉他就是你看',runtime_settings=settings,deadline_seconds=600,
        reference_frames=(out/'position.png',out/'type-detail.png'),design_version=2,
        stage_callback=lambda value:print(value,flush=True))
    (out/'result.json').write_text(json.dumps(asdict(result),ensure_ascii=False,indent=2),encoding='utf8')
    print(result.source,result.message,'seconds',time.monotonic()-start,flush=True)
    if result.source!='refined':raise SystemExit(1)

if __name__=='__main__':main()
