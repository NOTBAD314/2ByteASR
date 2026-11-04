"""Semantic serialization identity and aggregate authored HTML diagnostics."""
import re
from html.parser import HTMLParser
from .web_theme import _ALLOWED_TAG_NAMES, _ALLOWED_ATTRS, _FORBIDDEN_ATTR_VALUE_TOKENS, _VOID_TAGS, inline_svg_attribute_problem


def html_signature(markup):
    class Signature(HTMLParser):
        def __init__(self):super().__init__(convert_charrefs=True);self.events=[]
        def handle_starttag(self,tag,attrs):
            self.events.append(('start',tag,tuple(sorted((k.casefold(),(v or '').strip()) for k,v in attrs))))
            if tag in _VOID_TAGS:self.events.append(('end',tag))
        def handle_startendtag(self,tag,attrs):
            self.handle_starttag(tag,attrs)
            if tag not in _VOID_TAGS:self.events.append(('end',tag))
        def handle_endtag(self,tag):
            if tag not in _VOID_TAGS:self.events.append(('end',tag))
        def handle_data(self,data):
            if data.strip():self.events.append(('text',re.sub(r'\s+',' ',data)))
        def handle_comment(self,data):self.events.append(('comment',data))
    p=Signature();p.feed(markup);p.close();return p.events


def html_problems(markup):
    allowed_attrs={x.casefold() for x in _ALLOWED_ATTRS}
    class Audit(HTMLParser):
        def __init__(self):super().__init__();self.issues=[];self.stack=[];self.index=0
        def handle_starttag(self,tag,attrs):self.start(tag,attrs,False)
        def handle_startendtag(self,tag,attrs):self.start(tag,attrs,True)
        def start(self,tag,attrs,closed):
            self.index+=1;where=f'node[{self.index}] <{tag}>'
            if tag not in _ALLOWED_TAG_NAMES:self.issues.append(where+' 标签不在白名单')
            for name,value in attrs:
                problem=inline_svg_attribute_problem(tag,name,value)
                if problem:self.issues.append(where+'.'+name+' '+problem)
                if name.casefold() not in allowed_attrs:self.issues.append(where+'.'+name+' 属性不在白名单')
                if name.casefold()=='data-block':
                    from .theme_texture_resource import valid_data_block
                    if not valid_data_block(value):self.issues.append(where+'.data-block 必须为1–48字符的声明性标识')
                if any(t in (value or '').casefold() for t in _FORBIDDEN_ATTR_VALUE_TOKENS):self.issues.append(where+'.'+name+' 属性值含禁止结构')
            if not closed and tag not in _VOID_TAGS:self.stack.append(tag)
        def handle_endtag(self,tag):
            if tag in _VOID_TAGS:return
            if not self.stack or self.stack[-1]!=tag:self.issues.append(f'</{tag}> 与当前父节点不匹配')
            elif self.stack:self.stack.pop()
        def handle_comment(self,data):self.issues.append('HTML comment 会被安全重建移除')
    p=Audit();p.feed(markup);p.close()
    if p.stack:p.issues.append('未闭合节点：'+', '.join(p.stack))
    return p.issues
