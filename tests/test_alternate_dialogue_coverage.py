import ast,copy,math,re,sys,unittest
from pathlib import Path
from types import SimpleNamespace
BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE))
text=(BASE/'moss_firered_pipeline.py').read_text('utf8')
names={'apply_alternate_dialogue_coverage','_note_unchecked_other_speakers','select_host_speakers','_dialogue_coverage_mode','_trustworthy_dialogue_text','_time_overlap','alternate_dialogue_coverage_signature'}
nodes=[n for n in ast.parse(text).body if isinstance(n,ast.FunctionDef) and n.name in names]
constants={'_NON_SPEECH_ONLY_RE','MOSS_SPEAKER_PAD_SECONDS','MOSS_AUTO_MAX_HOST_SPEAKERS','MOSS_HOST_MIN_SPAN_RATIO','MOSS_HOST_MIN_ACTIVE_BIN_RATIO'}
constant_nodes=[n for n in ast.parse(text).body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in constants for t in n.targets)]
ns=dict(copy=copy,math=math,re=re)
exec(compile(ast.Module(body=constant_nodes,type_ignores=[]),'actual-production-constants','exec'),ns)
exec(compile(ast.Module(body=nodes,type_ignores=[]),'proposal-functions','exec'),ns)
apply=ns['apply_alternate_dialogue_coverage']
class Legacy:
    def __init__(self):self.events=[];self.review=[]
    def clean_subtitle_text(self,t):return str(t)
    def content_only(self,t):return ''.join(str(t).split())
    def best_alternate_window(self,t,c):return (t,1.) if t in c else ('',0.)
    def record_run_event(self,e,**kw):self.events.append(dict(event=e,**kw))
    def add_review_item(self,*a,**kw):self.review.append((a,kw))
class Guards(unittest.TestCase):
    def fixture(self,mode='host_priority'):
        l=Legacy();context=SimpleNamespace(dialogue_coverage_mode=mode,expected_speakers=1,speaker_recovery={'candidates':['D01','D02']})
        rows=[dict(start=0.,end=2.,text='持续对白甲',speaker='D01',confidence=None),dict(start=3.,end=5.,text='持续对白乙',speaker='D01',confidence=None),dict(start=6.,end=7.,text='短句角色',speaker='D02',confidence=None)]
        segments=[SimpleNamespace(segment_id=i+1,start=r['start'],end=r['end'],text=r['text'],speaker=r['speaker'],words=[{'text':r['text'],'start':r['start'],'end':r['end']}],caption_arbitration={'native_model_probability':None,'speaker_evidence':{'assignment':'DiariZen'}},primary_source='vibevoice_1_5b-primary',final_timing_owner='FireRed acoustic word alignment',timing_locked=False,confidence=0.) for i,r in enumerate(rows)]
        # One independent FireRed word: a second recognizer ran (2026-10-15).
        return segments,rows,[{'start':0,'end':2,'text':'持续对白甲'}],[{'start':0,'end':7}],l,context
    def run_filter(self,fixture,backend='vibevoice_1_5b'):
        s,r,t,v,l,c=fixture;return apply(s,r,t,v,10.,l,backend,c)
    def test_all_dialogue_objects_and_all_fields_unchanged(self):
        f=self.fixture('all_dialogue');before=copy.deepcopy(f[0]);out=self.run_filter(f)
        self.assertEqual(out,before);self.assertTrue(all(a is b for a,b in zip(out,f[0])))
        self.assertEqual(f[4].events[-1]['before_segments'],3);self.assertEqual(f[4].events[-1]['after_segments'],3)
    def test_host_priority_preserves_native_words_and_attribution_unknown_probability(self):
        f=self.fixture();before=copy.deepcopy(f[0][:2]);out=self.run_filter(f)
        self.assertEqual(out,before);self.assertEqual(len(out),2);self.assertTrue(out[0] is f[0][0])
        receipt=f[4].events[-1];self.assertEqual(receipt['host_labels'],['D01']);self.assertEqual(receipt['candidate_labels'],['D01','D02'])
        self.assertFalse(receipt['identity_confirmed']);self.assertTrue(receipt['needs_confirmation']);self.assertTrue(f[5].speaker_recovery['needs_confirmation'])
    def test_nonhost_independent_support_retained(self):
        f=self.fixture();f[2].append({'start':6,'end':7,'text':'短句角色'});out=self.run_filter(f)
        self.assertEqual(len(out),3);self.assertEqual(f[4].events[-1]['decisions'][-1]['reason'],'independent_firered_support')
    def test_host_priority_without_second_recognizer_keeps_and_lists_other_speakers(self):
        # 2026-10-15 MOSS Pro cloud-only: no FireRed, every other speaker was dropped.
        for tokens in ([], [{'start':6,'end':7,'text':'别的','source':'qwen-forced-aligner'}]):
            f=self.fixture();f[2][:]=tokens;out=self.run_filter(f)
            self.assertEqual([s.text for s in out],['持续对白甲','持续对白乙','短句角色'])
            receipt=f[4].events[-1]
            self.assertFalse(receipt['second_recognizer']);self.assertEqual(receipt['kept_unchecked'],1)
            self.assertEqual(receipt['decisions'][-1]['reason'],'kept_without_second_recognizer')
            self.assertIn('其他说话人未核对',[item[0][1] for item in f[4].review])
        f=self.fixture('host_only');f[2][:]=[];self.assertEqual(len(self.run_filter(f)),2)
    def test_host_only_does_not_keep_supported_nonhost(self):
        f=self.fixture('host_only');f[2].append({'start':6,'end':7,'text':'短句角色'});self.assertEqual(len(self.run_filter(f)),2)
    def test_same_trustworthy_rule_drops_vad_empty_or_known_low_confidence(self):
        f=self.fixture();f[3][:]=[{'start':3,'end':7}];out=self.run_filter(f);self.assertEqual([s.text for s in out],['持续对白乙'])
        f=self.fixture();f[1][0]['confidence']=.1;out=self.run_filter(f,'moss');self.assertEqual([s.text for s in out],['持续对白乙'])
    def test_single_label_truthful_noop_receipt(self):
        f=self.fixture();f[1][:]=f[1][:1];f[0][:]=f[0][:1];self.assertEqual(len(self.run_filter(f)),1)
        e=f[4].events[-1];self.assertTrue(e['executed']);self.assertEqual(e['before_segments'],e['after_segments']);self.assertFalse(e['identity_confirmed'])
    def test_empty_or_mismatch_never_silent_all_dialogue_success(self):
        f=self.fixture();f[3][:]=[]
        with self.assertRaisesRegex(RuntimeError,'全部对白'):self.run_filter(f)
        self.assertEqual(f[4].events[-1]['after_segments'],0)
        f=self.fixture();f[1].pop()
        with self.assertRaisesRegex(RuntimeError,'证据数量'):self.run_filter(f)
        f=self.fixture();f[1][0]['text']='错误对应文字'
        with self.assertRaisesRegex(RuntimeError,'文字或时间'):self.run_filter(f)
    def test_stable_coverage_signature_in_primary_group_and_final_cache(self):
        f=self.fixture();signature=ns['alternate_dialogue_coverage_signature']
        first=signature('vibevoice_1_5b','native',f[5],f[4])
        self.assertEqual(first,signature('vibevoice_1_5b','native',f[5],f[4]))
        f[5].dialogue_coverage_mode='all_dialogue'
        self.assertNotEqual(first,signature('vibevoice_1_5b','native',f[5],f[4]))
        f[5].expected_speakers=2
        self.assertNotEqual(first,signature('vibevoice_1_5b','native',f[5],f[4]))
        self.assertEqual(signature('moss','moss',f[5],f[4]),{})
        self.assertIn('primary_dependency.update(alternate_coverage_signature)',text)
        self.assertEqual(text.count('**alternate_coverage_signature'),2)
        self.assertNotIn('pid',str(first));self.assertNotIn('job',str(first))

    def test_diarizen_identity_primary_moss_and_label_source_are_separate(self):
        import contextlib,io
        f=self.fixture();f[5].speaker_source='diarizen'
        buffer=io.StringIO()
        with contextlib.redirect_stdout(buffer):out=self.run_filter(f,'moss')
        e=f[4].events[-1]
        self.assertEqual(e['primary_backend'],'moss');self.assertEqual(e['speaker_backend'],'diarizen')
        self.assertIn('label_source=DiariZen v2',buffer.getvalue());self.assertNotIn('label_source=moss',buffer.getvalue())
        self.assertEqual(out[0].speaker,'D01');self.assertEqual(out[0].caption_arbitration['speaker_evidence']['assignment'],'DiariZen')
        self.assertEqual(f[5].speaker_recovery['coverage_filter']['speaker_backend'],'diarizen')

    def test_final_recovery_refresh_keeps_coverage_receipt_and_confirmation(self):
        f=self.fixture();segments=self.run_filter(f);context=f[5]
        context.speaker_recovery['raw_segments']=copy.deepcopy(f[1])
        before=copy.deepcopy(context.speaker_recovery['coverage_filter'])
        tree=ast.parse(text);fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and any(isinstance(x,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='coverage_filter' for t in x.targets) for x in n.body))
        start=next(i for i,n in enumerate(fn.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='coverage_filter' for t in n.targets))
        from twobyteasr.speaker_recovery import candidate_snapshot
        scope=dict(copy=copy,runtime_context=context,segments=segments,primary_backend='vibevoice_1_5b',speaker_mode='native',speaker_processing={'status':'native','backend':'native'},legacy=f[4],candidate_snapshot=candidate_snapshot)
        exec(compile(ast.Module(body=fn.body[start:start+3],type_ignores=[]),'real-final-refresh','exec'),scope)
        self.assertEqual(context.speaker_recovery['coverage_filter'],before)
        self.assertTrue(context.speaker_recovery['needs_confirmation'])
        self.assertEqual(context.speaker_recovery['processing']['backend'],'native')

    def test_actual_pipeline_call_outside_cache_and_no_moss_restore_activation(self):
        tree=ast.parse(text);function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='apply_alternate_dialogue_coverage')
        source=ast.get_source_segment(text,function)
        self.assertNotIn('run_optional',source);self.assertNotIn('build_moss_host',source);self.assertNotIn('moss_payload',source)
        self.assertEqual(text.count('segments = apply_alternate_dialogue_coverage('),1)
        self.assertIn("if not (primary_backend == \"moss\" and speaker_mode == \"moss\"):",text)
        self.assertIn("moss_payload['host_speakers']=[]",text)
if __name__=='__main__':unittest.main()

