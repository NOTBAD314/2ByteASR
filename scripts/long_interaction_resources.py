"""Out-of-process resources: never hold the tested GUI's Python GIL."""
from pathlib import Path
import argparse,json,time,os
import shutil
import subprocess
import psutil


def gpu_memory(tool, pids):
    if not tool:
        return {"status": "nvidia-smi-unavailable"}
    options = dict(capture_output=True, text=True, timeout=3,
                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        total = subprocess.run([tool, '--query-gpu=index,memory.used',
                                '--format=csv,noheader,nounits'], **options)
        per_process = subprocess.run([tool, '--query-compute-apps=pid,used_gpu_memory',
                                      '--format=csv,noheader,nounits'], **options)
    except (OSError, subprocess.TimeoutExpired):
        return {"status": "sample-failed"}
    device = {}
    if total.returncode == 0:
        for line in total.stdout.splitlines():
            parts = [part.strip() for part in line.split(',')]
            if len(parts) == 2 and all(part.isdecimal() for part in parts):
                device[parts[0]] = int(parts[1])
    owned = {}
    if per_process.returncode == 0:
        for line in per_process.stdout.splitlines():
            parts = [part.strip() for part in line.split(',')]
            if len(parts) == 2 and parts[0].isdecimal() and int(parts[0]) in pids:
                owned[parts[0]] = int(parts[1]) if parts[1].isdecimal() else None
    return dict(status="sampled" if device else "sample-failed",
                device_used_mib=device, owned_compute_used_mib=owned)


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    out=a.output;began=time.perf_counter();known=None
    nvidia_smi = shutil.which('nvidia-smi')
    next_gpu_sample = began
    with (out/'resources-external.jsonl').open('w',encoding='utf8') as stream:
        while not (out/'resources-stop').exists():
            try:
                result=json.loads((out/'result.json').read_text('utf8'))
                pid=int(result['pid']);process=psutil.Process(pid)
                identity=(pid,process.create_time())
                if known is not None and known!=identity:break
                known=identity;rows=[]
                for child in [process]+process.children(recursive=True):
                    try:
                        mem=child.memory_info();cpu=child.cpu_times();io=child.io_counters()
                        rows.append(dict(pid=child.pid,name=child.name(),rss=mem.rss,private=getattr(mem,'private',None),
                            cpu_s=cpu.user+cpu.system,read=io.read_bytes,write=io.write_bytes,threads=child.num_threads(),
                            handles=child.num_handles() if os.name=='nt' else None))
                    except (psutil.Error,OSError):pass
                stamp=time.perf_counter()
                entry = dict(at=stamp-began,monotonic=stamp,processes=rows)
                if stamp >= next_gpu_sample:
                    entry['gpu'] = gpu_memory(nvidia_smi, {row['pid'] for row in rows})
                    next_gpu_sample = stamp + 60
                stream.write(json.dumps(entry)+'\n');stream.flush()
            except (FileNotFoundError,ValueError,KeyError):pass
            except psutil.NoSuchProcess:
                if known is not None:break
            for _ in range(10):
                if (out/'resources-stop').exists():break
                time.sleep(.5)

if __name__=='__main__':main()
