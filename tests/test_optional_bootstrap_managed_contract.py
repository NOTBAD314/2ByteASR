"""Bootstrap boundaries only: no downloads, installations, models, or GPU."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
import uuid
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('optional_bootstrap',ROOT/'scripts/prepare_optional_models.py')
bootstrap=importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


class ManagedOptionalContract(unittest.TestCase):
    def setUp(self):
        self.root=ROOT/'tmp'/('optional-contract-'+uuid.uuid4().hex)
        self.root.mkdir(parents=True)
        self.managed=self.root/'runtimes'
        self.base=self.managed/'python/cpython-3.12.13-windows-x86_64-none/python.exe'
        self.base.parent.mkdir(parents=True)
        self.base.write_bytes(b'fixture only')
        self.runtime=self.managed/'diarizen/python-3.12.13'
        (self.runtime/'Scripts').mkdir(parents=True)
        (self.runtime/'Scripts/python.exe').write_bytes(b'fixture only')
        self.cfg=self.runtime/'pyvenv.cfg'
        self.cfg.write_text('home = '+str(self.base.parent)+'\nversion = 3.12.13\ninclude-system-site-packages = false\n','utf8')
    def tearDown(self):
        assert self.root.resolve().is_relative_to((ROOT/'tmp').resolve())
        shutil.rmtree(self.root)
    def actual(self):
        return dict(version='3.12.13',base=str(self.base.parent),prefix=str(self.runtime),
                    stdlib=str(self.base.parent/'Lib'),typing=str(self.base.parent/'Lib/typing.py'))
    def test_every_uv_boundary_removes_parent_stdlib_and_keeps_network_settings(self):
        polluted=dict(os.environ,PYTHONHOME='main310',PYTHONPATH='main310/Lib',
                      __PYVENV_LAUNCHER__='main310/python.exe',VIRTUAL_ENV='main310',
                      UV_PYTHON='system312',HTTPS_PROXY='https://fixture.invalid',
                      SSL_CERT_FILE='fixture.crt',UV_CACHE_DIR='global-cache')
        with patch.dict(os.environ,polluted,clear=True),patch.object(bootstrap.subprocess,'run') as run:
            for arguments in (['uv','pip','sync'],['uv','pip','install','--no-build-isolation'],['uv','pip','check']):
                bootstrap.bootstrap_run(arguments,self.managed)
                env=run.call_args.kwargs['env']
                for name in ('PYTHONHOME','PYTHONPATH','__PYVENV_LAUNCHER__','VIRTUAL_ENV','UV_PYTHON'):
                    self.assertNotIn(name,env)
                self.assertEqual(env['HTTPS_PROXY'],'https://fixture.invalid')
                self.assertEqual(env['SSL_CERT_FILE'],'fixture.crt')
                self.assertEqual(env['UV_PYTHON_INSTALL_DIR'],str(self.managed/'python'))
                self.assertEqual(env['UV_CACHE_DIR'],str(self.managed/'download-cache'))
    def test_system_base_is_refused_before_running_or_altering_existing_venv(self):
        self.cfg.write_text('home = C:/system/Python312\nversion = 3.12.13\ninclude-system-site-packages = false\n','utf8')
        before=self.cfg.read_bytes()
        with patch.object(bootstrap,'bootstrap_run') as run:
            with self.assertRaisesRegex(RuntimeError,'unexpected Python base'):
                bootstrap.validate_optional_runtime(self.runtime,self.base,'3.12.13',self.managed)
            run.assert_not_called()
        self.assertEqual(self.cfg.read_bytes(),before)
    def test_config_identity_is_not_enough_foreign_real_stdlib_is_refused(self):
        actual=self.actual();actual['stdlib']='C:/system/Python310/Lib'
        with patch.object(bootstrap,'bootstrap_run',return_value=type('Result',(),{'stdout':json.dumps(actual)})()):
            with self.assertRaisesRegex(RuntimeError,'foreign Python'):
                bootstrap.validate_optional_runtime(self.runtime,self.base,'3.12.13',self.managed)
    def test_healthy_venv_probed_with_isolation_and_bytecode_off(self):
        with patch.object(bootstrap,'bootstrap_run',return_value=type('Result',(),{'stdout':json.dumps(self.actual())})()) as run:
            python=bootstrap.validate_optional_runtime(self.runtime,self.base,'3.12.13',self.managed)
        self.assertEqual(python,self.runtime/'Scripts/python.exe')
        self.assertEqual(run.call_args.args[0][1:5],['-I','-B','-X','utf8'])
    def test_uv_version_info_field_is_accepted(self):
        self.cfg.write_text(self.cfg.read_text('utf8').replace('version =','version_info ='),'utf8')
        with patch.object(bootstrap,'bootstrap_run',return_value=type('Result',(),{'stdout':json.dumps(self.actual())})()):
            self.assertEqual(bootstrap.validate_optional_runtime(self.runtime,self.base,'3.12.13',self.managed),self.runtime/'Scripts/python.exe')
    def test_fresh_venv_uses_exact_managed_base_without_download_fallback(self):
        fresh=self.managed/'vibevoice/python-3.12.13'
        with patch('twobyteasr.runtime_paths.user_data_root',return_value=self.root),patch.object(bootstrap.sys,'platform','win32'),patch.object(bootstrap,'verified_uv',return_value=self.managed/'tools/uv-0.11.7/uv.exe'),patch.object(bootstrap,'bootstrap_run') as run,patch.object(bootstrap,'validate_optional_runtime',return_value=fresh/'Scripts/python.exe'):
            bootstrap.prepare_runtime('vibevoice',fresh)
        install,venv=[call.args[0] for call in run.call_args_list]
        self.assertIn('3.12.13',install)
        self.assertEqual(venv[venv.index('--python')+1],self.base)
        self.assertIn('--managed-python',venv)
        self.assertIn('--no-python-downloads',venv)
        self.assertIn('--no-project',venv)
    def test_nonempty_incomplete_directory_is_preserved(self):
        fresh=self.managed/'other';fresh.mkdir();(fresh/'user.txt').write_text('keep','utf8')
        with patch('twobyteasr.runtime_paths.user_data_root',return_value=self.root),patch.object(bootstrap.sys,'platform','win32'),patch.object(bootstrap,'verified_uv',return_value=Path('uv')),patch.object(bootstrap,'bootstrap_run') as run:
            with self.assertRaisesRegex(RuntimeError,'not empty'):
                bootstrap.prepare_runtime('diarizen',fresh)
            run.assert_not_called()
        self.assertEqual((fresh/'user.txt').read_text('utf8'),'keep')
    def test_uv_path_override_cannot_choose_development_tool(self):
        boot=json.loads((ROOT/'dependencies.lock.json').read_text('utf8'))['managed_bootstrap']
        with patch.dict(os.environ,{'TWOBYTEASR_OPTIONAL_UV':'C:/developer/uv.exe'}):
            with self.assertRaisesRegex(RuntimeError,'application-managed uv'):
                bootstrap.verified_uv(self.managed,boot)
    def test_source_main_speaker_dependency_matches_actual_import_gate(self):
        contract=json.loads((ROOT/'dependencies.lock.json').read_text('utf8'))
        self.assertEqual(contract['environments']['main']['packages']['speechbrain'],'1.0.3')
        self.assertNotIn('speechbrain',contract['environments']['moss']['packages'])
        self.assertNotIn('speechbrain',(ROOT/'requirements-main.txt').read_text('utf8'))
    def test_formal_powershell_uses_same_preparation_contract(self):
        text=(ROOT/'scripts/setup_managed_backend.ps1').read_text('utf8')
        self.assertIn('--prepare-runtime-only',text)
        self.assertIn("$optionalVersion=$boot.python_version",text)
        self.assertNotIn("'--python','3.12.10'",text)
    @unittest.skipUnless(os.name=='nt','Windows environment provider contract')
    def test_actual_powershell_native_child_removes_then_restores_presence_and_value(self):
        shells=[Path(os.environ.get('SystemRoot','C:/Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe']
        modern=shutil.which('pwsh')
        if modern:shells.append(Path(modern))
        for index,shell in enumerate(shells):
            self.assertTrue(shell.is_file())
            receipt=self.root/('native-environment-'+str(index)+'.json')
            result=subprocess.run([str(shell),'-NoProfile','-ExecutionPolicy','Bypass','-File',
                str(ROOT/'tests/verify_managed_uv_environment.ps1'),'-Python',sys.executable,
                '-Output',str(receipt)],env=bootstrap.bootstrap_environment(self.managed),
                capture_output=True,text=True,encoding='utf8',errors='replace',timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            actual=json.loads(receipt.read_text('utf-8-sig'))
            self.assertEqual(actual['status'],'PASS')
            self.assertEqual([case['mode'] for case in actual['cases']],['absent','present','empty','child_failure'])

if __name__=='__main__':
    (ROOT/'tmp').mkdir(exist_ok=True)
    unittest.main()
