from twobyteasr.app.home_studio_entry import latest_studio_entry


def test_latest_available_and_relative_or_generated_cover(tmp_path):
    project = tmp_path/'sample.2byteproj'
    project.write_text('{}')
    record = {'path': str(project), 'cover_path': 'preview/custom.png'}
    assert latest_studio_entry([{'path': str(tmp_path/'moved')}, record]) == (
        'sample', str(tmp_path/'preview/custom.png'))
    (tmp_path/'preview').mkdir()
    (tmp_path/'preview/project-cover.jpg').write_bytes(b'fixture')
    assert latest_studio_entry([record])[1] == str(tmp_path/'preview/project-cover.jpg')
    assert latest_studio_entry([str(project)])[0] == 'sample'


def test_missing_and_invalid_recent_records_do_not_keep_a_cover(tmp_path):
    assert latest_studio_entry(None) == ('', '')
    assert latest_studio_entry([{}, {'path': str(tmp_path/'missing')}]) == ('', '')
