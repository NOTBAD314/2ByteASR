from twobyteasr.caption_style.caption_text_layout import normalized_caption_text,wrap_caption_text


def test_explicit_blank_lines_and_literal_ass_escape_are_preserved():
    source='第一行\r\n\r\n第二行\u2028第三行\\N'
    result=wrap_caption_text(source,lambda text:len(text)*10,1000)
    assert result.text=='第一行\n\n第二行\n第三行\\N'
    assert len(result.lines)==4 and not result.overflow


def test_soft_wrap_keeps_all_characters_and_never_changes_measured_size():
    text='只要打PVP顺手就给他做完了'
    calls=[]
    def measure(value):calls.append(value);return sum(90 if char.isascii() else 180 for char in value)
    result=wrap_caption_text(text,measure,1814)
    assert len(result.lines)==2 and max(result.widths)<=1814
    assert ''.join(result.lines)==text and not result.overflow
    assert calls


def test_combining_and_zwj_sequences_are_not_split():
    result=wrap_caption_text('A\u0301B👩\u200d💻C',lambda value:len(value.replace('\u200d',''))*10,20)
    assert ''.join(result.lines)=='A\u0301B👩\u200d💻C'
    assert all(not line.startswith('\u0301') and not line.startswith('\u200d') for line in result.lines)
    assert any('👩\u200d💻' in line for line in result.lines)


def test_overwide_grapheme_is_reported_in_full_instead_of_clipped():
    result=wrap_caption_text('AB',lambda value:len(value)*200,100)
    assert result.lines==('AB',) and result.overflow


def test_long_compound_and_combined_characters_wrap_without_new_timed_cues():
    text="L'e\u0301quipe dell'America\nDonaudampfschifffahrtsgesellschaftskapitän\n🇮🇹 👨‍👩‍👧‍👦"
    result=wrap_caption_text(text,lambda value:len(value)*10,70)
    assert 'Donaudampfschifffahrtsgesellschaftskapitän' in result.lines
    assert ''.join(result.lines)==text.replace('\n','')
    assert not any(line.startswith('\u0301') or line.startswith('\u200d') for line in result.lines)
    assert result.overflow
