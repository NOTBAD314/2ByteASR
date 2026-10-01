"""Explicit, traceable local text finishing. Source artwork stays editable."""
import copy
import hashlib
import json
import re
from html.parser import HTMLParser

from .i18n import bind_text

from .i18n import tr

MARKER = '/* 2byte-local-type-finish-v1 */'


class _TextSelector(HTMLParser):
    def __init__(self):
        super().__init__();self.selectors=[];self.stack=[];self.text_ancestors=set()

    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        selectors=['.'+name for name in attrs.get('class','').split()]
        if attrs.get('id'):selectors.append('#'+attrs['id'])
        if tag not in {'br','img','hr','input','meta','link'}:self.stack.append((tag,selectors))
        if attrs.get('data-semantic-text') == 'true':
            self.selectors.append('[data-semantic-text="true"]')
            self.text_ancestors.update(s for _,names in self.stack for s in names)

    def handle_endtag(self,tag):
        for i in range(len(self.stack)-1,-1,-1):
            if self.stack[i][0]==tag:
                del self.stack[i:];break


def polish_theme(theme, *, level=True, metal=True, settle=True):
    """No names or theme IDs select a template; only requested text properties change."""
    from .web_theme import WebThemeDocument
    original=WebThemeDocument.from_dict(dict(theme)).to_dict()
    result=copy.deepcopy(original)
    css=result.get('cueCss','').split(MARKER)[0].rstrip()
    parser=_TextSelector();parser.feed(result.get('cueHtml',''))
    if not parser.selectors:
        raise ValueError('该主题尚未标记正文层；请先在源码的正文容器标记 data-semantic-text="true"，保留原稿。')
    if level:
        # Layout translations and scales remain intact. Only static tilting
        # functions are removed; authored MotionSpec rotations remain authored.
        def flatten(match):
            selector,body=match.groups()
            if selector.strip() not in parser.text_ancestors and selector.strip() not in parser.selectors:
                return match.group(0)
            body=re.sub(r'(?i)(?:rotate(?:X|Y|Z)?|skew(?:X|Y)?)\([^)]*\)', '', body)
            body=re.sub(r'transform\s*:\s*(?=;|$)', 'transform:none', body)
            return selector+'{'+body+'}'
        css=re.sub(r'([^{}]+)\{([^{}]*)\}',flatten,css)
        css=re.sub(r'transform\s*:\s*;', 'transform:none;', css)
    if metal:
        css += '\n'+MARKER+'\n' + '''[data-semantic-text="true"]{
font-weight:900;letter-spacing:-0.018em;line-height:1.12;
color:#eef2f5;background:linear-gradient(180deg,#fff 0%,#f5f7f9 34%,#c4cdd6 49%,#fff 51%,#e3e9ee 76%,#a5b3c1 100%);
-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;
-webkit-text-stroke:0.007em #e8edf3;text-shadow:none;
filter:drop-shadow(0 0.035em 0 #566574) drop-shadow(0 0.025em 0 #080b10);
}'''
    result['cueCss']=css
    if settle:
        tracks=result.get('motionSpec',{}).get('tracks',[])
        for track in list(tracks):
            if track.get('phase')=='build' and str(track.get('ease','')).startswith(('back','elastic','bounce')):
                track['ease']='power3.out'
            if (track.get('phase')=='build' and track.get('selector') in parser.text_ancestors
                    and 'x' in track.get('from',{}) and track.get('start')==0
                    and not any(t.get('selector')==track['selector'] and t.get('phase')=='build'
                                and 'opacity' in t.get('from',{}) for t in tracks)):
                tracks.append(dict(selector=track['selector'],phase='build',start=0,end=.18,
                    ease='power2.out',**{'from':{'opacity':0},'to':{'opacity':1}}))
    result=WebThemeDocument.from_dict(result).to_dict()
    digest=lambda value:hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    receipt=dict(kind='explicit-local-text-finish',version=1,provider_calls=0,
        before_sha256=digest(original),after_sha256=digest(result),
        options=dict(level=level,metal=metal,settle=settle),
        retained=['cueHtml','stageHtml','stageCss','palette','appearance'],
        changes=['正文水平校正' if level else '', '银白金属字面/窄亮边/下缘厚度/字距' if metal else '',
                 '入场回弹改为连续减速' if settle else ''])
    return result,receipt


def open_polish_dialog(page):
    from PySide6.QtWidgets import QDialog,QVBoxLayout,QLabel,QCheckBox,QDialogButtonBox
    from .studio_design_target import design_cue
    from .studio_theme import apply_secondary_surface_theme
    cue=design_cue(page.project,page.selected_cue_id)
    theme=page.project.style_recipes.get(cue.style_id,{}).get('webTheme') if cue else None
    if not theme:return
    dialog=QDialog(page);bind_text(dialog, '本地精修文字', property='windowTitle');layout=QVBoxLayout(dialog)
    notice=QLabel('保留当前结构与正文，生成可撤销的本地修订。\n校验通过后自动应用；原稿与修改记录一起保存。')
    notice.setWordWrap(True);layout.addWidget(notice)
    boxes=[]
    for text in ('正文保持水平（去除静态倾斜）','银白金属字面（亮边、厚度与字距）','平稳入场（收敛回弹）'):
        box=QCheckBox(text);box.setChecked(True);layout.addWidget(box);boxes.append(box)
    buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
    bind_text(buttons.button(QDialogButtonBox.Ok), '校验并应用精修')
    buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
    apply_secondary_surface_theme(dialog)
    if not dialog.exec():return
    try:
        revised,receipt=polish_theme(theme,level=boxes[0].isChecked(),metal=boxes[1].isChecked(),settle=boxes[2].isChecked())
        drafts=page._theme_drafts()
        drafts.adopt(revised,cue.id,label='本地文字精修')
        drafts.preserve_manual_overrides=True
        folder=drafts.root/'local-revision';folder.mkdir(parents=True,exist_ok=True)
        for name,value in [('original',theme),('revised',revised),('receipt',receipt)]:
            (folder/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2),'utf8')
    except Exception as exc:
        page._show_studio_hint(tr('本地精修未应用，原稿保留：{value0}', value0=str(exc)))
