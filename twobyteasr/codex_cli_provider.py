"""Official Codex CLI as an isolated, read-only subtitle design provider.

No credential files are inspected. The CLI owns OAuth and account storage.
Protocol/flags verified against codex-cli 0.147.0's local help and schema.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import jsonschema
from pathlib import Path

from .ai_providers import AIProviderError, AITransport, CLIProvider, ProviderStatus, StructuredOutputMode, _extract_json_object, _messages_prompt
from .llm_config import cache_service_models, discovered_service_models
from .processes import popen_hidden_subprocess, stop_process_tree
from .provider_diagnostics import redact_diagnostics


class CodexCLIProvider(CLIProvider):
    provider_id = "openai_codex_cli"
    transport = AITransport.CODEX_CLI
    purpose = "OpenAI Codex CLI"
    executable_names = ("codex.exe", "codex")
    _capability_cache = {}
    _catalogue = {}
    _model_defaults = {}
    _metadata_lock = threading.Lock()
    _required_flags = ("--ignore-user-config", "--ignore-rules", "--ephemeral", "--output-schema", "--sandbox", "--json")
    # Disable execution, delegated agents, configured integrations and browser tools.
    # No user/project configuration or rules are loaded; working root is empty.
    _disabled_features = ("shell_tool", "unified_exec", "code_mode", "code_mode_host",
        "multi_agent", "multi_agent_v2", "apps", "plugins", "hooks", "browser_use",
        "browser_use_external", "browser_use_full_cdp_access", "computer_use", "in_app_browser",
        "image_generation", "skill_search", "tool_suggest", "workspace_dependencies", "view_image",
        "memories", "goals")

    def _discover_executable(self):
        # Prefer the installed official binary over third-party PATH wrappers.
        local = os.environ.get("LOCALAPPDATA", "")
        candidates = [Path(local)/"Programs/OpenAI/Codex/bin/codex.exe"] if local else []
        explicit = os.environ.get("TWOBYTEASR_CODEX_EXECUTABLE", "")
        if explicit:candidates.insert(0,Path(explicit))
        found = shutil.which("codex.exe")
        if found:candidates.append(Path(found))
        for candidate in candidates:
            if candidate.is_file():return str(candidate)
        if os.name != "nt":return shutil.which("codex") or ""
        return ""

    def structured_output_mode(self):
        return StructuredOutputMode.STRICT_JSON_SCHEMA

    def _verify_capabilities(self, cancel_check=None):
        key = self.executable
        with self._metadata_lock: cached = self._capability_cache.get(key)
        if cached:
            self.cli_version = cached["version"]
            return cached
        detected = self.detect_installation(timeout=5, cancel_check=cancel_check)
        if not detected.available:raise AIProviderError(detected.message,category="not_installed")
        result = self._run_cli_command([self.executable,"exec","--help"],purpose="Codex exec capabilities",timeout=5,cancel_check=cancel_check)
        missing = [flag for flag in self._required_flags if flag not in result.stdout]
        if result.returncode or missing:
            raise AIProviderError("当前 Codex CLI 缺少安全隔离或 schema 参数："+", ".join(missing),category="unsupported_cli")
        flags = self._run_cli_command([self.executable,"features","list"],purpose="Codex feature capabilities",timeout=5,cancel_check=cancel_check)
        supported = {line.split()[0] for line in flags.stdout.splitlines() if line.split()}
        if flags.returncode or "shell_tool" not in supported:
            raise AIProviderError("无法验证 Codex shell_tool 禁用能力；请更新官方 CLI。",category="unsupported_cli")
        value = {"version":getattr(self,"cli_version",""),"image_flag":"--image" in result.stdout,
                 "disabled_features":tuple(x for x in self._disabled_features if x in supported)}
        with self._metadata_lock:self._capability_cache[key]=value
        return value

    def runtime_capabilities(self):
        with self._metadata_lock:
            verified = self._capability_cache.get(self.executable,{})
            entry = self._catalogue.get(self.model,{})
        return {"vision":bool(verified.get("image_flag") and "image" in entry.get("inputModalities",[])),
                "structured_output":bool(verified), "structured_output_mode":"STRICT_JSON_SCHEMA",
                "streaming":False}

    def validate(self, *, timeout=20, cancel_check=None, use_cache=True):
        cached = self._cached_status() if use_cache else None
        if cached:
            self.last_timings={"cache_hit":True}
            return cached
        if not self.executable:return ProviderStatus(False,False,"未安装官方 Codex CLI；请选择安装帮助。")
        self._verify_capabilities(cancel_check)
        result = self._run_cli_command([self.executable,"login","status"],purpose="Codex login status",timeout=min(timeout,5),cancel_check=cancel_check)
        text = result.stdout+"\n"+result.stderr
        logged = result.returncode==0 and "logged in" in text.lower() and "not logged in" not in text.lower()
        message = "Codex CLI 已登录（模型调用待真实请求验证）" if logged else "Codex CLI 未登录；点击官方登录完成 OAuth 后重新检测。"
        return self._store_status(ProviderStatus(True,logged,message,discovered_service_models("codex_cli")[0]))

    def discover_models(self, *, timeout=20, cancel_check=None, refresh=False):
        cached,_ = discovered_service_models("codex_cli")
        if cached and not refresh:return cached
        self._verify_capabilities(cancel_check)
        # model/list is the official local app-server protocol, NOT an invented
        # `codex models` command. No thread or model turn is started here.
        packets = [
            {"id":1,"method":"initialize","params":{"clientInfo":{"name":"2byteasr","version":"1.0"}}},
            {"method":"initialized","params":{}},
            {"id":2,"method":"model/list","params":{"limit":100,"includeHidden":False}},
        ]
        response = {}
        def line(name,text):
            if name!="stdout":return
            try:payload=json.loads(text)
            except ValueError:return
            if payload.get("id")==2:response.update(payload)
        with tempfile.TemporaryDirectory(prefix="2byte-codex-catalogue-") as directory:
            try:
                self._run_cli_command([self.executable,"app-server","--stdio"],purpose="Codex models model/list",
                    timeout=timeout,cancel_check=cancel_check,cwd=directory,
                    input_text="".join(json.dumps(x)+"\n" for x in packets),keep_stdin_open=True,
                    on_line=line,stop_when=lambda:bool(response))
            except subprocess.TimeoutExpired as exc:
                raise AIProviderError("Codex 模型列表超时；保留当前选择。",category="model_discovery") from exc
        if response.get("error"):
            raise AIProviderError(redact_diagnostics(str(response["error"])),category="model_discovery")
        rows = response.get("result",{}).get("data",[])
        models = tuple(dict.fromkeys(str(row.get("model") or row.get("id") or "") for row in rows if isinstance(row,dict)))
        models = tuple(x for x in models if x)
        if not models:raise AIProviderError("Codex model/list 未返回模型；可手动输入模型 ID。",category="model_discovery")
        if any('inputModalities' not in row for row in rows):
            key=(self.executable,getattr(self,'cli_version',''))
            with self._metadata_lock:defaults=self._model_defaults.get(key)
            if defaults is None:
                # Optional fields are omitted on the wire. Read their defaults
                # from THIS installed CLI's generated protocol, not API lore.
                defaults=[]
                with tempfile.TemporaryDirectory(prefix='2byte-codex-protocol-') as directory:
                    result=self._run_cli_command([self.executable,'app-server','generate-json-schema','--out',directory],
                        purpose='Codex model modality schema',timeout=5,cancel_check=cancel_check,cwd=directory)
                    if result.returncode==0:
                        for path in Path(directory).glob('*.json'):
                            try:
                                schema=json.loads(path.read_text(encoding='utf-8'))
                                model=schema.get('definitions',{}).get('Model',{})
                                value=model.get('properties',{}).get('inputModalities',{}).get('default')
                                if isinstance(value,list):defaults=value;break
                            except (OSError,ValueError):continue
                with self._metadata_lock:self._model_defaults[key]=defaults
            for row in rows:
                if 'inputModalities' not in row:row['inputModalities']=list(defaults)
        with self._metadata_lock:
            self._catalogue.update({str(row.get("model") or row.get("id")):dict(row) for row in rows})
        cache_service_models("codex_cli",models)
        return models

    def login(self, *, timeout=300, on_progress=None, cancel_check=None):
        if not self.executable:return ProviderStatus(False,False,"未安装官方 Codex CLI")
        if cancel_check and cancel_check():
            raise AIProviderError("Codex 登录已取消。", category="cancelled")
        started = time.monotonic()
        self.last_invocation_trace["login"] = {"created": False, "pid": None, "exit_code": None}
        try:
            process = popen_hidden_subprocess([self.executable,"login"],
                purpose="Codex explicit OAuth login", visible_console=True,
                stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        except OSError as exc:
            detail = redact_diagnostics(str(exc))
            self.last_invocation_trace["login"]["error"] = detail
            raise AIProviderError(f"无法启动官方 Codex 登录窗口：{detail}", category="login_spawn") from exc
        trace = self.last_invocation_trace["login"]
        trace.update(created=True, pid=process.pid)
        errors = []
        def drain():
            if process.stderr is not None:
                for line in process.stderr:
                    errors.append(redact_diagnostics(line.strip()))
                    del errors[:-20]
        reader = threading.Thread(target=drain, daemon=True, name="codex-login-stderr")
        reader.start()
        if on_progress:on_progress("已打开登录窗口，等待认证；可在此取消。")
        with self._active_process_lock:self._active_process=process
        deadline = time.monotonic()+timeout
        try:
            while process.poll() is None:
                if cancel_check and cancel_check():raise AIProviderError("Codex 登录已取消。",category="cancelled")
                if time.monotonic()>deadline:raise AIProviderError("Codex 官方登录等待超时，可再次打开登录。",category="timeout")
                time.sleep(.1)
        finally:
            if process.poll() is None:stop_process_tree(process)
            reader.join(timeout=.5)
            trace.update(exit_code=process.poll(), seconds=time.monotonic()-started, stderr="\n".join(errors)[-1200:])
            with self._active_process_lock:
                if self._active_process is process:self._active_process=None
        status = self.validate(timeout=5,use_cache=False)
        if process.returncode and not status.authenticated:
            return ProviderStatus(True, False, f"官方登录窗口已退出（{process.returncode}）：" + (trace["stderr"] or "登录未完成或已取消"))
        return status

    def logout(self, *, cancel_check=None):
        result=self._run_cli_command([self.executable,"logout"],purpose="Codex explicit logout",timeout=10,cancel_check=cancel_check)
        self.invalidate_status_cache()
        if result.returncode:raise AIProviderError(redact_diagnostics(result.stderr or result.stdout),category="logout_failed")
        return ProviderStatus(True,False,"Codex CLI 已退出登录。")

    def _exec_command(self, directory, schema_path=None, images=()):
        verified=self._capability_cache[self.executable]
        command=[self.executable,"--ask-for-approval","never","exec","--ignore-user-config","--ignore-rules",
                 "--ephemeral","--sandbox","read-only","--skip-git-repo-check","--json","--color","never","--cd",str(directory)]
        for feature in verified["disabled_features"]:command.extend(("--disable",feature))
        if self.model:command.extend(("--model",self.model))
        if schema_path:command.extend(("--output-schema",str(schema_path)))
        for path in images:command.extend(("--image",str(path)))
        command.append("-")
        return command

    def complete(self,messages,*,timeout=120,cancel_check=None,json_schema=None,on_stream_event=None,**kwargs):
        if kwargs.get('enable_search'):
            raise AIProviderError('当前 Codex 适配器未验证联网检索能力。',category='unsupported_search')
        from .provider_input_budget import prepare_input, InputBudgetError, launch_budget
        try:
            messages,budget=prepare_input(messages,schema=json_schema,max_tokens=kwargs.get('max_tokens',3500),
                operation=kwargs.get('operation_kind','general'),scope=kwargs.get('input_scope'),
                crops=kwargs.get('image_crops'),comparison=kwargs.get('image_comparison',False))
        except InputBudgetError as exc:
            self.last_timings={'request_budget':exc.report}
            if kwargs.get('request_diagnostics') is not None:
                kwargs['request_diagnostics'].update(request_budget=exc.report,failure_stage='local_budget')
            raise AIProviderError(str(exc),category='request_too_large') from exc
        self._verify_capabilities(cancel_check)
        seconds=max(timeout) if isinstance(timeout,tuple) else float(timeout)
        with tempfile.TemporaryDirectory(prefix="2byte-codex-design-") as directory:
            root=Path(directory); images=[]; plain=[]
            for message in messages:
                content=message.get("content","")
                if isinstance(content,list):
                    texts=[]
                    for part in content:
                        if part.get("type")=="text":texts.append(str(part.get("text", "")))
                        elif part.get("type")=="image_url":
                            if not self.runtime_capabilities()["vision"]:
                                raise AIProviderError("当前 Codex 模型图片能力未验证，请刷新模型或使用文字上下文。",category="unsupported_image")
                            url=str(part.get("image_url",{}).get("url", ""))
                            if not url.startswith(("data:image/png;base64,","data:image/jpeg;base64,")):
                                raise AIProviderError("Codex 仅接收本次捕获的 PNG/JPEG 图像。",category="unsupported_image")
                            data=base64.b64decode(url.split(",",1)[1],validate=True)
                            if len(data)>20_000_000:raise AIProviderError("图片超过20MB。",category="unsupported_image")
                            path=root/f"context-{len(images)}.png";path.write_bytes(data);images.append(path)
                    content="\n".join(texts)
                plain.append({"role":message.get("role","user"),"content":str(content)})
            schema_path=None
            if json_schema is not None:
                schema_path=root/'response-schema.json';schema_path.write_text(json.dumps(json_schema),encoding='utf-8')
            final=[];errors=[]
            def consume(name,line):
                if name!='stdout':
                    if on_stream_event and line.strip():on_stream_event('stderr',redact_diagnostics(line.strip()[-400:]))
                    return
                try:event=json.loads(line)
                except ValueError:return
                kind=event.get('type','');item=event.get('item') or {}
                if kind=='item.completed' and item.get('type')=='agent_message':
                    final.append(str(item.get('text') or ''))
                    if on_stream_event:on_stream_event('delta',final[-1])
                if kind in ('error','turn.failed'):
                    errors.append(redact_diagnostics(str(event.get('message') or event.get('error') or event)))
                elif on_stream_event:on_stream_event('stage',str(kind))
            prompt="Return only the requested response. Do not use tools or inspect files.\n"+_messages_prompt(plain)
            command=self._exec_command(root,schema_path,images)
            budget.update(launch_budget(command),transport='official_stdin',
                          transmitted_prompt_utf8_bytes=len(prompt.encode('utf8')))
            try:
                result=self._run_cli_command(command,purpose='Codex isolated completion request',
                    timeout=seconds,cancel_check=cancel_check,cwd=root,input_text=prompt,on_line=consume,
                    request_diagnostics=kwargs.get('request_diagnostics'))
            except subprocess.TimeoutExpired as exc:raise AIProviderError("Codex 设计请求超时。",category='timeout') from exc
            finally:
                self.last_timings['request_budget']=budget
                self.last_invocation_trace['request_budget']=budget
                if kwargs.get('request_diagnostics') is not None:
                    kwargs['request_diagnostics'].update(request_budget=budget,
                        cli_version=getattr(self,'cli_version','unknown'),timings=dict(self.last_timings))
            if result.returncode or errors:
                detail=redact_diagnostics('\n'.join(errors) or (result.stderr or result.stdout)[-800:])
                category='authentication_required' if self._auth_error(detail) or '401' in detail else 'provider_error'
                lowered=detail.lower()
                if category=='provider_error':
                    if 'model' in lowered and any(x in lowered for x in ('not supported','not found','unavailable','does not exist')):
                        category='model_unavailable'
                    elif any(x in lowered for x in ('connection','network','dns','resolve host','tls','socket')):
                        category='network'
                raise AIProviderError(detail or f'Codex exit {result.returncode}',category=category)
            if not final:raise AIProviderError('Codex 未返回设计文本。',category='empty_response')
            return final[-1]

    def structured_complete(self,messages,schema,**kwargs):
        value=self.complete(messages,json_schema=schema,**kwargs)
        began=time.perf_counter()
        try:
            result=_extract_json_object(value)
            jsonschema.validate(result,schema)
            return result
        except (ValueError, jsonschema.ValidationError) as exc:
            self.last_invocation_trace['schema_error']=redact_diagnostics(str(exc))
            raise AIProviderError(f'Codex schema 校验失败：{exc}',category='schema_validation') from exc
        finally:self.last_timings['schema_parse_seconds']=time.perf_counter()-began
