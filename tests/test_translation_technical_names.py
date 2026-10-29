import pytest
from twobyteasr.subtitle_rules.subtitle_translation import validate_translation


@pytest.mark.parametrize('source,translation', [
    ("from a Blackmagic Pocket Cinema Camera Something that's important to know about ACES",
     '来自 Blackmagic Pocket Cinema Camera，有关 ACES 需要注意'),
    ('S-Log3 S-Gamut3 Cine color space', 'S-Log3 S-Gamut3 Cine 色彩空间'),
    ('to us here in Resolve Resolve Color Management V2 which we can access', '在 Resolve 中可以使用 Resolve Color Management V2'),
    ('and not one of my ACES flavors but DaVinci YRGB Color Managed', '选择 DaVinci YRGB Color Managed，而非 ACES'),
    ("up I'm going to go to DaVinci Wide Gamut", '接下来选择 DaVinci Wide Gamut'),
    ("of DaVinci Wide Gamut Intermediate unless you're more experienced", '使用 DaVinci Wide Gamut Intermediate，除非你更有经验'),
])
def test_chinese_with_source_technical_names_is_not_rejected(source, translation):
    assert validate_translation(source, translation, 'zh-Hans', 'en') is None


def test_source_name_can_remain_english_but_sentences_cannot():
    assert validate_translation('DaVinci Wide Gamut', 'DaVinci Wide Gamut', 'zh-Hans', 'en') is None
    source = 'We need to grab the shield first'
    assert validate_translation(source, source, 'zh-Hans', 'en') == 'echo_source'
    assert validate_translation(source, '中文 ' + source, 'zh-Hans', 'en') == 'english_output'
    uppercase = 'WE NEED TO GET READY FOR THE NEXT CLIP'
    assert validate_translation(uppercase, '中文 ' + uppercase, 'zh-Hans', 'en') == 'english_output'
    title_case = 'We Need To Grab The Shield First'
    assert validate_translation(title_case, '中文 ' + title_case, 'zh-Hans', 'en') == 'english_output'
