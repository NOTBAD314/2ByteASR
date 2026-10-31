"""Different subtitle texts reuse a bounded, thread-owned FreeType face."""
import threading
from concurrent.futures import ThreadPoolExecutor
from twobyteasr.caption_style.resolved_caption_style import _measurement_font, _MEASUREMENT_FONTS
from twobyteasr.caption_style.font_metadata import resolve_local_face


def test_font_face_reused_across_texts_and_size_cache_is_bounded():
    face, _ = resolve_local_face('Source Han Sans SC Heavy')
    _MEASUREMENT_FONTS.faces = __import__('collections').OrderedDict()
    font = _measurement_font(face.file, 1000, face.index)
    assert _measurement_font(face.file,1000,face.index) is font
    for size in range(40,48):
        _measurement_font(face.file,size,face.index)
    assert len(_MEASUREMENT_FONTS.faces)==4


def test_freetype_objects_are_not_shared_between_measurement_threads():
    face, _ = resolve_local_face('Source Han Sans SC Heavy')
    barrier = threading.Barrier(2)
    def read():
        font = _measurement_font(face.file,1000,face.index)
        barrier.wait(5)
        return font, font.getlength('Test italiano 测试')
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(lambda _:read(), range(2)))
    assert first[0] is not second[0] and first[1] == second[1]
