"""Bounded-memory JSON projection for the library; never constructs a project.

The file is mapped read-only. Unneeded subtrees are scanned lexically rather
than deserialized. No recognition evidence, captions or recovery graph is
retained. All callers doing IO belong on a reader thread.
"""
from __future__ import annotations
import json,mmap,re,time
from pathlib import Path

_TOKEN=re.compile(rb'"[^"\\]*(?:\\.[^"\\]*)*"|[{}\[\]]')
_STRING=re.compile(rb'"[^"\\]*(?:\\.[^"\\]*)*"')
_SPACE=re.compile(rb'\s*')
_SCALAR=re.compile(rb'[^,}\]\s]+')
COUNT=object()
PROJECTION={'schema_version':True,'project_id':True,'created_at':True,'updated_at':True,
    'media':True,'cues':COUNT,
    'studio_state':{'project_name':True,'project_name_automatic':True,'project_name_origin':True},
    'generation_metadata':{'timeline_recognition':{'source_project_id':True,'source_project_path':True}}}

class JsonProjection:
    def __init__(self,data):self.data=data;self.deadline=time.perf_counter()+.006
    def yield_reader(self):
        if time.perf_counter()>=self.deadline:
            time.sleep(.001);self.deadline=time.perf_counter()+.006
    def space(self,pos):return _SPACE.match(self.data,pos).end()
    def end(self,pos):
        pos=self.space(pos);first=self.data[pos:pos+1]
        if first==b'"':
            match=_STRING.match(self.data,pos)
            if match is None:raise ValueError('Unterminated JSON string')
            return match.end()
        if first not in (b'{',b'['):
            match=_SCALAR.match(self.data,pos)
            if match is None:raise ValueError('Invalid JSON value')
            return match.end()
        depth=0
        for index,match in enumerate(_TOKEN.finditer(self.data,pos)):
            token=match.group(0)
            if token[:1]==b'"':continue
            depth+=1 if token in (b'{',b'[') else -1
            if not depth:return match.end()
            if index%512==0:self.yield_reader()
        raise ValueError('Unterminated JSON container')
    def project(self,pos,schema):
        pos=self.space(pos)
        if schema is True:
            end=self.end(pos);return json.loads(self.data[pos:end]),end
        if schema is COUNT:
            if self.data[pos:pos+1]!=b'[':raise ValueError('Expected captions array')
            count=0;pos=self.space(pos+1)
            while self.data[pos:pos+1]!=b']':
                pos=self.space(self.end(pos));count+=1
                if self.data[pos:pos+1]==b',':pos=self.space(pos+1)
                elif self.data[pos:pos+1]!=b']':raise ValueError('Invalid captions array')
                self.yield_reader()
            return count,pos+1
        if self.data[pos:pos+1]!=b'{':
            return {},self.end(pos)
        result={};pos=self.space(pos+1)
        while self.data[pos:pos+1]!=b'}':
            match=_STRING.match(self.data,pos)
            if match is None:raise ValueError('Expected JSON field')
            key=json.loads(match.group(0));pos=self.space(match.end())
            if self.data[pos:pos+1]!=b':':raise ValueError('Expected JSON colon')
            pos=self.space(pos+1)
            if key in schema:result[key],pos=self.project(pos,schema[key])
            else:pos=self.end(pos)
            pos=self.space(pos)
            if self.data[pos:pos+1]==b',':pos=self.space(pos+1)
            elif self.data[pos:pos+1]!=b'}':raise ValueError('Invalid JSON object')
            self.yield_reader()
        return result,pos+1

def naming_payload(path):
    with Path(path).open('rb') as stream:
        with mmap.mmap(stream.fileno(),0,access=mmap.ACCESS_READ) as data:
            payload,_=JsonProjection(data).project(3 if data[:3]==b'\xef\xbb\xbf' else 0,PROJECTION)
    return payload

def summary_from_payload(path,payload,recent=None):
    path=Path(path);recent=recent or {};state=payload.get('studio_state') or {};media=payload.get('media') or {}
    origin=dict(state.get('project_name_origin') or {})
    timeline=(payload.get('generation_metadata') or {}).get('timeline_recognition') or {}
    legacy=(timeline.get('source_project_id') and timeline.get('source_project_path')
        and state.get('project_name')==f"{Path(timeline['source_project_path']).stem} · 识别结果")
    if legacy:origin={'kind':'recognition_result','parent':Path(timeline['source_project_path']).stem}
    if not origin and not state.get('project_name'):
        match=re.fullmatch(r'未命名工程(?: ([2-9]|[1-9]\d+))?',path.stem)
        if match and path.parent.name==path.stem and Path(str(media.get('path') or '')).stem!=path.stem:
            origin={'kind':'unnamed','number':int(match[1]) if match[1] else None}
        elif path.stem=='识别结果' and timeline.get('source_project_id'):origin={'kind':'recognition_result'}
    name=state.get('project_name') or path.stem
    if not state.get('project_name') and path.stem=='project' and re.fullmatch(r'(?:p|media)-[0-9a-f]{32}',path.parent.name):
        name=Path(str(media.get('display_name') or media.get('path') or name)).stem
    cover=path.parent/'preview/project-cover.jpg'
    try:st=cover.stat();cover_mtime_ns,cover_size=st.st_mtime_ns,st.st_size
    except OSError:cover_mtime_ns,cover_size=0,0
    cues=payload.get('cues',0)
    return dict(project_id=payload.get('project_id',''),name=str(name),name_origin=origin,
        name_custom=bool(state.get('project_name') and not state.get('project_name_automatic') and not legacy),
        cue_count=len(cues) if isinstance(cues,list) else int(cues),duration_ms=int(media.get('duration_ms') or 0),
        source_media=str(media.get('path') or ''),created_at=payload.get('created_at',''),updated_at=payload.get('updated_at',''),
        width=int(media.get('width') or 0),height=int(media.get('height') or 0),
        cover_mtime_ns=cover_mtime_ns,cover_size=cover_size,cover_path=str(cover) if cover.is_file() else str(recent.get('cover_path') or ''),summary_version=1)

def read_project_summary(path,recent=None):
    return summary_from_payload(path,naming_payload(path),recent)
