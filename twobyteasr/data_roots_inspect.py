"""Read-only source/frozen data-root inspection; no downloads or registration."""
from pathlib import Path
import hashlib,json,os,sys


def main(output):
    out=Path(output).resolve()
    if 'tmp' not in (p.lower() for p in out.parts):
        raise ValueError('Inspection output must be under tmp')
    from .runtime_paths import build_runtime_paths
    from .settings import stable_settings_root
    from .studio_project import studio_data_root, project_library_root, load_library_index
    from .model_registry import scan_model_registry
    from .runtime_registry import resolve_runtime_python
    paths=build_runtime_paths()
    registry=scan_model_registry(paths=paths,verify_hashes=True)
    projects=[];errors=[];base=project_library_root()
    def onerror(exc):errors.append(str(exc))
    for folder,dirs,names in os.walk(base,onerror=onerror):
        dirs[:]=[d for d in dirs if d.lower() not in {'backup','backups','autosave','autosaves','cache','preview','tmp','recovery','exports'}]
        for name in names:
            p=Path(folder)/name
            if p.suffix!='.2byteproj' or any(s in name for s in ('.autosave','.previous','.backup','.checkpoint')):continue
            try:
                raw=p.read_bytes();d=json.loads(raw.decode('utf-8-sig'))
                projects.append(dict(path=str(p),sha256=hashlib.sha256(raw).hexdigest(),cues=len(d.get('cues',[])),
                    project_id=d.get('project_id'),media_exists=Path(d.get('media',{}).get('path','')).is_file()))
            except (OSError,ValueError) as exc:errors.append(f'{p}: {exc}')
    warnings=[];index=load_library_index(diagnostics=warnings)
    result=dict(executable=sys.executable,frozen=bool(getattr(sys,'frozen',False)),cwd=os.getcwd(),
        roots=paths.to_dict(),settings_root=str(stable_settings_root()),studio_root=str(studio_data_root()),
        project_root=str(base),models=[r.to_dict() for r in registry.records.values()],
        runtimes={role:resolve_runtime_python(role) for role in ('main','moss','firered_llm','nemotron')},
        projects=projects,index_entries=len(index),errors=errors+warnings,
        environment={k:v for k,v in os.environ.items() if k in ('TWOBYTEASR_TEST_ROOT','2BYTEASR_USER_DATA_ROOT','2BYTEASR_MODEL_ROOT','LOCALAPPDATA')})
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    return 0 if not errors else 1
