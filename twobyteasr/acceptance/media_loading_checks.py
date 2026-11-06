"""Disposable reader, cancellation, missing-device and drive relocation checks."""
import ctypes
import os
from pathlib import Path
import subprocess
import threading
import time


def run(output,check,pump):
    from ..media.media_availability import probe_sources,shutdown_probe_worker,apply_availability,media_available
    from ..studio.studio_helpers import probe_media_identity
    from ..media.relocation_identity import verified_relocation
    from types import SimpleNamespace
    media=output/'fixture.mp4'
    def background(call,timeout=12):
        done=threading.Event();result={}
        def work():
            try:result['value']=call()
            except BaseException as exc:result['error']=exc
            finally:done.set()
        threading.Thread(target=work,daemon=True).start()
        end=time.monotonic()+timeout
        while not done.is_set() and time.monotonic()<end:pump(.03)
        if not done.is_set():raise TimeoutError('owned reader did not finish')
        if 'error' in result:raise result['error']
        return result['value']
    shutdown_probe_worker()
    healthy=background(lambda:probe_sources([str(media)],decode=True))[str(media)]
    check('normal disk decoded identity',healthy['status']=='available' and healthy['identity']['has_audio'])
    asset=SimpleNamespace(canonical_source=str(media),offline=False,relink_state='linked',fingerprint=healthy['identity']['fingerprint'])
    project=SimpleNamespace(media_pool=[asset])
    apply_availability(project,{str(media):healthy})
    shutdown_probe_worker();os.environ['TWOBYTEASR_TEST_MEDIA_DELAY']='2'
    try:
        previous={str(media):dict(healthy,next_probe_monotonic=0)}
        slow=background(lambda:probe_sources([str(media)],timeout=.1,previous=previous))[str(media)]
        apply_availability(project,{str(media):slow})
        check('sleeping reader remains slow and preserves verified media',slow['status']=='slow' and not asset.offline and media_available(project,str(media)))
        cancel=threading.Event();threading.Timer(.15,cancel.set).start()
        try:background(lambda:probe_sources([str(media)],timeout=3,cancel_check=cancel.is_set))
        except InterruptedError:check('slow reader cancels within bounded lifetime',True)
        else:check('slow reader cancels within bounded lifetime',False)
    finally:
        os.environ.pop('TWOBYTEASR_TEST_MEDIA_DELAY',None);shutdown_probe_worker()
    recovered=background(lambda:probe_sources([str(media)],decode=True))[str(media)]
    check('slow reader can recover',recovered['status']=='available')
    missing=output/'missing.mp4'
    check('genuine missing differs from slow',background(lambda:probe_sources([str(missing)]))[str(missing)]['status']=='missing')
    drives=[]
    if os.name=='nt':
        mask=ctypes.WinDLL('kernel32').GetLogicalDrives()
        unused=[chr(65+bit)+':' for bit in range(25,3,-1) if not mask&(1<<bit)][:2]
        subst=Path(os.environ.get('SystemRoot','C:/Windows'))/'System32/subst.exe'
        try:
            if len(unused)!=2:raise RuntimeError('No two unused drive letters for owned mapping test')
            old,new=unused
            folder=output/'owned-drive';folder.mkdir(exist_ok=True)
            import shutil
            shutil.copy2(media,folder/'fixture.mp4')
            def mount(drive):
                subprocess.run([str(subst),drive,str(folder)],check=True,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
                drives.append(drive)
            def unmount(drive):
                subprocess.run([str(subst),drive,'/D'],check=True,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
                drives.remove(drive)
            mount(old);old_path=old+'\\fixture.mp4'
            original=background(lambda:probe_sources([old_path],decode=True))[old_path]
            check('mapped external-drive fixture is playable',original['status']=='available')
            unmount(old);shutdown_probe_worker()
            absent=background(lambda:probe_sources([old_path]))[old_path]
            check('temporary drive disconnect differs from missing file',absent['status']=='offline',absent)
            mount(new);new_path=new+'\\fixture.mp4';shutdown_probe_worker()
            relocated=background(lambda:probe_sources([new_path],decode=True))[new_path]
            expected=SimpleNamespace(canonical_source=old_path,fingerprint=original['identity']['fingerprint'])
            check('drive-letter change verifies original identity',verified_relocation(expected,relocated,original['identity']),
                  dict(original=original['identity'],relocated=relocated['identity']))
            wrong=dict(relocated,identity=dict(relocated['identity'],size=1))
            check('same name with wrong identity is rejected',not verified_relocation(expected,wrong,original['identity']))
        finally:
            for drive in list(drives):
                subprocess.run([str(subst),drive,'/D'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
            shutdown_probe_worker()
