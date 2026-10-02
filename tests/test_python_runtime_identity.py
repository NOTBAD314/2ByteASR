# SPDX-License-Identifier: GPL-3.0-only
"""Cheap real-interpreter regression; runnable before third-party installs."""
from __future__ import annotations
import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
import venv
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from twobyteasr import runtime_registry as registry
from twobyteasr.processes import external_python_environment, popen_hidden_subprocess, python_utf8_command
from twobyteasr.python_runtime_identity import python_entry_path

class RuntimeEntryTests(unittest.TestCase):
    def setUp(self):
        scratch=Path(os.environ.get("TWOBYTEASR_TEST_ROOT") or ROOT/"tmp/macos-worker-runtime-20261002/venv-tests")
        scratch.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(prefix="2byte-venv-",dir=scratch)
        self.root=Path(self.temp.name)/"中文 spaces";self.root.mkdir()
        env=dict(os.environ)
        for key in tuple(env):
            if key.startswith("TWOBYTEASR_") or key in {"2BYTEASR_USER_DATA_ROOT","2BYTEASR_MODEL_ROOT"}:
                env.pop(key)
        env.update(LOCALAPPDATA=str(self.root/"local"),APPDATA=str(self.root/"roaming"),
                   TWOBYTEASR_CHILD_PROCESS_LOG=str(self.root/"children.jsonl"))
        self.environment=patch.dict(os.environ,env,clear=True);self.environment.start()
        registry.reset_runtime_registry_cache()
        # Disable only asynchronous window observation; the real canonical
        # subprocess launcher and actual child remain exercised.
        self.observer=patch("twobyteasr.process_diagnostics.record_process",lambda payload:None)
        self.observer.start()
        self.entries=[]
        for number in (1,2):
            folder=self.root/("env "+str(number))
            venv.EnvBuilder(with_pip=False,symlinks=os.name!="nt").create(folder)
            python=registry.runtime_python_path(folder)
            result=subprocess.run([str(python),"-I","-X","utf8","-c","import site;print(site.getsitepackages()[0])"],
                                  capture_output=True,text=True,check=True,env=external_python_environment())
            packages=Path(result.stdout.strip())
            (packages/"runtime_identity_marker_2byte.py").write_text("VALUE="+repr(number),encoding="utf8")
            (packages/"funasr.py").write_text("AutoModel=object\nVALUE="+repr(number),encoding="utf8")
            metadata=packages/"funasr-99.0.dist-info";metadata.mkdir()
            (metadata/"METADATA").write_text("Metadata-Version: 2.1\nName: funasr\nVersion: 99.0\n",encoding="utf8")
            self.entries.append(python)
    def tearDown(self):
        registry.reset_runtime_registry_cache();self.observer.stop();self.environment.stop();self.temp.cleanup()
    def run_child(self,command):
        process=popen_hidden_subprocess(python_utf8_command(command),purpose="real venv regression",
             env=external_python_environment(),cwd=str(self.root),stdout=subprocess.PIPE,
             stderr=subprocess.PIPE,text=True,encoding="utf8")
        stdout,stderr=process.communicate(timeout=60)
        return process.returncode,stdout,stderr
    def marker(self,python):
        return self.run_child([str(python),"-I","-c",
             "import json,sys,runtime_identity_marker_2byte as m;print(json.dumps(dict(value=m.VALUE,prefix=sys.prefix,executable=sys.executable)))"])
    def probe(self,python,expected):
        return self.run_child([str(python),"-I",str(ROOT/"sensevoice_worker.py"),"--probe-import",
                              "--expected-prefix",str(expected),"--expected-funasr-version","99.0",
                              "--diagnostics-dir",str(self.root/"diagnostics")])
    def test_resolver_and_real_production_subprocess_keep_each_venv(self):
        observed=[]
        for value,entry in enumerate(self.entries,1):
            os.environ["TWOBYTEASR_MAIN_PYTHON"]=str(entry)
            selected=registry.resolve_runtime_python("main")
            self.assertEqual(selected,python_entry_path(entry))
            code,stdout,stderr=self.marker(selected)
            self.assertEqual(code,0,stderr);row=json.loads(stdout);observed.append(row)
            self.assertEqual(row["value"],value)
            self.assertEqual(Path(row["prefix"]),entry.parent.parent)
            code,stdout,stderr=self.probe(selected,entry.parent.parent)
            self.assertEqual(code,0,stderr)
            self.assertNotIn("[2BYTEASR_PYTHON_IDENTITY]",stdout)
        self.assertNotEqual(observed[0]["prefix"],observed[1]["prefix"])
        if os.name!="nt":
            self.assertEqual(self.entries[0].resolve(),self.entries[1].resolve())
            code,_,_=self.marker(self.entries[0].resolve())
            self.assertNotEqual(code,0,"Resolved base must not see the venv-only marker")
            code,_,stderr=self.probe(self.entries[0].resolve(),self.entries[0].parent.parent)
            self.assertNotEqual(code,0);self.assertIn("selected virtual environment",stderr)
    def test_registry_restart_recovery_uses_explicit_root(self):
        entry=self.entries[0];registry.register_runtime("main",str(entry))
        os.environ.pop("TWOBYTEASR_MAIN_PYTHON",None)
        importlib.reload(registry)
        self.assertEqual(registry.resolve_runtime_python("main"),str(entry))
        # Simulate the legacy persisted base path, retaining a known venv root.
        saved=registry.load_registry()
        saved["main"]["python_executable"]=str(entry.resolve())
        registry._save_registry(saved);registry.reset_runtime_registry_cache()
        self.assertEqual(registry.resolve_runtime_python("main"),str(entry))
        self.assertEqual(self.marker(registry.resolve_runtime_python("main"))[0],0)
        # Another process loads the same registry without an environment override.
        code="import sys;sys.path.insert(0,"+repr(str(ROOT))+");from twobyteasr.runtime_registry import resolve_runtime_python;print(resolve_runtime_python('main'))"
        status,stdout,stderr=self.run_child([str(entry),"-I","-c",code])
        self.assertEqual(status,0,stderr);self.assertEqual(stdout.strip(),str(entry))
    def test_readiness_child_cannot_replace_previous_registration(self):
        old,new=self.entries
        registry.register_runtime("main",str(old))
        original=registry.registry_path().read_bytes()
        os.environ["TWOBYTEASR_MAIN_PYTHON"]=str(new)
        os.environ["TWOBYTEASR_RUNTIME_REGISTRY_READ_ONLY"]="1"
        # Production resolver still selects the candidate for a real import,
        # but a failing readiness child must not commit its role registration.
        selected=registry.resolve_runtime_python("main")
        self.assertEqual(selected,str(new))
        status,_,stderr=self.probe(selected,old.parent.parent)
        self.assertNotEqual(status,0)
        self.assertEqual(registry.registry_path().read_bytes(),original)

    def test_missing_runtime_and_boundary_are_not_silently_repaired_to_base(self):
        os.environ["TWOBYTEASR_TEST_ROOT"]=str(self.root)
        os.environ["TWOBYTEASR_MAIN_PYTHON"]=str(self.root/"missing/bin/python")
        registry.reset_runtime_registry_cache()
        self.assertEqual(registry.resolve_runtime_python("main"),"")
        if os.name!="nt":
            os.environ["TWOBYTEASR_MAIN_PYTHON"]=str(self.entries[0])
            # Canonical target lies outside disposable root; retain old boundary.
            self.assertEqual(registry.resolve_runtime_python("main"),"")
    def test_wrong_venv_is_a_real_failed_production_import_probe(self):
        status,_,stderr=self.probe(self.entries[1],self.entries[0].parent.parent)
        self.assertNotEqual(status,0)
        self.assertIn("Traceback (most recent call last)",stderr)
        records=list((self.root/"diagnostics").glob("*worker-import-failed.json"))
        self.assertTrue(records)
        self.assertFalse(json.loads(records[0].read_text("utf8"))["import_passed"])
    def test_external_environment_is_cleaned_without_mutating_parent(self):
        parent=dict(os.environ,PYTHONHOME="wrong-home",PYTHONPATH="wrong-path",
                    VIRTUAL_ENV="wrong-env",__PYVENV_LAUNCHER__="wrong-python",
                    DYLD_LIBRARY_PATH="bundle",DYLD_LIBRARY_PATH_ORIG="original",
                    _PYI_APPLICATION_HOME_DIR="bundle",_PYI_PARENT_PROCESS_LEVEL="1",
                    DEEPSEEK_API_KEY="do-not-record")
        copy=dict(parent);child=external_python_environment(parent)
        self.assertEqual(parent,copy)
        for name in ("PYTHONHOME","PYTHONPATH","VIRTUAL_ENV","__PYVENV_LAUNCHER__","_PYI_APPLICATION_HOME_DIR"):
            self.assertNotIn(name,child)
        self.assertEqual(child["DYLD_LIBRARY_PATH"],"original")
        from twobyteasr.python_runtime_identity import environment_difference
        self.assertNotIn("DEEPSEEK_API_KEY",environment_difference(parent,child))

if __name__=="__main__":unittest.main()
