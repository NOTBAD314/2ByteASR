import subtitle_core


def test_adjacent_spoken_amounts_stay_chinese_and_are_never_added_together():
    assert subtitle_core.normalize_output_text("哎三万三万最后一本两万救一下") == (
        "哎三万三万最后一本两万救一下"
    )
    assert subtitle_core.normalize_output_text("又来个二十万十万") == "又来个二十万十万"
    assert subtitle_core.normalize_output_text(
        "第二本刮完赚二十二万十万九万九万十一万十万"
    ) == "第二本刮完赚二十二万十万九万九万十一万十万"


def test_single_compound_amount_avoids_arabic_chinese_hybrid():
    assert subtitle_core.normalize_output_text("三百二十万") == "三百二十万"
    assert subtitle_core.normalize_output_text("三亿五千万") == "三亿五千万"


def test_cleanup_keeps_number_spelling_until_explicit_formatting_stage():
    from twobyteasr.subtitle_rules.number_fidelity import format_numbers
    assert subtitle_core.normalize_output_text("这1万多威力吗") == "这1万多威力吗"
    assert subtitle_core.normalize_output_text("这百分之1万有问题") == "这百分之1万有问题"
    assert subtitle_core.normalize_output_text("十六层毒") == "十六层毒"
    assert format_numbers("威力加四十")[0] == "威力加40"
    assert format_numbers("回复十二生命值")[0] == "回复12生命值"
    assert format_numbers("威力加四十",enabled=False)[0] == "威力加四十"


def test_cleanup_does_not_force_small_countdown_numbers_to_digits():
    assert subtitle_core.normalize_output_text("十九八") == "十九八"
    assert subtitle_core.normalize_output_text("倒计时十九八开始") == "倒计时十九八开始"


def test_ten_second_boarding_term_uses_the_live_membership_character():
    assert subtitle_core.normalize_output_text("十秒内不上剑给你号刮完") == (
        "十秒内不上舰给你号刮完"
    )
