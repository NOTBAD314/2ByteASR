"""Out-of-process resources: never hold the tested GUI's Python GIL."""
from pathlib import Path
import argparse,json,time,os
import psutil

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    out=a.output;began=time.perf_counter();known=None
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
                            cpu_s=cpu.user+cpu.system,read=io.read_bytes,write=io.write_bytes,threads=child.num_threads()))
                    except (psutil.Error,OSError):pass
                stream.write(json.dumps(dict(at=time.perf_counter()-began,processes=rows))+'\n');stream.flush()
            except (FileNotFoundError,ValueError,KeyError):pass
            except psutil.NoSuchProcess:
                if known is not None:break
            for _ in range(10):
                if (out/'resources-stop').exists():break
                time.sleep(.5)

if __name__=='__main__':main()
