"""Read-only Windows session status, sampled outside audio and GUI callbacks."""
import os,threading,time


class AudioSessionStatus:
    def __init__(self):
        self.value={'system_session_status':'pending'}
        self.stop=threading.Event()
        threading.Thread(target=self._run,name='audio-session-status',daemon=True).start()

    def _run(self):
        try:
            import comtypes
            from pycaw.pycaw import AudioUtilities
            comtypes.CoInitialize()
        except Exception as exc:
            self.value={'system_session_status':'unavailable','system_session_error':type(exc).__name__}
            return
        try:
            while not self.stop.wait(1.):
                try:
                    sessions=[s for s in AudioUtilities.GetAllSessions() if s.ProcessId==os.getpid()]
                    session=next((s for s in sessions if s.State==1),sessions[0] if sessions else None)
                    if session is not None:
                        volume=session.SimpleAudioVolume
                        self.value={'system_session_status':'measured','system_session_pid':os.getpid(),
                            'system_session_muted':bool(volume.GetMute()),'system_session_volume':float(volume.GetMasterVolume()),
                            'system_session_measured_at':time.monotonic()}
                except Exception as exc:self.value={'system_session_status':'unavailable','system_session_error':type(exc).__name__}
        finally:comtypes.CoUninitialize()
