from pathlib import Path
from scripts.check_release_payload import user_directory


def test_projects_source_package_is_shippable():
    assert not user_directory(Path('twobyteasr/projects/studio_project.py'))
    assert not user_directory(Path('twobyteasr/projects/__init__.py'))


def test_user_data_cannot_hide_in_or_beside_source_package():
    for name in ('Projects/user.2byteproj','Projects/user.py',
                 'twobyteasr/projects/private.txt','twobyteasr/projects/logs/output.py',
                 'twobyteasr/projects/__pycache__/studio_project.pyc','models/weights.bin'):
        assert user_directory(Path(name)),name
