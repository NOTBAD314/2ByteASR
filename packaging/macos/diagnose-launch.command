#!/bin/bash
# Optional pre-Python diagnostic. Does not remove quarantine or change trust.
set -u
here=$(cd -- "$(dirname -- "$0")" && pwd)
app=${1:-"$here/2ByteASR.app"}
if [ ! -d "$app" ]; then app='/Applications/2ByteASR.app'; fi
if [ -n "${TWOBYTEASR_TEST_ROOT:-}" ]; then
  logs="$TWOBYTEASR_TEST_ROOT/logs"
else
  logs="$HOME/Library/Application Support/2ByteASR/logs"
fi
mkdir -p -- "$logs"
log="$logs/macos-before-python-$(date +%Y%m%d-%H%M%S).log"
{
  printf 'stage=pre_python\n'
  /usr/bin/sw_vers
  /usr/bin/uname -m
  /usr/sbin/sysctl -in sysctl.proc_translated 2>/dev/null || true
  /usr/sbin/sysctl -in hw.optional.arm64 2>/dev/null || true
  /usr/libexec/PlistBuddy -c 'Print :LSMinimumSystemVersion' "$app/Contents/Info.plist"
  /usr/bin/codesign --verify --deep --strict "$app"
  /usr/sbin/spctl --assess --type execute --verbose "$app"
  printf '\nstage=launch\n'
  "$app/Contents/MacOS/2ByteASR"
  result=$?
  printf '\nlauncher_exit_code=%s\n' "$result"
} >"$log" 2>&1
printf '诊断已保存：%s\n' "$log"
printf '此脚本没有更改签名、公证或隔离属性。\n'
