"""r3 mouse/menu/file-dialog acceptance. No production controllers are injected."""
import copy,json,os,time,traceback
from PySide6.QtCore import QTimer,Qt,QPoint,QRect
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import QApplication,QFileDialog,QLineEdit,QMenu,QToolButton
from PySide6.QtTest import QTest

def start(window,out):
 page=window.studio_page;timeline=page.timeline
 config=json.loads((out/'audit-config.json').read_text('utf8'))
 phase=os.environ.get('TWOBYTEASR_USER_FEEDBACK_PHASE','exercise')
 result=dict(passed=False,checks={},pid=os.getpid(),phase=phase,input_method='QTest normal widgets and context-menu event',real_user_click=False)
 from .build_identity import load_build_identity
 result['identity']=load_build_identity().to_dict()
 def pump(seconds):
  until=time.monotonic()+seconds
  while time.monotonic()<until:QApplication.processEvents();QTest.qWait(10)
 def check(name,value):
  result['checks'][name]=bool(value)
  if not value:raise AssertionError(name)
 def wait(predicate,label,timeout=15):
  until=time.monotonic()+timeout
  while not predicate() and time.monotonic()<until:pump(.05)
  check(label,predicate())
 def click(widget):QTest.mouseClick(widget,Qt.LeftButton);pump(.15)
 def toolbar(text):click(next(w for w in page.findChildren(QToolButton) if w.toolTip()==text));pump(.5)
 def snapshot(name,native=False):
  pump(.2);window.grab().save(str(out/(name+'-qt.png')))
  timeline.grab(QRect(0,0,timeline.TRACK_HEADER_WIDTH,timeline.height())).save(str(out/(name+'-headers.png')))
  if native:
   from .processes import run_hidden_subprocess
   from .runtime_paths import detect_install_root
   run_hidden_subprocess([detect_install_root()/'tools/ffmpeg/bin/ffmpeg.exe','-v','error','-f','lavfi','-i',
    f'gfxcapture=hwnd={int(window.winId())}:max_framerate=10:capture_cursor=0','-vf','hwdownload,format=bgra','-frames:v','1','-y',out/(name+'-native.png')],
    timeout=10,purpose='r3 actual window screenshot')
 def header(kind,tid,action):
  from .studio_track_header import button_rect
  rect=(timeline._video_track_rects() if kind=='video' else timeline._audio_track_rects())[tid]
  QTest.mouseClick(timeline,Qt.LeftButton,pos=button_rect(kind,action,rect).center().toPoint());pump(.3)
 def clip_point(track_id,index=0):
  track=next(t for t in page.project.video_tracks if t.id==track_id);clip=track.clips[index]
  return QPoint(round(timeline._time_to_x(clip.timeline_in_ms+400)),round(timeline._video_track_rect(track_id).center().y()))
 def context(track_id,action_text=None,after=None):
  point=clip_point(track_id);QTest.mouseClick(timeline,Qt.LeftButton,pos=point);pump(.15)
  def choose():
   try:
    menu=QApplication.activePopupWidget();check('actual_context_menu',isinstance(menu,QMenu))
    result.setdefault('menus',[]).append([a.text() for a in menu.actions()])
    check('video_menu_has_no_audio_actions',not any(any(x in a.text() for x in ('音量','恢复声音','静音','独奏')) for a in menu.actions()))
    menu.grab().save(str(out/('menu-'+str(len(result['menus']))+'.png')))
    if action_text:
     action=next(a for a in menu.actions() if a.text()==action_text);check('menu_action_enabled',action.isEnabled())
     if after:QTimer.singleShot(250,after)
     QTest.mouseClick(menu,Qt.LeftButton,pos=menu.actionGeometry(action).center())
    else:QTest.keyClick(menu,Qt.Key_Escape)
   except Exception:
    result['callback_error']=traceback.format_exc()
    popup=QApplication.activePopupWidget()
    if popup:popup.close()
  QTimer.singleShot(120,choose)
  QApplication.sendEvent(timeline,QContextMenuEvent(QContextMenuEvent.Mouse,point,timeline.mapToGlobal(point)))
  if result.get('callback_error'):raise AssertionError(result['callback_error'])
 def choose_file(cancel=False):
  dialog=next(w for w in QApplication.topLevelWidgets() if isinstance(w,QFileDialog) and w.isVisible())
  result.setdefault('dialogs',[]).append(dict(title=dialog.windowTitle(),directory=dialog.directory().absolutePath(),cancel=cancel))
  dialog.grab().save(str(out/('file-dialog-cancel.png' if cancel else 'file-dialog.png')))
  if cancel:QTest.keyClick(dialog,Qt.Key_Escape);return
  field=dialog.findChild(QLineEdit,'fileNameEdit');clipboard=QApplication.clipboard();old=clipboard.text()
  clipboard.setText(config['relink_path']);QTest.mouseClick(field,Qt.LeftButton);QTest.keyClick(field,Qt.Key_A,Qt.ControlModifier)
  QTest.keyClick(field,Qt.Key_V,Qt.ControlModifier);clipboard.setText(old);QTest.keyClick(field,Qt.Key_Return)
 def run():
  started=time.monotonic()
  try:
   wait(lambda:page._readiness.ready,'normal_window_ready',30)
   window.showMaximized();window.raise_();window.activateWindow();page.video.set_paused(True)
   page.workspace_splitter.setSizes([260,700]);timeline.vertical_scrollbar.setValue(0);pump(1)
   if phase=='reopen':
    expected=json.loads((out/'expected.json').read_text('utf8'))
    check('reopen_ids_and_order',[t.id for t in page.project.video_tracks]==expected['video_ids'] and [t.id for t in page.project.audio_tracks]==expected['audio_ids'])
    check('reopen_linked_source',next(a for a in page.project.media_pool if a.asset_id==config['offline_asset_id']).canonical_source==config['relink_path'])
    check('reopen_preserves_three_subtitles',len(page.project.cues)==3)
    snapshot('reopened',True);result['passed']=True;return
   wait(lambda:any(a.offline for a in page.project.media_pool),'offline_detected')
   from .studio_track_header import ACTIONS,button_rect
   rows=[('subtitle',tid,r) for tid,r in timeline._track_layout()[0].items()]+[('video',tid,r) for tid,r in timeline._video_track_rects().items()]+[('audio',tid,r) for tid,r in timeline._audio_track_rects().items()]
   result['geometry']=dict(dpr=timeline.devicePixelRatioF(),window=[window.width(),window.height()],rows=[dict(kind=k,id=tid,row=[r.x(),r.y(),r.width(),r.height()],buttons=[dict(action=a,rect=[button_rect(k,a,r).x(),button_rect(k,a,r).y(),24,24]) for a in ACTIONS[k]]) for k,tid,r in rows])
   check('all_nine_headers_visible',len(rows)==9 and all(r.top()>=timeline.RULER_HEIGHT and r.bottom()<=timeline.height() for _,_,r in rows))
   check('three_column_centers',all([button_rect(k,a,r).center().x() for a in ACTIONS[k]]==[152,180,208] for k,_,r in rows))
   snapshot('aligned-all-headers',True)
   before=copy.deepcopy((page.project.video_tracks,page.project.audio_tracks,page.project.av_track_groups,page.project.cues))
   QApplication.setAttribute(Qt.AA_DontUseNativeDialogs,True)
   index=page.undo_stack.index();context('V3','重新链接素材…',lambda:choose_file(True))
   check('file_cancel_no_mutation',page.undo_stack.index()==index and (page.project.video_tracks,page.project.audio_tracks,page.project.av_track_groups,page.project.cues)==before)
   context('V3','重新链接素材…',choose_file)
   wait(lambda:next(a for a in page.project.media_pool if a.asset_id==config['offline_asset_id']).canonical_source==config['relink_path'],'relink_completed')
   check('relink_preserves_all_edits',(page.project.video_tracks,page.project.audio_tracks,page.project.av_track_groups,page.project.cues)==before)
   wait(lambda:timeline.waveform_cache_for_source(config['relink_path']) is not None,'relink_waveform_ready',30)
   pump(1)
   snapshot('relinked',True)
   toolbar('撤销 (Ctrl+Z)');check('relink_undo_offline',next(a for a in page.project.media_pool if a.asset_id==config['offline_asset_id']).offline)
   toolbar('重做 (Ctrl+Y)');wait(lambda:not next(a for a in page.project.media_pool if a.asset_id==config['offline_asset_id']).offline,'relink_redo_online')
   wait(lambda:timeline.waveform_cache_for_source(config['relink_path']) is not None,'redo_waveform_ready',30)
   before=copy.deepcopy((page.project.video_tracks,page.project.audio_tracks,page.project.av_track_groups,page.project.cues))
   context('V3','删除视频片段');pump(.6)
   check('last_clip_removes_both_rows',not any(t.id=='V3' for t in page.project.video_tracks) and not any(t.id=='A3' for t in page.project.audio_tracks))
   snapshot('last-clip-deleted',True)
   toolbar('撤销 (Ctrl+Z)');check('one_undo_restores_full_group',(page.project.video_tracks,page.project.audio_tracks,page.project.av_track_groups,page.project.cues)==before)
   toolbar('重做 (Ctrl+Y)');check('delete_redo',len(page.project.video_tracks)==2 and len(page.project.audio_tracks)==2);toolbar('撤销 (Ctrl+Z)')
   remaining=copy.deepcopy(page.project.video_tracks[1].clips[1]);context('V2','删除视频片段');pump(.4)
   check('nonlast_keeps_lane_and_position',page.project.video_tracks[1].clips==[remaining] and remaining.timeline_in_ms==6000)
   toolbar('撤销 (Ctrl+Z)')
   header('video','V3','locked');QTest.mouseClick(timeline,Qt.LeftButton,pos=clip_point('V3'));QTest.keyClick(timeline,Qt.Key_Delete);pump(.3)
   check('locked_pair_not_half_deleted',len(page.project.video_tracks)==3 and len(page.project.audio_tracks)==3)
   header('video','V3','locked')
   # Actual A controls, shared graph and video visibility remain independent.
   from .audio_graph import capture_audio_graph,preview_audio_layers
   sound=lambda:{l['track_id'] for l in preview_audio_layers(capture_audio_graph(page.project),1000)}
   check('default_mix_one_source_per_group',sound()=={'V1','V2','V3'})
   header('video','V3','enabled');check('eye_keeps_audio',sound()=={'V1','V2','V3'})
   header('audio','A3','solo');check('solo_only_sound',sound()=={'V3'} and len(page.project.cues)==3)
   header('audio','A3','muted');check('mute_wins',sound()==set())
   header('audio','A3','muted');header('audio','A3','solo');header('video','V3','enabled')
   check('mix_restored',sound()=={'V1','V2','V3'})
   QTest.mouseClick(timeline,Qt.LeftButton,pos=clip_point('V3'));QTest.keyClick(timeline,Qt.Key_G);pump(.4)
   dialog=getattr(page,'_track_gain_dialog',None)
   check('gain_shortcut_opens_audio_dialog',dialog is not None and dialog.isVisible())
   from PySide6.QtWidgets import QComboBox
   check('gain_shortcut_targets_linked_a3',dialog.findChild(QComboBox,'gainTrack').currentData()=='A3')
   QTest.keyClick(dialog,Qt.Key_Escape);pump(.4)
   click(page.save_button);wait(page.undo_stack.isClean,'saved')
   (out/'expected.json').write_text(json.dumps(dict(video_ids=[t.id for t in page.project.video_tracks],audio_ids=[t.id for t in page.project.audio_tracks])),'utf8')
   snapshot('final',True);result['passed']=True
  except Exception:result['error']=traceback.format_exc()
  finally:
   result['elapsed_seconds']=time.monotonic()-started
   (out/(phase+'-result.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf8')
   page.undo_stack.setClean();QTimer.singleShot(200,window.close)
 QTimer.singleShot(400,run)
