"""Non-executable matching of the class-only authored selector vocabulary."""
from html.parser import HTMLParser
import re


class ThemeDOM(HTMLParser):
    def __init__(self, markup, *, conditional_text=False):
        super().__init__();self.rows=[];self.stack=[];self.conditional_text=conditional_text;self.feed(markup)

    def handle_data(self,data):
        # Material declarations may bind the host's conditional text spans.
        # Motion selectors deliberately use the default static DOM: a phrase
        # can be absent in the next cue and cannot be a required motion target.
        if not self.conditional_text or not self.stack or not re.search(r'\{\{\s*text\s*\}\}',data):return
        parent=self.stack[-1];raw=self.rows[parent]['attrs'].get('data-emphasis','')
        if not any(0<len(p.strip())<=24 for p in raw.split('|')):return
        caption=len(self.rows)
        self.rows.append(dict(tag='span',attrs={'data-caption-text':'true'},classes=set(),parent=parent))
        self.rows.append(dict(tag='span',attrs={'class':'wt-focus'},classes={'wt-focus'},parent=caption))

    def handle_starttag(self, tag, attrs):
        index=len(self.rows);attrs=dict(attrs)
        self.rows.append(dict(tag=tag,attrs=attrs,classes=set(attrs.get('class','').split()),
            parent=self.stack[-1] if self.stack else None))
        if tag not in ('br','hr','img','input','meta','link'):self.stack.append(index)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag,attrs)
        if self.stack and self.stack[-1]==len(self.rows)-1:self.stack.pop()

    def handle_endtag(self, tag):
        if self.stack:self.stack.pop()

    def targets(self, selector, *, allow_tags=False):
        selector=str(selector).strip()
        pseudo=re.search(r':(first-child|last-child|nth-child\(([1-9]\d?)\)|nth-last-child\(([1-9]\d?)\))$',selector)
        if pseudo:selector=selector[:pseudo.start()]
        part=(r'(?:[A-Za-z][\w-]*(?:\.[A-Za-z][\w-]*)*|(?:\.[A-Za-z][\w-]*)+)'
              if allow_tags else r'(?:\.[A-Za-z][\w-]*)+')
        if not re.fullmatch(part+r'(?:(?:\s*>\s*|\s+)'+part+r')*',selector):return None
        tokens=re.findall(part+r'|>',selector)
        def match(node,end):
            if node is None or not set(re.findall(r'\.([A-Za-z][\w-]*)',tokens[end]))<=self.rows[node]['classes']:return False
            tag=re.match(r'^[A-Za-z][\w-]*',tokens[end]) if allow_tags else None
            if tag and tag.group().lower()!=self.rows[node]['tag']:return False
            if end==0:return True
            parent=self.rows[node]['parent']
            if tokens[end-1]=='>':return match(parent,end-2)
            while parent is not None:
                if match(parent,end-1):return True
                parent=self.rows[parent]['parent']
            return False
        targets={i for i in range(len(self.rows)) if match(i,len(tokens)-1)}
        if pseudo:
            def selected(i):
                siblings=[j for j,r in enumerate(self.rows) if r['parent']==self.rows[i]['parent']]
                position=siblings.index(i)+1;value=pseudo.group(1)
                if value=='first-child':return position==1
                if value=='last-child':return position==len(siblings)
                if pseudo.group(2):return position==int(pseudo.group(2))
                return len(siblings)-position+1==int(pseudo.group(3))
            targets={i for i in targets if selected(i)}
        return targets


def selector_targets(markup, selector):
    return ThemeDOM(markup).targets(selector)
