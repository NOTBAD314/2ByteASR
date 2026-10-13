"""Temporary test-session unmute; never touch another application/session."""
import json,threading,time,os

def monitor(out,stopped):
    import comtypes
    comtypes.CoInitialize()
    from pycaw.pycaw import AudioUtilities
    owned={};rows=[]
    try:
        while not stopped.wait(.3):
            try:
                state=json.loads((out/'latest.json').read_text('utf8'));pid=state.get('audio',{}).get('endpoint_pid')
                if not pid:continue
                for session in AudioUtilities.GetAllSessions():
                    if session.ProcessId!=pid:continue
                    proc=session.Process
                    if proc is None:continue
                    command=' '.join(proc.cmdline())
                    if 'twobyteasr.audio_process' not in command and '--studio-audio-worker' not in command:continue
                    volume=session.SimpleAudioVolume
                    if pid not in owned:
                        previous=volume.GetMute();owned[pid]=(session,previous)
                        rows.append({'pid':pid,'wall':time.perf_counter(),'previous_mute':previous,'volume':volume.GetMasterVolume()})
                        if previous:volume.SetMute(0,None)
                        (out/'owned-session-unmute.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
            except (OSError,ValueError,comtypes.COMError):pass
    finally:
        for pid,(session,previous) in owned.items():
            try:
                session.SimpleAudioVolume.SetMute(previous,None)
                rows.append({'pid':pid,'restored_mute':previous,'wall':time.perf_counter()})
            except Exception as exc:rows.append({'pid':pid,'restore_error':type(exc).__name__})
        (out/'owned-session-unmute.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
        comtypes.CoUninitialize()
