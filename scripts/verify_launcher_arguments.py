"""Compile the actual root launcher and verify argv through a capture child."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    output=args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT/'tmp'):
        raise ValueError('Use a fresh directory under repository tmp')
    output.mkdir(parents=True)
    compiler=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    launcher=output/'2ByteASR.exe'
    source=ROOT/'launcher/2ByteASRLauncher.cs'
    subprocess.run([str(compiler),'/nologo','/target:winexe','/optimize+','/codepage:65001',
        '/reference:System.Windows.Forms.dll',f'/win32icon:{ROOT / "assets/app_icon.ico"}',
        f'/out:{launcher}',str(source)],check=True,capture_output=True)
    child=output/'dist/2ByteASR/2ByteASR.exe';child.parent.mkdir(parents=True)
    capture=output/'Capture.cs'
    capture.write_text('''using System;
using System.IO;
using System.Web.Script.Serialization;
class Capture { static void Main(string[] args) {
var payload = new { args = args, cwd = Environment.CurrentDirectory,
    invokerCwd = Environment.GetEnvironmentVariable("TWOBYTEASR_INVOKER_CWD") };
File.WriteAllText(Environment.GetEnvironmentVariable("TWOBYTEASR_LAUNCHER_CAPTURE_FILE"),
    new JavaScriptSerializer().Serialize(payload)); } }''','utf8')
    subprocess.run([str(compiler),'/nologo','/target:winexe','/reference:System.Web.Extensions.dll',
                    f'/out:{child}',str(capture)],check=True,capture_output=True)
    invoker=output/'不同工作目录 & (cwd)';invoker.mkdir()
    cases=[['中文 (校对)&副本.2byteproj'],['--import','素材 文件(中文)&.mp4','字幕.srt'],
           ['C:\\中文目录\\'+'长路径'*80+'\\项目 (1)&.2byteproj'],
           ['trailing\\','quoted"argument','backslash\\"quote','','--help']]
    results=[]
    for index,values in enumerate(cases):
        receipt=output/f'capture-{index}.json'
        env=os.environ.copy();env['TWOBYTEASR_LAUNCHER_CAPTURE_FILE']=str(receipt)
        launched=subprocess.run([str(launcher)]+values,cwd=invoker,env=env,timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW)
        deadline=time.monotonic()+15
        while not receipt.is_file() and time.monotonic()<deadline:time.sleep(.05)
        actual=json.loads(receipt.read_text('utf-8-sig'))
        checks={'argument_vector_exact':actual['args']==values,
                'invoker_cwd_exact':actual['invokerCwd']==str(invoker),
                'child_working_directory':actual['cwd']==str(child.parent),
                'root_exit_zero':launched.returncode==0}
        results.append({'input':values,'actual':actual,'checks':checks})
    passed=all(all(row['checks'].values()) for row in results)
    result={'passed':passed,'cases':results,'launcher':str(launcher),
            'launcher_sha256':hashlib.sha256(launcher.read_bytes()).hexdigest(),
            'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'scope':'actual compiled launcher and capture child, no GUI substitution claim'}
    (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({'passed':passed,'output':str(output)}))
    return 0 if passed else 1


if __name__=='__main__':raise SystemExit(main())
