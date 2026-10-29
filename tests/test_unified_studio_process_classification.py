from twobyteasr.acceptance.unified_studio_audit import classify_export_invocation


def test_actual_media_tools_with_non_remotion_output_paths_are_not_rejected():
    result=classify_export_invocation([
        r'C:\tools\ffmpeg\bin\ffmpeg.exe','-i',
        r'C:\tmp\workspaces\non-remotion-proof\woodcut.mov',
        r'C:\tmp\exports\non-remotion-studio-composed.mp4'])
    assert result['accepted'] and result['naive_remotion_substring']
    assert not result['runtime'] and not result['remotion_helper'] and not result['remotion_package']


def test_ffprobe_also_accepts_harmless_output_name():
    assert classify_export_invocation(['C:/tools/ffprobe.exe','non-remotion-studio-composed.mp4'])['accepted']


def test_actual_node_runtime_rejected_even_without_remotion_word():
    result=classify_export_invocation(['C:/tools/node.exe','C:/render/render.js'])
    assert result['runtime'] and not result['accepted']


def test_actual_remotion_package_media_binary_rejected():
    result=classify_export_invocation([
        'C:/renderer/node_modules/@remotion/compositor-win32-x64-msvc/ffmpeg.exe','out.mp4'])
    assert result['remotion_package'] and not result['accepted']


def test_compositor_is_rejected_without_package_path():
    result=classify_export_invocation(['C:/tools/compositor.exe','out.mp4'])
    assert result['remotion_helper'] and not result['accepted']


def test_unknown_tool_and_missing_invocation_fail_closed():
    assert not classify_export_invocation(['C:/custom/transcoder.exe'])['accepted']
    assert not classify_export_invocation([])['accepted']
