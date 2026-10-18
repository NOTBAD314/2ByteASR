"""Owned cache inventory and deletion. A directory name never grants ownership.

Logical bytes removed and observed volume free-space delta are separate metrics.
SQLite transactions serialize registration, leases and deletion across processes.
Unknown and remotely rebuilt data is always excluded from ordinary maintenance.
"""
from __future__ import annotations

from contextlib import contextmanager, closing
from dataclasses import dataclass, field, asdict, replace
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import threading
import time

from .runtime_paths import get_runtime_paths

GiB = 1024 ** 3
DEFAULT_POLICY = dict(enabled=True, budget_bytes=10 * GiB, retention_days=7,
                      log_days=14, log_budget_bytes=200 * 1024 ** 2, resume_days=14)
LABELS = dict(overlay='一次性播放覆盖层', media='可重建中间媒体', waveform='波形',
              thumbnail='缩略图', audio='可重建音频', preview='字幕预览', log='诊断日志',
              download='已完成下载', evidence='识别文字证据', unknown='归属不明')
LABELS['uv']='运行库下载缓存（uv）'
LOCAL_CATEGORIES = {'overlay', 'media', 'waveform', 'thumbnail', 'audio', 'preview', 'log', 'download'}
_TOUCHES = {}
_TOUCH_LOCK = threading.Lock()
_UNTRACKED_ACTIVE = {}


def _source_unavailable(category,source):
    return (category=='media' and not source) or (
        category in {'media','audio','waveform','thumbnail'} and bool(source) and not Path(source).is_file())


def _media_fallback(source):
    """Check the existing local reader/rebuild tools, without rendering a proxy."""
    from .audio_engine import studio_ffmpeg_path
    from .processes import run_hidden_subprocess
    ffmpeg = Path(studio_ffmpeg_path())
    probe = ffmpeg.with_name('ffprobe.exe' if os.name == 'nt' else 'ffprobe')
    if not ffmpeg.is_file() or not probe.is_file():
        return '本地媒体读取／重建工具不可用'
    try:
        result = run_hidden_subprocess([str(probe), '-v', 'error', '-show_entries',
            'stream=codec_type,codec_name:format=duration', '-of', 'json', str(source)],
            purpose='storage original media fallback check', capture_output=True,
            text=True, encoding='utf8', errors='replace', timeout=20)
        data = json.loads(result.stdout or '{}')
        if result.returncode or not any(s.get('codec_type') == 'video' and s.get('codec_name') for s in data.get('streams', [])):
            return '原素材无法通过本地媒体读取检查；保留中间副本'
        return ''
    except Exception as exc:
        return '原素材读取／重建链路核对失败：' + str(exc)[-300:]


def _pid_identity(pid=None):
    pid = pid or os.getpid()
    try:
        import psutil
        return f'{pid}:{psutil.Process(pid).create_time():.6f}'
    except Exception:
        return f'{pid}:unknown'


def _alive(identity):
    try:
        pid, created = identity.split(':', 1)
        import psutil
        # On Windows constructing Process for hundreds of historical dead PIDs
        # repeatedly queries kernel process metadata. A fresh PID snapshot proves
        # absence cheaply; a present PID still requires its exact birth time.
        if int(pid) not in psutil.pids():return False
        process = psutil.Process(int(pid))
        return created == 'unknown' or abs(process.create_time() - float(created)) < .01
    except ImportError:
        return True  # Cannot prove dead; do not reclaim a lease.
    except Exception as exc:
        try:
            import psutil
            if isinstance(exc,psutil.NoSuchProcess):return False
        except ImportError:pass
        return True  # AccessDenied/malformed identity is not proof of death.


def safe_path(path, roots):
    """Validate lexical AND physical containment, including every reparse ancestor."""
    target = Path(os.path.abspath(path))
    for root in roots:
        root = Path(os.path.abspath(root))
        try:
            target.relative_to(root)
        except ValueError:
            continue
        current = target
        while True:
            try:
                info = current.lstat()
                if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                    return False
            except FileNotFoundError:
                pass
            except OSError:
                return False
            if current == current.parent:
                break
            current = current.parent
        try:
            return target.resolve().is_relative_to(root.resolve()) and target != root
        except OSError:
            return False
    return False


@dataclass
class CacheItem:
    path: str
    category: str
    size: int
    last_used: float | None
    producer: str
    source: str = ''
    reason: str = ''
    rebuild: str = 'local'
    identity: tuple = ()
    warning: str = ''
    source_identity: tuple = ()
    @property
    def cleanable(self):
        return not self.reason and self.category in LOCAL_CATEGORIES and self.rebuild == 'local'
    @property
    def manual_cleanable(self):
        return self.cleanable or (bool(self.warning) and self.reason.startswith('原素材不可访问；辅助预览') and self.category in {'waveform','thumbnail','preview'}) or (self.producer.endswith('_legacy') and
            self.reason.startswith('已识别生成契约') and self.category in LOCAL_CATEGORIES and self.rebuild == 'local')


@dataclass
class ScanResult:
    items: list[CacheItem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    cancelled: bool = False
    roots: list[str] = field(default_factory=list)
    model_bytes: int | None = None
    runtime_usage: object | None = None  # runtime_usage.RuntimeUsage
    @property
    def complete(self):
        return not self.cancelled and not self.errors
    @property
    def total_bytes(self):
        return sum(i.size for i in self.items)
    @property
    def cleanable_bytes(self):
        return sum(i.size for i in self.items if i.cleanable)
    @property
    def manual_cleanable_bytes(self):
        return sum(i.size for i in self.items if i.manual_cleanable)


@dataclass
class CleanupResult:
    deleted: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)
    pending: list[dict] = field(default_factory=list)
    cancelled: bool = False
    logical_removed_bytes: int = 0
    observed_free_delta: dict[str, int] = field(default_factory=dict)
    note: str = '卷空闲空间变化含其他进程活动；逻辑删除量不等于物理释放量。'


class StorageService:
    def __init__(self, paths=None, *, roots=None, state_root=None, busy=None, manual_busy=None, media_validator=None, media_references=None):
        self.paths = paths or get_runtime_paths()
        self.roots = tuple(Path(p).absolute() for p in (roots or (
            self.paths.cache_root, self.paths.temp_root, self.paths.log_root,
            self.paths.user_data_root / 'SubtitleStudioPreview',
            self.paths.managed_runtime_root / 'download-cache',
        )))
        self.roots = tuple(r for n,r in enumerate(self.roots) if not any(
            r == other and k < n or r != other and r.is_relative_to(other)
            for k,other in enumerate(self.roots)))
        self.state_root = Path(state_root or self.paths.user_data_root / 'storage')
        self.db_path = self.state_root / 'cache.sqlite3'
        self.policy_path = self.state_root / 'policy.json'
        self.busy = busy or (lambda: False)
        self.manual_busy = manual_busy or (lambda:self.busy())
        self.media_validator = media_validator or _media_fallback
        # The UI supplies its current, possibly unsaved, media graph separately
        # from the bounded read-only saved-project inspection.
        self.media_references = media_references or (lambda:None)

    @contextmanager
    def _db(self):
        if not safe_path(self.db_path,(self.state_root,)):
            raise OSError('存储索引路径含链接或不可确认祖先')
        self.state_root.mkdir(parents=True, exist_ok=True)
        if not safe_path(self.db_path,(self.state_root,)):
            raise OSError('存储索引路径在创建目录后变化')
        db = sqlite3.connect(self.db_path, timeout=5)
        db.execute('PRAGMA busy_timeout=5000')
        db.execute('CREATE TABLE IF NOT EXISTS entries(path TEXT PRIMARY KEY, category TEXT, producer TEXT, source TEXT, rebuild TEXT, protected TEXT, used REAL)')
        db.execute('CREATE TABLE IF NOT EXISTS leases(path TEXT, owner TEXT, token TEXT PRIMARY KEY)')
        try:
            with db:
                yield db
        finally:
            db.close()

    def register(self, path, category, *, source='', producer='', rebuild='local', protected_reason=''):
        path = str(Path(path).absolute())
        if not safe_path(path, self.roots):
            return False
        if category not in LABELS or not producer:
            return False
        with self._db() as db:
            db.execute('INSERT INTO entries VALUES(?,?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET category=excluded.category, producer=excluded.producer, source=excluded.source, rebuild=excluded.rebuild, protected=excluded.protected, used=excluded.used',
                       (path, category, producer, str(source), rebuild, protected_reason, time.time()))
        return True

    def touch(self, path):
        if not self.db_path.exists():
            return
        with self._db() as db:
            db.execute('UPDATE entries SET used=? WHERE path=?', (time.time(), str(Path(path).absolute())))

    @contextmanager
    def lease(self, path):
        import uuid
        token = uuid.uuid4().hex
        path = str(Path(path).absolute())
        if not safe_path(path, self.roots):
            yield
            return
        with self._db() as db:
            db.execute('INSERT INTO leases VALUES(?,?,?)', (path, _pid_identity(), token))
            db.execute('UPDATE entries SET used=? WHERE path=?', (time.time(), path))
        try:
            yield
        finally:
            with self._db() as db:
                db.execute('DELETE FROM leases WHERE token=?', (token,))

    def policy(self):
        policy = dict(DEFAULT_POLICY)
        try:
            value = json.loads(self.policy_path.read_text('utf8'))
            for key in policy:
                if key in value:
                    policy[key] = bool(value[key]) if key == 'enabled' else max(1, int(value[key]))
        except (OSError, ValueError, TypeError):
            pass
        return policy

    def save_policy(self, policy):
        data = dict(DEFAULT_POLICY)
        for key in data:
            if key in policy:
                data[key] = bool(policy[key]) if key == 'enabled' else max(1, int(policy[key]))
        self.write_state_json('policy.json',data)

    def write_state_json(self,name,payload):
        import uuid
        if Path(name).name!=name or not name.endswith('.json'):raise ValueError('Invalid state leaf')
        target=self.state_root/name
        if not safe_path(target,(self.state_root,)):raise OSError('状态目录／文件含链接，拒绝写入')
        self.state_root.mkdir(parents=True,exist_ok=True)
        temporary=self.state_root/('.'+name+'-'+uuid.uuid4().hex+'.part')
        try:
            if not safe_path(temporary,(self.state_root,)):raise OSError('状态临时路径不安全')
            with temporary.open('x',encoding='utf8') as stream:
                json.dump(payload,stream,ensure_ascii=False,indent=2);stream.flush();os.fsync(stream.fileno())
            if not safe_path(target,(self.state_root,)):raise OSError('状态路径在写入期间变化')
            os.replace(temporary,target)
        finally:
            try:temporary.unlink(missing_ok=True)
            except OSError:pass

    def forget_missing(self,limit=256):
        if not self.db_path.exists():return 0
        count=0
        with self._db() as db:
            for path, in db.execute('SELECT path FROM entries').fetchall():
                if count>=limit:break
                if not safe_path(path,self.roots) or os.path.lexists(path):continue
                owners=db.execute('SELECT owner FROM leases WHERE path=?',(path,)).fetchall()
                if any(_alive(o[0]) for o in owners):continue
                db.execute('DELETE FROM entries WHERE path=?',(path,));db.execute('DELETE FROM leases WHERE path=?',(path,));count+=1
        return count

    def _registered(self, *, read_only=False):
        if not self.db_path.exists():
            return {}, {}
        if read_only:
            if not safe_path(self.db_path,(self.state_root,)):
                raise OSError('缓存索引目录包含链接，未读取')
            with closing(sqlite3.connect(self.db_path.absolute().as_uri()+'?mode=ro',uri=True)) as db:
                entries={row[0]:row[1:] for row in db.execute('SELECT * FROM entries')}
                live={path:owner for path,owner,_ in db.execute('SELECT * FROM leases') if _alive(owner)}
            return entries,live
        with self._db() as db:
            entries = {row[0]: row[1:] for row in db.execute('SELECT * FROM entries')}
            live = {}
            for path, owner, token in db.execute('SELECT * FROM leases').fetchall():
                if _alive(owner):
                    live[path] = owner
                else:
                    db.execute('DELETE FROM leases WHERE token=?', (token,))
        return entries, live

    def scan(self, cancel=None, *, include_models=True):
        cancel = cancel or threading.Event()
        result = ScanResult(roots=[str(r) for r in self.roots])
        try: registered, leases = self._registered(read_only=True)
        except (OSError,sqlite3.Error) as exc:
            result.errors.append('缓存索引读取失败：'+str(exc));registered,leases={},{}
            # Unknown lease state must not become an executable plan.
            index_failed=True
        else:index_failed=False
        seen=set()
        for root in self.roots:
            if not root.exists():
                continue
            if not safe_path(root/'.scan-sentinel',(root,)):
                result.errors.append(f'{root}: 根目录为链接或不可确认，未遍历')
                continue
            def visit(directory):
                if cancel.is_set():
                    result.cancelled = True
                    return
                try:
                    if not safe_path(Path(directory)/'.scan-sentinel',self.roots):
                        result.errors.append(f'{directory}: 目录为链接或越界；未遍历');return
                    parent_identity=Path(directory).lstat()
                    first_item=len(result.items)
                    children = list(os.scandir(directory))
                except OSError as exc:
                    result.errors.append(f'{directory}: {exc}')
                    return
                for child in children:
                    if cancel.is_set():
                        result.cancelled = True
                        return
                    path = Path(child.path).absolute()
                    if str(path).casefold() in seen:continue
                    seen.add(str(path).casefold())
                    try:
                        # Windows DirEntry.stat may cache st_ino/st_dev as zero;
                        # deletion recheck uses lstat, so use the same source here.
                        st = path.lstat()
                        # The parent was checked before enumeration. Inspect the
                        # leaf without repeating every ancestor for 80k files;
                        # recheck the directory identity below and the entire
                        # path again inside the deletion transaction.
                        if stat.S_ISLNK(st.st_mode) or getattr(st,'st_file_attributes',0)&0x400:
                            result.items.append(CacheItem(str(path), 'unknown', st.st_size if child.is_file(follow_symlinks=False) else 0, None, '', reason='链接／目录越界；未遍历'))
                        elif child.is_dir(follow_symlinks=False):
                            visit(path)
                        else:
                            row = registered.get(str(path))
                            category, producer, source, rebuild, protected, used = row or ('unknown', '', '', 'unknown', '无法确认生成归属', None)
                            if path.is_relative_to(self.paths.managed_runtime_root/'download-cache'):
                                category,producer,rebuild,protected='uv','uv','download','包管理器缓存；仅通过官方 uv 维护入口处理'
                            reason = protected
                            warning=''
                            if protected.startswith('仅手动确认：'):
                                warning=protected.removeprefix('仅手动确认：')
                                reason='原素材不可访问；辅助预览仅可手动确认清理'
                            if str(path) in leases:
                                reason = '正在生成或使用（活动进程租约）'
                            elif rebuild != 'local':
                                reason = reason or '需要重新下载／远程服务，普通清理排除'
                            elif _source_unavailable(category,source):
                                if category in {'waveform','thumbnail'}:
                                    warning='原素材未恢复前无法重新生成这些预览'
                                    reason='原素材不可访问；辅助预览仅可手动确认清理'
                                else:reason = '原素材不可访问；可能是唯一副本，请保存为工程资产或重新定位'
                            if index_failed:reason='消费者索引读取失败；无法确认占用'
                            elif st.st_nlink>1 and category!='uv':reason='共享硬链接；需单独核对依赖'
                            result.items.append(CacheItem(str(path), category, st.st_size, used, producer, source, reason, rebuild,
                                                          (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns),warning))
                    except OSError as exc:
                        result.errors.append(f'{path}: {exc}')
                try:
                    final=Path(directory).lstat()
                    if (final.st_dev,final.st_ino)!=(parent_identity.st_dev,parent_identity.st_ino) or not safe_path(Path(directory)/'.scan-sentinel',self.roots):
                        result.items[first_item:]=[replace(i,reason='扫描期间目录身份／链接发生变化；需重新扫描') for i in result.items[first_item:]]
                        result.errors.append(f'{directory}: 扫描期间目录身份变化')
                except OSError as exc:
                    result.items[first_item:]=[replace(i,reason='扫描期间目录不可访问；需重新扫描') for i in result.items[first_item:]]
                    result.errors.append(f'{directory}: {exc}')
            visit(root)
        if not result.cancelled and not index_failed:
            from .storage_legacy import candidates
            recognized=candidates(self.paths,result.items)
            result.items=[recognized.get(i.path,i) for i in result.items]
            self._protect_media(result,cancel)
        if include_models and not cancel.is_set():
            try:
                total = 0
                model_errors=[]
                for directory, dirs, files in os.walk(self.paths.model_root, followlinks=False, onerror=lambda e:model_errors.append(str(e))):
                    dirs[:] = [d for d in dirs if safe_path(Path(directory)/d, (self.paths.model_root,))]
                    if cancel.is_set():
                        result.cancelled = True
                        break
                    for name in files:
                        path = Path(directory)/name
                        if safe_path(path, (self.paths.model_root,)):
                            total += path.stat().st_size
                if model_errors:
                    result.errors.extend('模型统计不完整: '+e for e in model_errors)
                elif not cancel.is_set():
                    result.model_bytes = total
            except OSError as exc:
                result.errors.append(f'模型统计不完整: {exc}')
        if include_models and not cancel.is_set():
            # Shown, never cleaned here: hard links counted once (2026-10-16).
            from .runtime_usage import runtime_disk_usage
            usage = runtime_disk_usage(self.paths.managed_runtime_root, cancel.is_set)
            result.runtime_usage = usage if usage is not None and usage.complete else None
        result.items.sort(key=lambda i:(i.category,-i.size,i.path))
        return result

    def _media_reference_state(self,items,cancel,*,saved=None):
        from .storage_media_preservation import (canonical_media_path,
            saved_project_references,strong_media_references)
        watched={i.path for i in items if i.category=='media' and i.producer}
        families={}
        for path in watched.copy():
            folder=Path(path).parent
            # A referenced seek payload requires its maps and receipts too.
            if folder.parent.name=='v2' and folder.parent.parent==self.paths.cache_root/'media'/'seek':
                family={str(folder/leaf) for leaf in ('optimized.mp4','optimized.mkv','continuous.mkv','ready.json','origin.json','sync-map.json')}
                watched.update(family);families[path]=family
            else:families[path]={path}
        if saved is None:saved=saved_project_references(self.paths,watched,cancel=cancel)
        current=set();loaded_error=''
        try:
            loaded=self.media_references()
            if loaded is not None:
                payload,project_path=loaded[:2]
                current=set(strong_media_references(payload,project_path))
                if len(loaded)>2:
                    for path in loaded[2]:
                        if not isinstance(path,str) or not path:raise ValueError('当前媒体消费者路径未知')
                        current.add(canonical_media_path(path))
        except Exception as exc:loaded_error='当前工程素材图不可核实：'+str(exc)[:400]
        blocks={}
        for item in items:
            if item.category!='media' or not item.producer:continue
            if not saved.complete:
                blocks[item.path]='已保存工程依赖检查不完整；保留缓存：'+'；'.join(saved.errors[:3])
            elif loaded_error:blocks[item.path]=loaded_error
            else:
                projects=tuple(dict.fromkeys(project for peer in families[item.path] for project in saved.references.get(peer,())))
                if projects:blocks[item.path]='已保存工程直接使用缓存；请先重新定位并保存：'+'；'.join(projects[:4])
                elif any(canonical_media_path(peer) in current for peer in families[item.path]):
                    blocks[item.path]='当前打开工程直接使用缓存；请先重新定位并保存工程'
                elif _source_unavailable('media',item.source) and item.source and canonical_media_path(item.source) in current:
                    blocks[item.path]='当前打开工程仍依赖失联原素材；请先重新定位并保存工程'
        return blocks,saved

    @staticmethod
    def _media_source_reason(item):
        """Recheck the historical producer's original identity when present."""
        folder=Path(item.path).parent
        try:
            source=Path(item.source)
            if not safe_path(source,(source.parent,)):return '原素材路径含链接或不可核实；保留中间副本'
            info=source.lstat()
            if item.source_identity and (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)!=item.source_identity:
                return '扫描后原素材身份已变化；保留中间副本'
            for leaf in ('ready.json','origin.json'):
                receipt=folder/leaf
                if not os.path.lexists(receipt):continue
                if not safe_path(receipt,(folder,)):return '媒体来源凭据路径含链接；保留中间副本'
                before=receipt.lstat()
                if before.st_size>1024*1024:return '媒体来源凭据过大；保留中间副本'
                with receipt.open('rb') as reader:
                    opened=os.fstat(reader.fileno())
                    if (opened.st_dev,opened.st_ino,opened.st_size,opened.st_mtime_ns)!=(before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns):
                        return '媒体来源凭据在读取时变化；保留中间副本'
                    payload=json.loads(reader.read(1024*1024+1))
                after=receipt.lstat()
                if (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns)!=(before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns):
                    return '媒体来源凭据在读取后变化；保留中间副本'
                if (not isinstance(payload,dict) or payload.get('source')!=item.source
                        or payload.get('size')!=info.st_size or payload.get('mtime_ns')!=info.st_mtime_ns):
                    return '原素材与媒体来源凭据不一致；保留中间副本'
            return ''
        except (OSError,ValueError,TypeError) as exc:return '原素材／来源凭据不可核实；保留中间副本：'+str(exc)[:300]

    def _protect_media(self,result,cancel):
        media=[i for i in result.items if i.category=='media' and i.producer]
        if not media:return
        from .storage_media_preservation import verified_relinked_asset
        blocks,_=self._media_reference_state(media,cancel)
        updated={}
        for item in media:
            if item.path in blocks:updated[item.path]=replace(item,reason=blocks[item.path]);continue
            if _source_unavailable('media',item.source):
                # An asset copy is provenance only. The helper also requires a
                # complete saved graph with no remaining old-media dependency.
                if item.reason.startswith(('原素材不可访问','原素材丢失')) and Path(item.path).suffix.lower() in {'.mp4','.mkv','.mov','.avi','.webm'}:
                    proof=verified_relinked_asset(item,self.paths,cancel=cancel)
                    updated[item.path]=replace(item,reason='' if proof.verified else item.reason+'；'+proof.reason,
                        warning=proof.reason if proof.verified else item.warning)
                continue
            reason=self._media_source_reason(item)
            if item.warning.startswith('独立资产完整校验通过') and not reason:
                # Restoration of the original does not erase a previous
                # explicit relink receipt or turn its old copy into auto work.
                proof=verified_relinked_asset(item,self.paths,cancel=cancel)
                updated[item.path]=replace(item,reason='' if proof.verified else proof.reason,
                    warning=proof.reason if proof.verified else item.warning)
                continue
            try:
                info=Path(item.source).lstat();identity=(info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)
            except OSError:identity=()
            updated[item.path]=replace(item,reason=reason or item.reason,source_identity=identity)
        result.items=[updated.get(i.path,i) for i in result.items]

    def manual_items(self,scan,categories=None):
        return [i for i in scan.items if i.manual_cleanable and (categories is None or i.category in categories)]

    def automatic_reason(self,item,scan=None):
        if item.warning:return '自动保留：'+item.warning
        if not item.cleanable:return item.reason or '自动保留：尚未确认登记归属'
        if item.category=='overlay':return '一次性覆盖层：消费者已结束时可自动即时清理'
        if item.last_used is None:return '自动保留：没有实际使用时间；可手动清理'
        if scan is not None and item.path in {i.path for i in self.recommended(scan)}:return '符合自动期限／预算'
        days=self.policy()['log_days' if item.category=='log' else 'retention_days']
        return f'自动保留：未达{days}天且未超预算；可手动清理'

    def recommended(self, scan, *, now=None):
        now = time.time() if now is None else now
        policy = self.policy()
        eligible = [i for i in scan.items if i.cleanable and not i.warning and (i.last_used is not None or i.category=='overlay')]
        selected = {i.path: i for i in eligible if i.category=='overlay' or now-i.last_used > (policy['log_days'] if i.category=='log' else policy['retention_days'])*86400}
        for group, budget in (([i for i in eligible if i.category!='log'], policy['budget_bytes']),
                              ([i for i in eligible if i.category=='log'], policy['log_budget_bytes'])):
            total = sum(i.size for i in group if i.path not in selected)
            for item in sorted(group, key=lambda i:i.last_used or 0):
                if total <= budget:
                    break
                if item.path not in selected:
                    selected[item.path] = item
                    total -= item.size
        return list(selected.values())

    def clean(self, items, cancel=None, *, adopt_legacy=False, allow_missing_aux=False, automatic=False):
        cancel = cancel or threading.Event()
        items=list({i.path:i for i in items}.values())
        result = CleanupResult()
        before = {}
        checked_media={}
        media=[i for i in items if i.category=='media' and i.producer]
        if media:
            from .storage_media_preservation import project_reference_snapshot_current,verified_relinked_asset
            media_blocks,reference_snapshot=self._media_reference_state(media,cancel)
        else:media_blocks={};reference_snapshot=None
        adoption_skips={}
        if adopt_legacy:
            from .storage_legacy import adopt
            legacy=[i for i in items if i.producer.endswith('_legacy') and i.manual_cleanable]
            if legacy:
                adoption=adopt(self,legacy,cancel=cancel)
                adoption_skips={i['path']:i['reason'] for i in adoption['skipped'] if 'path' in i}
        for item in items:
            if cancel.is_set():
                result.cancelled = True
                break
            record = dict(path=item.path, size=item.size)
            if (self.busy if automatic else self.manual_busy)():
                result.skipped.append(dict(record, reason='应用正在识别／播放／导出／安装；稍后重试'))
                continue
            if item.path in adoption_skips:
                result.skipped.append(dict(record,reason=adoption_skips[item.path]));continue
            if item.path in media_blocks:
                result.skipped.append(dict(record,reason=media_blocks[item.path]));continue
            permissible=item.cleanable or adopt_legacy and item.manual_cleanable or allow_missing_aux and bool(item.warning) and item.manual_cleanable
            if not permissible or (item.warning and not allow_missing_aux) or not safe_path(item.path, self.roots):
                result.skipped.append(dict(record, reason=item.reason or '归属／路径不符合普通清理'))
                continue
            path = Path(item.path)
            volume = path.anchor
            try:
                before.setdefault(volume, shutil.disk_usage(path.parent).free)
                with self._db() as db:
                    db.execute('BEGIN IMMEDIATE')
                    row = db.execute('SELECT category,producer,source,rebuild,protected,used FROM entries WHERE path=?', (item.path,)).fetchone()
                    owners = db.execute('SELECT owner FROM leases WHERE path=?', (item.path,)).fetchall()
                    if not row or row[0]!=item.category or row[1]!=item.producer or row[2]!=item.source or row[3]!='local' or (row[4] and not (allow_missing_aux and row[4].startswith('仅手动确认：'))) or any(_alive(o[0]) for o in owners):
                        result.skipped.append(dict(record, reason='删除前归属／占用状态已变化'))
                        continue
                    if item.last_used is not None and (row[5] is None or row[5]>item.last_used+.001):
                        result.skipped.append(dict(record, reason='扫描后已再次使用，需重新扫描'))
                        continue
                    with _TOUCH_LOCK:
                        untracked=bool(_UNTRACKED_ACTIVE.get(item.path))
                    if untracked:
                        result.skipped.append(dict(record,reason='消费者索引不可写，活动文件保持保护'));continue
                    recovery=None
                    if row[0]=='media':
                        # Recheck saved files and the unsaved loaded graph at
                        # the deletion boundary, even if the original is alive.
                        current_blocks,_=self._media_reference_state(media,cancel,saved=reference_snapshot)
                        if item.path in current_blocks or not project_reference_snapshot_current(reference_snapshot):
                            result.skipped.append(dict(record,reason=current_blocks.get(item.path,'工程依赖在扫描后变化；保留缓存')));continue
                        if (_source_unavailable('media',row[2]) or item.warning.startswith('独立资产完整校验通过')) and allow_missing_aux and not automatic:
                            recovery=verified_relinked_asset(item,self.paths,cancel=cancel)
                            if not recovery.verified:
                                result.skipped.append(dict(record,reason=recovery.reason));continue
                    if _source_unavailable(row[0],row[2]) and not (allow_missing_aux and row[0] in {'waveform','thumbnail'} or recovery and recovery.verified):
                        result.skipped.append(dict(record, reason='原素材丢失，唯一中间副本保护'))
                        continue
                    if row[0]=='media':
                        source=recovery.asset_path if recovery else row[2]
                        if not recovery:
                            source_reason=self._media_source_reason(item)
                            if source_reason:result.skipped.append(dict(record,reason=source_reason));continue
                        source_info=Path(source).lstat()
                        key=(source,source_info.st_dev,source_info.st_ino,source_info.st_size,source_info.st_mtime_ns)
                        if key not in checked_media:checked_media[key]=self.media_validator(source)
                        if checked_media[key]:
                            result.skipped.append(dict(record,reason=checked_media[key]));continue
                        final_source=Path(source).lstat()
                        current_blocks,_=self._media_reference_state(media,cancel,saved=reference_snapshot)
                        if (current_blocks.get(item.path) or not project_reference_snapshot_current(reference_snapshot)
                                or (source,final_source.st_dev,final_source.st_ino,final_source.st_size,final_source.st_mtime_ns)!=key
                                or not safe_path(source,(Path(source).parent,))):
                            result.skipped.append(dict(record,reason=current_blocks.get(item.path,'原素材／资产或工程在媒体读取检查中变化；保留缓存')));continue
                    st = path.lstat()
                    if (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns) != item.identity or not safe_path(path, self.roots):
                        result.skipped.append(dict(record, reason='文件已变化，需重新扫描'))
                        continue
                    if st.st_nlink > 1:
                        result.skipped.append(dict(record, reason='共享硬链接：需单独核对依赖'))
                        continue
                    path.unlink()
                    if path.exists():
                        raise OSError('文件仍存在')
                    db.execute('DELETE FROM entries WHERE path=?', (item.path,))
                    db.execute('DELETE FROM leases WHERE path=?', (item.path,))
                    result.deleted.append(record)
                    result.logical_removed_bytes += st.st_size
            except FileNotFoundError:
                result.skipped.append(dict(record, reason='已不存在；没有计算释放空间'))
            except PermissionError as exc:
                result.pending.append(dict(record, reason=f'权限／文件占用，等待释放后重试: {exc}'))
            except (OSError, sqlite3.Error) as exc:
                result.failed.append(dict(record, reason=str(exc)))
        for volume, free in before.items():
            try:
                result.observed_free_delta[volume] = shutil.disk_usage(volume).free-free
            except OSError:
                pass
        # One bounded receipt, not an ever-growing log. Failed entries remain registered.
        payload = asdict(result)
        payload['time'] = time.time()
        payload['counts']={key:len(payload[key]) for key in ('deleted','skipped','failed','pending')}
        payload['details_truncated']=any(len(payload[key])>200 for key in ('deleted','skipped','failed','pending'))
        for key in ('deleted', 'skipped', 'failed', 'pending'):
            payload[key] = payload[key][:200]
        self.write_state_json('last-cleanup.json',payload)
        return result


def register_cache(path, category, **kwargs):
    key=(str(Path(path).absolute()),category,str(kwargs))
    with _TOUCH_LOCK:
        now=time.monotonic()
        if now-_TOUCHES.get(key,-1000)<60:return True
        if len(_TOUCHES)>4096:_TOUCHES.clear()
    try:
        registered=StorageService().register(path, category, **kwargs)
        if registered:
            with _TOUCH_LOCK:_TOUCHES[key]=now
        return registered
    except (OSError,sqlite3.Error):return False


def touch_cache(path):
    key=(str(Path(path).absolute()),'touch')
    with _TOUCH_LOCK:
        now=time.monotonic()
        if now-_TOUCHES.get(key,-1000)<60:return
        if len(_TOUCHES)>4096:_TOUCHES.clear()
        _TOUCHES[key]=now
    try:StorageService().touch(path)
    except (OSError,sqlite3.Error):pass


@contextmanager
def cache_lease(path):
    lease=StorageService().lease(path)
    try:lease.__enter__()
    except (OSError,sqlite3.Error):
        key=str(Path(path).absolute());handle=None
        with _TOUCH_LOCK:_UNTRACKED_ACTIVE[key]=_UNTRACKED_ACTIVE.get(key,0)+1
        try:
            # Windows' ordinary read handle denies DeleteFile while this
            # fallback consumer is alive. Keep the in-process guard as well.
            if Path(path).is_file():handle=Path(path).open('rb')
            yield
        finally:
            if handle:handle.close()
            with _TOUCH_LOCK:
                _UNTRACKED_ACTIVE[key]-=1
                if not _UNTRACKED_ACTIVE[key]:_UNTRACKED_ACTIVE.pop(key,None)
        return
    try:yield
    finally:
        try:lease.__exit__(None,None,None)
        except (OSError,sqlite3.Error):pass
