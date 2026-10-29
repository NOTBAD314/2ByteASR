"""Explicit-root development artifact maintenance; default is a read-only plan.

No git clean and no directory-name deletion. Execute requires approved manifest
entries, unchanged fingerprints, current process protection and leaf validation.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import zipfile
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from twobyteasr.storage.storage_service import safe_path

ASSETS={'.2byteproj','.2byteasr','.flv','.wav','.mp3','.m4a'}
SOURCE={'.py','.pyi','.ps1','.sh','.bat','.cmd','.cs','.cpp','.c','.h','.js','.mjs','.cjs','.jsx','.ts','.tsx','.rs','.go','.java','.md','.toml','.lock','.yml','.yaml','.ini','.env'}
PERSISTENT={'.2byteproj','.2byteasr','.srt','.ass','.vtt'}
UNKNOWN_ASSETS=ASSETS|{'.mp4','.mov','.mkv','.avi','.png','.jpg','.jpeg','.webp','.html','.json','.jsonl','.txt','.pth','.pt','.safetensors','.bin'}
ARCHIVES={'.zip','.7z','.tar','.gz','.xz','.rar'}


def overlaps(path, protected):
    """An asset and either of its containing/contained paths overlap."""
    return any(path==item or path.is_relative_to(item) or item.is_relative_to(path) for item in protected)


def configured_path(root,value):
    path=Path(os.path.abspath(root/str(value)))
    if not path.is_relative_to(root):raise ValueError('Configured object escapes explicit project root')
    return path


def asset_reason(path,derived):
    suffix=path.suffix.lower()
    if any(part in {'.git','.agents','.codex'} for part in path.parts):return '源码／未提交修改或项目配置'
    if path.name in {'.env','.gitignore','.gitattributes'}:return '源码或项目配置'
    if suffix in SOURCE or suffix in PERSISTENT:return '源码或持久用户契约'
    if path.name.casefold() in {'learned_game_terms.json','runtime_settings.json','settings.json','config.json'}:
        return '个人词库或配置'
    if suffix in UNKNOWN_ASSETS and path not in derived:return '归属未确认的媒体／工程证据／素材'
    return ''


def process_paths(root):
    import psutil
    protected={root/'dist'/'2ByteASR'}
    for process in psutil.process_iter(['pid','name']):
        try:
            name=(process.info.get('name') or '').casefold()
            if not (name.startswith(('python','2byteasr','ffmpeg','node','uv'))):continue
            for value in [process.exe(),*process.cmdline()]:
                if not value:continue
                path=Path(value)
                if path.is_absolute() and path.is_relative_to(root):
                    # Protect the whole candidate with its dependent DLLs, not just exe.
                    relative=path.relative_to(root)
                    if len(relative.parts)>1 and relative.parts[0] in {'tmp','dist','releases','build'}:
                        bundle=next((p for p in [path.parent,*path.parents]
                                     if p.is_relative_to(root) and (p/'2ByteASR.exe').is_file()
                                     and (p/'2byteasr_build.json').is_file()),None)
                        protected.add(bundle or path)
        except (psutil.Error,OSError,ValueError):continue
    return protected


def historical_references(root):
    protected=set()
    # Current navigation plus delivery READMEs; never traverse copied release
    # environments or historical source trees just to discover their docs.
    documents=list((root/'docs'/'exec-plans'/'active').glob('*.md'))
    documents.extend((root/'docs'/'architecture').glob('*.md'))
    documents.extend(root/'docs'/name for name in ('PROJECT_STATE.md','KNOWN_ISSUES.md','VERIFICATION.md'))
    documents.extend(root.glob('README*.md'))
    releases=root/'releases'
    if releases.is_dir():
        for folder in releases.iterdir():
            if folder.is_dir() and safe_path(folder,(releases,)):
                documents.extend(folder.glob('README*.md'))
    for path in documents:
            if not safe_path(path,(root,)):continue
            try:text=path.read_text('utf8')
            except (OSError,UnicodeError):continue
            for match in re.finditer(r'(?:\.\./)*(tmp|releases|dist|build)[/\\]([^\s)\]"<>]+)',text):
                rel=Path(match.group(1))/Path(match.group(2).replace('\\','/'))
                try:candidate=configured_path(root,rel)
                except ValueError:continue
                management={root/folder for folder in ('tmp','build','dist','releases')}
                if candidate in management:continue
                # Document links are weak historical evidence, even when they
                # point at a complete executable. Annotate; do not pin payload.
                bundled=(candidate.suffix.casefold()=='.exe' and candidate.parent not in management
                         and (candidate.parent/'_internal').is_dir())
                protected.add(candidate.parent if bundled else candidate)
    return protected


def referenced_paths(root):
    """Strong application references; Markdown delivery links are only history.

    User project contracts are never inferred from incidental report links. The
    project directories stay outside the selectable generated-artifact scopes.
    Archive dependency maps are explicit runtime restore contracts, however.
    """
    protected=set()
    archives=root/'releases'/'local-archives'
    for folder in archives.iterdir() if archives.is_dir() else ():
        contract=folder/'external-release-dependencies.json'
        if not contract.is_file():continue
        try:text=contract.read_text('utf8')
        except (OSError,UnicodeError):continue
        for match in re.finditer(r'(?:releases|tmp)[/\\][^"\s]+',text):
            try:protected.add(configured_path(root,match.group(0).replace('\\\\','/')))
            except ValueError:continue
    return protected


def generated_bundle_proof(path,root):
    """Recognize an explicitly selected frozen app, never a generic source tree.

    A valid build identity, PE entrypoint and shipped Qt/Python runtime establish
    the producer contract. Real project/config/model directories remain guards.
    The caller must still obtain approval for this exact metadata fingerprint.
    """
    marker=path/'2byteasr_build.json';exe=path/'2ByteASR.exe'
    if not path.is_dir() or not safe_path(path,(root/'tmp',root/'build',root/'dist',root/'releases')):
        return None
    try:
        build=json.loads(marker.read_text('utf8'))
        if not re.fullmatch('[0-9a-f]{64}',str(build.get('source_sha256',''))):return None
        if not build.get('build_channel') or int(build.get('source_file_count',0))<1:return None
        with exe.open('rb') as stream:
            if stream.read(2)!=b'MZ':return None
        payload=path/'_internal' if (path/'_internal').is_dir() else path
        if not any(payload.glob('python3*.dll')) or not (payload/'PySide6'/'Qt6Core.dll').is_file():return None
        for child in path.iterdir():
            if child.name.casefold() in {'models','projects','reports','runtime','.git','.codex','.agents','2byteasr projects'}:
                return None
        h=hashlib.sha256()
        with exe.open('rb') as stream:
            for chunk in iter(lambda:stream.read(1024**2),b''):h.update(chunk)
        return dict(kind='frozen_application_payload',build=build,exe_sha256=h.hexdigest())
    except (OSError,ValueError,TypeError,UnicodeError):return None


def snapshot(path,root,derived=(),*,generated_bundle=False):
    files=[];issues=[];assets=[]
    derived=set(derived)
    def visit(directory):
        try:entries=list(os.scandir(directory))
        except OSError as exc:issues.append(str(exc));return
        for entry in entries:
            leaf=Path(entry.path)
            try:
                info=entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:
                    issues.append(str(leaf)+': link/outside');continue
                # Every ancestor was checked on descent; avoid O(depth) lstat
                # calls per leaf in million-file copied environments.
                if entry.is_dir(follow_symlinks=False):visit(leaf)
                else:
                    record=dict(path=str(leaf.relative_to(root)),size=info.st_size,mtime_ns=info.st_mtime_ns,
                                device=info.st_dev,inode=info.st_ino)
                    files.append(record)
                    reason=asset_reason(leaf,derived)
                    # Frozen, explicitly selected runtime source copies are
                    # generated payload. Persistent user contracts are not.
                    relative=leaf.relative_to(path).as_posix()
                    user_media=(leaf.suffix.lower() in ASSETS|{'.mp4','.mov','.mkv','.avi','.webm'}
                                and relative!='assets/diagnostics/speech_en.wav')
                    forbidden=(user_media or leaf.suffix.lower() in PERSISTENT or any(p in {'.git','.codex','.agents'} for p in leaf.relative_to(path).parts)
                               or leaf.name.casefold() in {'learned_game_terms.json','2byteasr_settings.json','secrets.dat'})
                    if reason and (not generated_bundle or forbidden):assets.append(record['path'])
            except OSError as exc:issues.append(str(exc))
    if not safe_path(path,(root,)):issues.append(str(path)+': link/outside')
    elif path.is_dir():visit(path)
    else:
        try:
            st=path.lstat();files.append(dict(path=str(path.relative_to(root)),size=st.st_size,mtime_ns=st.st_mtime_ns,
                                             device=st.st_dev,inode=st.st_ino))
            if asset_reason(path,derived):assets.append(str(path.relative_to(root)))
        except OSError as exc:issues.append(str(exc))
    digest=hashlib.sha256(json.dumps(sorted(files,key=lambda f:f['path']),sort_keys=True).encode()).hexdigest()
    return files,issues,assets,digest


def make_plan(root,pins,scopes=(),*,scope_children=False,derived_files=(),generated_bundles=()):
    runtime=process_paths(root);refs=referenced_paths(root);weak=historical_references(root);entries=[]
    roots=tuple(root/folder for folder in ('tmp','build','dist','releases'))
    derived={configured_path(root,value) for value in derived_files}
    bundles={configured_path(root,value) for value in generated_bundles}
    if any(not safe_path(path,roots) for path in derived):raise ValueError('Derived file is outside management roots or linked')
    selected=[]
    if scopes:
        for value in scopes:
            path=configured_path(root,value)
            if scope_children:
                if not safe_path(path,(root,)) or not any(path==base or path.is_relative_to(base) for base in roots):
                    raise ValueError('Scope must remain in tmp/build/dist/releases')
                selected.extend(path.iterdir())
            else:
                if not safe_path(path,roots):raise ValueError('Scope must name a specific safe object below management roots')
                selected.append(path)
    else:
        for base in roots:
            if base.is_dir():selected.extend(base.iterdir())
    for path in sorted(set(selected)):
            proof=generated_bundle_proof(path,root) if path in bundles else None
            files,issues,assets,digest=snapshot(path,root,derived,generated_bundle=bool(proof))
            reasons=[]
            if overlaps(path,runtime):reasons.append('正在运行进程或实际日常入口完整目录')
            if overlaps(path,refs):reasons.append('归档恢复等实际依赖契约；先迁移对应对象')
            if path in bundles and not proof:reasons.append('完整冻结程序归属未通过核验')
            if overlaps(path,pins):reasons.append('用户固定保留')
            if assets and not proof:reasons.append('包含工程／原始媒体／音频，不能自动判定临时')
            if issues:reasons.append('链接或扫描不完整')
            entries.append(dict(path=str(path.relative_to(root)),category='F/G',files=len(files),
                logical_bytes=sum(f['size'] for f in files),fingerprint=digest,protected=bool(reasons),reasons=reasons,
                approved=False,action='keep',recommendation=('可见迁移到 releases/<交付主题>/assets 或证据归档后验证引用／打开' if overlaps(path,refs) else '核对当前有效交付及一个回退；可用 --scope / --scope-children 下钻，明确派生文件用 --derived-file 单独登记'),
                fingerprint_type='metadata:path,size,mtime_ns,device,inode',
                generated_proof=proof, historical_reference=overlaps(path,weak),
                retained_asset_paths=assets if proof else [],
                executable_bytes=sum(f['size'] for f in files if f['path'] not in assets) if proof else (0 if reasons else sum(f['size'] for f in files)),
                assets=assets[:20],issues=issues[:20]))
    return dict(schema=1,project_root=str(root),time=datetime.now(timezone.utc).isoformat(),
                mode='只读清理计划；未批准对象不会删除',pins=[str(p.relative_to(root)) for p in pins],
                derived_files=[str(p.relative_to(root)) for p in sorted(derived)],entries=entries)


def execute(plan,root):
    if Path(plan['project_root']).resolve()!=root:raise ValueError('Plan root differs from explicit project root')
    results=[];free=shutil.disk_usage(root).free
    pins={configured_path(root,value) for value in plan.get('pins',())}
    derived={configured_path(root,value) for value in plan.get('derived_files',())}
    roots=tuple(root/folder for folder in ('tmp','build','dist','releases'))
    def current_protection(path):
        return overlaps(path,process_paths(root)) or overlaps(path,referenced_paths(root)) or overlaps(path,pins)
    for item in plan['entries']:
        if item.get('approved') is not True or item.get('action') not in {'delete','archive'}:continue
        path=configured_path(root,item['path']);reason=''
        if item.get('protected') or current_protection(path):reason='受保护／当前运行或当前引用完整目录'
        if not safe_path(path,roots):reason='越界／链接／管理根本身'
        if reason:results.append(dict(path=item['path'],status='skipped',reason=reason));continue
        proof=generated_bundle_proof(path,root) if item.get('generated_proof') else None
        if item.get('generated_proof') and proof!=item['generated_proof']:
            results.append(dict(path=item['path'],status='skipped',reason='冻结产物身份改变，需要重新确认'));continue
        files,issues,assets,digest=snapshot(path,root,derived,generated_bundle=bool(proof))
        retained=set(item.get('retained_asset_paths',())) if proof else set()
        if issues or (assets and not proof) or (proof and set(assets)!=retained) or digest!=item['fingerprint']:
            results.append(dict(path=item['path'],status='skipped',reason='内容变化／用户资产／链接，需重新生成计划'));continue
        if item['action']=='archive':
            if any(Path(f['path']).suffix.lower() in ARCHIVES for f in files):
                results.append(dict(path=item['path'],status='skipped',reason='不重复归档已有压缩包'));continue
            archive=configured_path(root,item.get('archive_path',''))
            if not item.get('archive_path') or not safe_path(archive,(root/'releases',)) or archive.exists() or archive.is_relative_to(path):
                results.append(dict(path=item['path'],status='skipped',reason='需明确全新releases归档路径'));continue
            archive.parent.mkdir(parents=True,exist_ok=True)
            with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
                for f in files:z.write(root/f['path'],arcname=Path(f['path']).as_posix())
            with zipfile.ZipFile(archive) as z:
                if z.testzip() is not None:raise OSError('Archive CRC check failed; source preserved')
                for f in files:
                    h=hashlib.sha256()
                    with (root/f['path']).open('rb') as stream:
                        for chunk in iter(lambda:stream.read(1024**2),b''):h.update(chunk)
                    archived=hashlib.sha256()
                    with z.open(Path(f['path']).as_posix()) as stream:
                        for chunk in iter(lambda:stream.read(1024**2),b''):archived.update(chunk)
                    if archived.digest()!=h.digest():raise OSError('Archive byte verification failed; source preserved')
        # A task or a document reference can appear while scanning/archiving.
        if current_protection(path):
            results.append(dict(path=item['path'],status='skipped',reason='处理期间开始使用或新增引用；源文件保持',
                                archive_path=str(archive.relative_to(root)) if item['action']=='archive' else None));continue
        deleted=0;failed=[]
        active=process_paths(root);refs=referenced_paths(root);checked=time.monotonic()
        for f in files:
            leaf=root/f['path']
            if f['path'] in retained:continue
            try:
                if time.monotonic()-checked>.5:
                    active=process_paths(root);refs=referenced_paths(root);checked=time.monotonic()
                if overlaps(leaf,active|refs|pins):raise OSError('当前运行／引用／固定资产，等待释放后重新计划')
                info=leaf.lstat()
                if not safe_path(leaf,(path,)) and leaf!=path:raise OSError('Path changed')
                # Windows DirEntry.stat may report unavailable dev/ino as 0.
                if (info.st_size!=f['size'] or info.st_mtime_ns!=f['mtime_ns']
                    or f['device'] and info.st_dev!=f['device']
                    or f['inode'] and info.st_ino!=f['inode']):raise OSError('File changed')
                leaf.unlink();deleted+=info.st_size
            except OSError as exc:failed.append(dict(path=f['path'],reason=str(exc)))
        if path.is_dir() and safe_path(path,roots):
            # Only revisit known file parents; never descend into a junction
            # created after the scan just to remove empty directories.
            directories=set()
            for record in files:
                directory=(root/record['path']).parent
                while directory!=path and directory.is_relative_to(path):
                    directories.add(directory);directory=directory.parent
            for directory in sorted(directories,key=lambda p:len(p.parts),reverse=True):
                if safe_path(directory,(path,)):
                    try:directory.rmdir()
                    except OSError:pass
            try:path.rmdir()
            except OSError:pass
        results.append(dict(path=item['path'],status='failed' if failed else ('generated_payload_removed_assets_retained' if retained else ('failed' if path.exists() else 'removed')),logical_removed_bytes=deleted,failed=failed,
            retained_asset_paths=sorted(retained),
            remaining_path=path.exists(),archive_path=str(archive.relative_to(root)) if item['action']=='archive' else None))
    return dict(results=results,observed_volume_free_delta=shutil.disk_usage(root).free-free,
                note='逻辑删除大小不等于物理释放；同盘归档成本已包含在观察差值，不将移动视为释放')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--pin',action='append',default=[])
    parser.add_argument('--scope',action='append',default=[],help='Scan only this exact repository-relative object; repeat for multiple objects')
    parser.add_argument('--scope-children',action='store_true',help='Scan only the immediate children of explicitly supplied scopes')
    parser.add_argument('--derived-file',action='append',default=[],help='Explicitly declare this exact file as a generated artifact; does not override source/project/config/reference/active guards')
    parser.add_argument('--generated-bundle',action='append',default=[],help='Verify this exact frozen application payload; never permits deleting user contracts, active apps or pinned rollback')
    parser.add_argument('--execute-plan',type=Path)
    args=parser.parse_args();root=args.project_root.resolve()
    if not (root/'AGENTS.md').is_file():raise ValueError('Explicit project root must contain AGENTS.md')
    args.output=Path(os.path.abspath(args.output))
    if args.output.exists() or not safe_path(args.output,(root/'tmp',root/'releases')):
        raise ValueError('Use a new, safe tmp/release output; existing source or user files are never overwritten')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    if args.execute_plan:
        result=execute(json.loads(args.execute_plan.read_text('utf8')),root)
    else:
        if args.scope_children and not args.scope:raise ValueError('--scope-children requires explicit --scope')
        result=make_plan(root,[configured_path(root,p) for p in args.pin],args.scope,
                         scope_children=args.scope_children,derived_files=args.derived_file,generated_bundles=args.generated_bundle)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(dict(output=str(args.output),entries=len(result.get('entries',[])),mode='executed' if args.execute_plan else 'read-only'),ensure_ascii=False))


if __name__=='__main__':main()
