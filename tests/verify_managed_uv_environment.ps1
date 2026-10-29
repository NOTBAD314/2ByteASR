[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Python,
      [Parameter(Mandatory=$true)][string]$Output)
$ErrorActionPreference='Stop'
$w=Split-Path -Parent $PSScriptRoot
$env:TEMP=Join-Path $w 'tmp';$env:TMP=$env:TEMP
if (-not ([IO.Path]::GetFullPath($Output)).StartsWith($w+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) {throw 'Evidence output must stay in workspace'}
# Load only the production RunUv function AST; never execute the bootstrap body.
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $w 'scripts/setup_managed_backend.ps1'),[ref]$tokens,[ref]$errors)
if ($errors.Count) {throw 'Production script has parser errors'}
$function=$ast.Find({param($a) $a -is [Management.Automation.Language.FunctionDefinitionAst] -and $a.Name -eq 'RunUv'},$true)
. ([ScriptBlock]::Create($function.Extent.Text))
$script:uv=$Python;$script:phase='tiny_environment_probe'
$keys=@('PYTHONHOME','PYTHONPATH','__PYVENV_LAUNCHER__','VIRTUAL_ENV','PYTHONEXECUTABLE','PYTHONPLATLIBDIR','_PYTHON_SYSCONFIGDATA_NAME','UV_PYTHON','UV_PROJECT_ENVIRONMENT','UV_SYSTEM_PYTHON')
$nativeProbe=Join-Path $w 'tmp/runuv_native_environment_probe.py'
[IO.File]::WriteAllText($nativeProbe,'import os,json,sys;keys=sys.argv[3].split("|");value={k:{"exists":k in os.environ,"value":os.environ.get(k)} for k in keys};open(sys.argv[1],"w").write(json.dumps(value));sys.exit(int(sys.argv[2]))',[Text.UTF8Encoding]::new($false))
$cases=@()
foreach ($mode in @('absent','present','empty','child_failure')) {
    foreach ($name in $keys) {Remove-Item -LiteralPath ('Env:'+ $name) -ErrorAction SilentlyContinue}
    if ($mode -eq 'present' -or $mode -eq 'child_failure') {
        $env:UV_SYSTEM_PYTHON='false';$env:UV_PYTHON='foreign-python';$env:PYTHONHOME='foreign-stdlib'
    } elseif ($mode -eq 'empty') {
        # Native API also models an empty value inherited by Windows PowerShell.
        if (-not ('EnvironmentProbeNative' -as [type])) {
            Add-Type 'using System.Runtime.InteropServices; public static class EnvironmentProbeNative { [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] public static extern bool SetEnvironmentVariable(string name, string value); }'
        }
        if (-not [EnvironmentProbeNative]::SetEnvironmentVariable('UV_SYSTEM_PYTHON','')) {throw 'Cannot prepare empty probe'}
    }
    $before=@{}
    foreach ($name in $keys) {$before[$name]=@{Exists=(Test-Path -LiteralPath ('Env:'+ $name));Value=[Environment]::GetEnvironmentVariable($name,'Process')}}
    $childFile=Join-Path $w ('tmp/runuv-child-'+$PSVersionTable.PSVersion.Major+'-'+$mode+'.json')
    $exit=if ($mode -eq 'child_failure') {'7'} else {'0'}
    $caught=$false
    try {RunUv @('-I','-B','-X','utf8',$nativeProbe,$childFile,$exit,($keys -join '|'))} catch {$caught=$true;if ($mode -ne 'child_failure') {throw}}
    $child=Get-Content -LiteralPath $childFile -Raw | ConvertFrom-Json
    $after=@{}
    foreach ($name in $keys) {
        $after[$name]=@{Exists=(Test-Path -LiteralPath ('Env:'+ $name));Value=[Environment]::GetEnvironmentVariable($name,'Process')}
        if ($child.$name.exists) {throw ('Native child inherited '+$name+' in '+$mode)}
        if ($before[$name].Exists -ne $after[$name].Exists -or $before[$name].Value -cne $after[$name].Value) {throw ('Parent existence/value restoration failed: '+$name+' in '+$mode)}
    }
    if (($mode -eq 'child_failure') -ne $caught) {throw 'Native child failure was not handled correctly'}
    $cases+=@{mode=$mode;status='PASS';parent_before=$before;parent_after=$after;child=$child;expected_failure_caught=$caught}
}
foreach ($name in $keys) {Remove-Item -LiteralPath ('Env:'+ $name) -ErrorAction SilentlyContinue}
@{status='PASS';powershell=$PSVersionTable.PSVersion.ToString();native_child=$Python;cases=$cases;installed=$false;gpu=$false;bootstrap_body_executed=$false}|ConvertTo-Json -Depth 8|Set-Content -LiteralPath $Output -Encoding UTF8
Write-Host ('PASS '+$PSVersionTable.PSVersion+' 4 actual native-child cases')
