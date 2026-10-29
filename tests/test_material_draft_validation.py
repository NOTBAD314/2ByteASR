from twobyteasr.caption_design.theme_draft import _caption_runs,_bound_text_phases


def test_decorative_copies_are_not_the_reading_text():
    primary={'text':'主字幕','opacity':1,'rect':[300,560,600,80]}
    ghost={'text':'主字幕','opacity':0,'rect':[300,560,600,80]}
    assert _caption_runs({'semantic_text_runs':[primary],'text_runs':[primary,ghost]},'主字幕')==[primary]
    assert _caption_runs({'semantic_text_runs':[],'text_runs':[ghost]},'主字幕')==[]
    # A genuinely hidden primary is preserved so the visibility gate rejects it.
    assert _caption_runs({'semantic_text_runs':[ghost]},'主字幕')[0]['opacity']==0


def test_gsap_requires_actual_text_targets_in_both_phases():
    rows=[{'phase':'build','start':0,'end':.5,'targets':1,'affects_text':True},
          {'phase':'resolve','start':2.7,'end':3,'targets':1,'affects_text':True}]
    details={'motion_map':rows,'timelines':[{'paused':True,'duration':3}],'animations':[]}
    assert _bound_text_phases(details,True)==(True,True,True)
    rows[1]['affects_text']=False
    assert _bound_text_phases(details,True)==(True,False,True)
    rows[0]['targets']=0
    assert _bound_text_phases(details,True)==(False,False,False)


def test_legacy_css_motion_remains_valid_and_static_source_fails():
    details={'animations':[{'cue':True,'affects_text':True,'iterations':1,'end':400,'delay':0},
                           {'cue':True,'affects_text':True,'iterations':1,'end':3000,'delay':2700}]}
    assert _bound_text_phases(details,False)==(True,True,True)
    assert _bound_text_phases({'animations':[]},False)==(False,False,False)
