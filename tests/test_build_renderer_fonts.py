"""Browser font resources are required before packaging starts."""
import importlib.util,json,hashlib
from pathlib import Path
import pytest
SPEC=importlib.util.spec_from_file_location('release_font_preflight',Path(__file__).resolve().parents[1]/'scripts/build_release.py')
module=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(module)

def fixture(tmp_path,data=None):
    (tmp_path/'packaging').mkdir();(tmp_path/'renderer/public/fonts').mkdir(parents=True)
    (tmp_path/'packaging/renderer_fonts.json').write_text(json.dumps({'fonts':[{'file':'sample.otf','sha256':hashlib.sha256(b'correct').hexdigest()}]}))
    if data is not None:(tmp_path/'renderer/public/fonts/sample.otf').write_bytes(data)
    return tmp_path

def test_missing_font_fails_before_build(tmp_path):
    with pytest.raises(ValueError,match='sample.otf'):module.validate_renderer_fonts(fixture(tmp_path))

def test_corrupt_font_fails_before_build(tmp_path):
    with pytest.raises(ValueError,match='sample.otf'):module.validate_renderer_fonts(fixture(tmp_path,b'wrong'))

def test_pinned_font_passes(tmp_path):
    module.validate_renderer_fonts(fixture(tmp_path,b'correct'))

def test_all_web_font_faces_are_in_contract():
    import re
    root=Path(__file__).resolve().parents[1]
    required=set(re.findall(r"\['([^']+\.(?:ttf|otf|woff2))'",(root/'renderer/src/webThemeFonts.ts').read_text('utf8')))
    pinned={item['file'] for item in json.loads((root/'packaging/renderer_fonts.json').read_text('utf8'))['fonts']}
    assert len(required)==7 and required<=pinned
    module.validate_renderer_fonts(root)

def test_font_contract_is_distributed():
    root=Path(__file__).resolve().parents[1]
    assert "datas.append((str(ROOT / 'packaging/renderer_fonts.json'), 'packaging'))" in (root/'packaging/2byteasr_main.spec').read_text('utf8')


def test_public_renderer_tone_survives_media_filter_without_user_recordings():
    assert module.release_input_allowed(Path('renderer/node_modules/@remotion/studio-server/web/beep.wav'))
    for relative in ('renderer/user-recording.wav', 'assets/beep.wav', 'models/private.pt', 'secrets.json'):
        assert not module.release_input_allowed(Path(relative))


def test_public_renderer_tone_requires_exact_bytes(tmp_path):
    import shutil
    root=Path(__file__).resolve().parents[1]
    relative=next(iter(module.PUBLIC_RENDERER_AUDIO));target=tmp_path/relative
    target.parent.mkdir(parents=True);shutil.copy2(root/relative,target)
    module.validate_renderer_audio(tmp_path)
    target.write_bytes(b'private recording')
    with pytest.raises(ValueError,match='checksum mismatch'):module.validate_renderer_audio(tmp_path)
    target.unlink()
    with pytest.raises(ValueError,match='missing'):module.validate_renderer_audio(tmp_path)


def test_payload_scanner_uses_the_same_public_audio_pin():
    root=Path(__file__).resolve().parents[1]
    spec=importlib.util.spec_from_file_location('payload_media_preflight',root/'scripts/check_release_payload.py')
    scanner=importlib.util.module_from_spec(spec);spec.loader.exec_module(scanner)
    assert scanner.PUBLIC_RENDERER_AUDIO==module.PUBLIC_RENDERER_AUDIO
