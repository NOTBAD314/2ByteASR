from twobyteasr.diagnostics import playback_probe as probe

def test_runtime_capture_enables_existing_decorators_and_restores():
    old=probe.configure(enabled=False)
    class Owner:
        @probe.measured('apply_playhead')
        def call(self):return 42
    instance=Owner();before=probe.counters()['recorded'];assert instance.call()==42
    assert probe.counters()['recorded']==before
    token=probe.configure(enabled=True,light=True)
    assert instance.call()==42
    assert probe.counters()['recorded']==before+1
    assert probe.restore(token)
    instance.call();assert probe.counters()['recorded']==before+1
    probe.configure(enabled=old[1][0],light=old[1][1])

def test_old_capture_cannot_disable_newer_capture():
    one=probe.configure(enabled=True)
    two=probe.configure(enabled=True,light=False)
    assert not probe.restore(one)
    assert probe.counters()['enabled'] and not probe.LIGHT
    probe.restore(two)
    probe.configure(enabled=False)
