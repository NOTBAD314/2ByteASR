"""Headed Qt task-state/transport evidence on an isolated Windows desktop."""
import argparse
import copy
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--child',action='store_true')
    args=parser.parse_args();out=args.output.resolve()
    if not out.is_relative_to(ROOT/'tmp'):raise ValueError('Evidence must stay under tmp')
    out.mkdir(parents=True,exist_ok=True)
    if not args.child:
        from isolated_windows_desktop import run_on_desktop
        env=dict(os.environ,TWOBYTEASR_TEST_ROOT=str(out/'isolation'),QT_QPA_PLATFORM='windows',PYTHONIOENCODING='utf-8')
        return run_on_desktop([sys.executable,__file__,'--output',str(out),'--child'],cwd=ROOT,env=env,output=out/'process',timeout=90)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out/'isolation')
    from twobyteasr.test_isolation import install
    install()
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt
    from twobyteasr.theme_concept_dialog import ThemeConceptDialog
    from twobyteasr.theme_manager import apply_theme
    app=QApplication([]);apply_theme('grape',app)
    concept=dict(id='A',name='王国之泪 · 环纹方向',pending=True,technical_status='pending',composition='测试夹具：用于验证进度状态，不冒充模型作品。')
    d=ThemeConceptDialog([concept],{});d.resize(1120,820);d.show();QTest.qWait(350)
    start=time.monotonic()-91
    activity=dict(label='等待首个输出',started_monotonic=start,last_output_monotonic=None,
        status='running',local_state='本地进程存活',transport_connected=True,last_response_monotonic=time.monotonic(),
        task_budget=dict(task_started_monotonic=start,total_seconds=600,repairs_used=0,max_repairs=2))
    checks={}
    state=dict(status='running',stage='等待首个输出',activity=activity,task_budget=activity['task_budget'])
    d.set_task_states({'A':state});QTest.qWait(80);d.grab().save(str(out/'waiting.png'))
    before=d.status.text();QTest.qWait(1200)
    checks['one_second_clock_updates']=before!=d.status.text()
    checks['silence_honest']='远端内部进度不可见' in d.picture.text()
    checks['one_candidate_is_compact']=d.candidate_list.item(0).sizeHint().width()<=320
    checks['details_default_collapsed']=not d.tabs.isVisible()
    for label,status,detail in [('repairing','repairing','流中断，保留 HTML，正在补全缺失 CSS'),('failed','failed','恢复次数已用完；原始正文与方向已保存'),('cancelled','cancelled','用户取消，迟到输出不会采用')]:
        state=copy.deepcopy(state);state.update(status=status,detail=detail,error=detail)
        if status!='repairing':state['finished_monotonic']=time.monotonic()
        state['task_budget']['repairs_used']=2
        d.set_task_states({'A':state});QTest.qWait(80);d.grab().save(str(out/(label+'.png')))
        checks[label+'_consistent']=('停止并保留'==d.primary.text())==(status=='repairing')
    QTest.mouseClick(d.details_toggle,Qt.LeftButton);d.tabs.setCurrentIndex(2);QTest.qWait(100)
    checks['details_expand']=d.tabs.isVisible()
    # The generator may send a terminal snapshot with the same ID and no path.
    terminal=dict(concept,pending=False,technical_status='failed',technical_errors=[dict(constraint='正文截断')])
    d.update_concepts([terminal],{});QTest.qWait(50)
    checks['no_stale_processing']='正在处理此方向' not in d.picture.text()
    d.grab().save(str(out/'expanded.png'));d.close()
    result=dict(checks=checks,passed=all(checks.values()),real_user_click=False,
                note='Real Qt widgets on isolated desktop, accelerated state injection; no provider calls.')
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(result,ensure_ascii=False));return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
