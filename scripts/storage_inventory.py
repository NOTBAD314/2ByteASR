"""Read-only A-G inventory. Writes only the requested report; never deletes."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def inventory(path):
    result = dict(path=str(path), files=0, logical_bytes=0, newest_modified=None,
                  oldest_modified=None, last_used='未记录；mtime不等于实际使用时间',
                  links_skipped=0, errors=[], largest=[])
    def walk(directory):
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            result['errors'].append(str(exc)); return
        for entry in entries:
            try:
                st = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(st.st_mode) or getattr(st, 'st_file_attributes', 0) & 0x400:
                    result['links_skipped'] += 1; continue
                if entry.is_dir(follow_symlinks=False):
                    walk(entry.path)
                else:
                    result['files'] += 1; result['logical_bytes'] += st.st_size
                    result['newest_modified'] = max(result['newest_modified'] or st.st_mtime, st.st_mtime)
                    result['oldest_modified'] = min(result['oldest_modified'] or st.st_mtime, st.st_mtime)
                    result['largest'].append(dict(path=entry.path, logical_bytes=st.st_size,
                                                  modified=st.st_mtime, hardlinks=st.st_nlink))
                    result['largest'] = sorted(result['largest'], key=lambda x:x['logical_bytes'], reverse=True)[:12]
            except OSError as exc:
                result['errors'].append(str(exc))
    if path.is_dir(): walk(path)
    result['complete'] = not result['errors'] and not result['links_skipped']
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    from twobyteasr.runtime_paths import build_runtime_paths
    paths = build_runtime_paths(persist=False)
    categories = [
        (paths.user_data_root/'runtimes'/'download-cache','C','setup_managed_backend.ps1 / uv','应用专属wheel/解释器下载缓存','官方uv prune，经离线健康与事务锁核对'),
        (paths.user_data_root/'SubtitleStudioPreview'/'mpv-overlays','A/G','studio_video_canvas / overlay_buffer','mpv像素消费者会话','有owner/lease的残留可回收；历史无owner须单独确认'),
        (paths.cache_root/'media','B/D','indexed_media','索引换封装/时间映射代理','保留原素材和映射；原丢失唯一副本保护'),
        (paths.cache_root,'B/D/G','cache / 各生成模块','音频与文字阶段缓存','原ASR/字戳/云端结果保护；本地可重建文件须归属登记'),
        (paths.user_data_root/'SubtitleStudioPreview','B/D/G','Studio','波形/缩略图/设计源/设置','源设计与正式资产保留；生成缓存单独登记'),
        (paths.model_root,'E','model_registry','已安装模型','模型工坊单独永久删除确认，不纳入缓存预算'),
        (paths.user_data_root/'runtimes','E/C','runtime_registry','离线Python环境及缓存','安装环境保护，缓存只能官方uv接口'),
        (paths.log_root,'A/G','cache.record_run_event','诊断日志','已登记普通日志14天/200MiB；证据日志保留'),
        (paths.temp_root,'A/D/G','任务临时产物','临时文件/恢复资料','按事务归属，未知内容待确认'),
    ]
    if args.project_root:
        project = args.project_root.resolve()
        for folder in ('tmp','build','dist','releases'):
            categories.append((project/folder,'F/G','构建与验收脚本','开发产物／交付／证据','按开发维护计划逐项保护、迁移或确认删除'))
    rows=[]
    for path, category, producer, purpose, recommendation in categories:
        row=inventory(path);row.update(category=category,producer=producer,purpose=purpose,
            references='未全量解析；不能仅凭未发现引用认定可删', rebuildable=category.startswith(('A','B','C')),
            recommendation=recommendation)
        rows.append(row)
    payload=dict(time=datetime.now(timezone.utc).isoformat(), scope='只读，嵌套目录统计不可相加；逻辑大小不等于物理磁盘占用', roots=paths.to_dict(), directories=rows)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(payload,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps([dict(path=r['path'],GiB=round(r['logical_bytes']/1024**3,3),files=r['files'],complete=r['complete']) for r in rows],ensure_ascii=False))


if __name__=='__main__': main()
