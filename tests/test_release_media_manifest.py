import hashlib,json
from scripts import check_release_hygiene as hygiene


def test_only_exact_public_demo_bytes_are_approved(tmp_path,monkeypatch):
    monkeypatch.setattr(hygiene,'ROOT',tmp_path)
    folder=tmp_path/'examples/web-themes';folder.mkdir(parents=True)
    video=folder/'demo.mp4';video.write_bytes(b'synthetic fixture')
    manifest={'files':[{'path':'examples/web-themes/demo.mp4','bytes':video.stat().st_size,
        'sha256':hashlib.sha256(video.read_bytes()).hexdigest()}]}
    (folder/'release-media.json').write_text(json.dumps(manifest),'utf8')
    errors=[];assert hygiene.approved_example_media(errors)=={'examples/web-themes/demo.mp4'} and not errors
    video.write_bytes(b'changed fixture')
    assert hygiene.approved_example_media(errors)==set() and errors


def test_public_demo_manifest_cannot_authorize_an_outside_file(tmp_path,monkeypatch):
    monkeypatch.setattr(hygiene,'ROOT',tmp_path)
    folder=tmp_path/'examples/web-themes';folder.mkdir(parents=True)
    (folder/'release-media.json').write_text(json.dumps({'files':[{'path':'../outside.mp4'}]}),'utf8')
    errors=[];assert hygiene.approved_example_media(errors)==set() and errors
