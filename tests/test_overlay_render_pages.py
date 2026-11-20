from twobyteasr.rendering.advanced_renderer import overlay_render_pages

GB = 1024**3


def test_pages_follow_cores_and_free_memory():
    assert overlay_render_pages(1920, 1080, cores=12, available_bytes=32*GB) == 4
    assert overlay_render_pages(1920, 1080, cores=6, available_bytes=32*GB) == 3
    assert overlay_render_pages(1920, 1080, cores=12, available_bytes=6.5*GB) == 3
    # 4K pages are heavier.
    assert overlay_render_pages(3840, 2160, cores=12, available_bytes=12*GB) == 2


def test_never_below_original_two_pages():
    assert overlay_render_pages(1920, 1080, cores=2, available_bytes=1*GB) == 2
    assert overlay_render_pages(None, None, cores=1, available_bytes=0) == 2
