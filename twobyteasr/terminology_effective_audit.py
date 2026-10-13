"""Opt-in regular source/frozen GUI checks, only using guarded audit data."""
from __future__ import annotations
import json
from pathlib import Path


def run_glossary_checks(owner, output):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from .studio_acceptance_audit import require
    from .theme_manager import apply_theme
    from .terminology import TermResolver, snapshot_glossaries
    from .service import RunOptions
    from .runtime import activate_runtime_context

    output = Path(output)
    app = QApplication.instance()
    results = dict(passed=False, checks=[], screenshots=[], library_ids=[])

    def check(name, value, detail=''):
        results['checks'].append(dict(name=name, passed=bool(value), detail=detail))
        require(value, name + ': ' + str(detail))

    def settle():
        app.processEvents()
        QTest.qWait(100)

    def shot(name):
        settle()
        target = output / (name + '.png')
        _capture(owner, target)
        results['screenshots'].append(target.name)

    def click(button):
        check('visible enabled action ' + button.text(), button.isVisible() and button.isEnabled())
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        settle()

    apply_theme('grape', app)
    owner._manage_terms()
    settle()
    page = owner.term_library_page._ensure_library()
    owner.legacy.RUNTIME_SETTINGS.setdefault('glossary', {})['enabled_glossary_ids'] = []
    owner._save_glossary_settings()

    page.game_input.setText('验收瓦罗兰特')
    click(page.add_game_button)
    primary_id = page._library_key()
    results['primary_id'] = primary_id
    results['library_ids'].append(primary_id)
    check('new library immediately in Home choices', owner.game_box.findData(primary_id) >= 0,
          [owner.game_box.itemText(i) for i in range(owner.game_box.count())])
    page.term_editor.setText('BerLIN')
    page.term_alias_editor.setText('Borlin')
    check('quick form parses raw canonical and alias', 'BerLIN' in page.term_parse_preview.text() and 'Borlin' in page.term_parse_preview.text())
    click(page.add_term_button)
    page.term_editor.setText('S0PP')
    click(page.add_term_button)
    records = owner.legacy.learned_mappings_for_game(primary_id)
    check('real persisted case and digit zero', {(r['from'], r['to']) for r in records} == {
        ('BerLIN', 'BerLIN'), ('Borlin', 'BerLIN'), ('S0PP', 'S0PP')}, records)
    page.term_try_input.setText('Borlin也没有接住，berlin和s0pp，sopp不改')
    page.try_sentence()
    check('same resolver trial actual three hits', 'BerLIN也没有接住，BerLIN和S0PP，sopp不改' in page.term_try_result.text()
          and '替换 3 处' in page.term_try_result.text(), page.term_try_result.text())
    click(page.use_game)
    check('page explicit enable persisted', primary_id in owner._enabled_glossary_ids())
    shot('glossary-canonical-and-trial')
    # A text assertion alone missed a squeezed/clipped result on the actual
    # headed page. Verify the rendered label fits each ancestor and input row.
    label = page.term_try_result
    result_top = label.mapTo(page.term_try_panel, label.rect().topLeft()).y()
    input_top = page.term_try_input.mapTo(page.term_try_panel, page.term_try_input.rect().topLeft()).y()
    clipped = []
    ancestor = label.parentWidget()
    while ancestor is not None and ancestor is not page:
        top = label.mapTo(ancestor, label.rect().topLeft()).y()
        if top < 0 or top + label.height() > ancestor.height():
            clipped.append(dict(parent=ancestor.objectName(), top=top,
                result_height=label.height(), parent_height=ancestor.height()))
        ancestor = ancestor.parentWidget()
    check('rendered trial result fits beneath input without clipping',
        label.isVisible() and result_top >= input_top + page.term_try_input.height() and not clipped,
        dict(text=label.text(), clipped=clipped))
    quick = page.term_try_panel.parentWidget()
    header = quick.parentWidget()
    ai_panel = header.layout().itemAt(header.layout().count() - 1).widget()
    check('AI panel does not cover trial result', ai_panel.geometry().top() > quick.geometry().bottom(),
        dict(quick_bottom=quick.geometry().bottom(), ai_top=ai_panel.geometry().top()))
    last_row = page.listing.model().index(2, 0)
    check('all three fixture rows fit the visible table', page.listing.viewport().rect().contains(page.listing.visualRect(last_row)),
        dict(row=str(page.listing.visualRect(last_row)), viewport=str(page.listing.viewport().rect())))
    click(page.term_try_toggle)
    footer_top = page.use_game.mapTo(owner, page.use_game.rect().topLeft()).y()
    check('collapse trial restores footer action inside window', page.term_try_panel.isHidden()
        and page.use_game.isVisible() and footer_top >= 0 and footer_top + page.use_game.height() <= owner.height(),
        dict(footer_top=footer_top, button_height=page.use_game.height(), window_height=owner.height()))
    shot('glossary-collapsed-footer-visible')

    # Real edit form covers the historical lowercase repair without guesswork.
    owner.legacy.add_learned_mapping(primary_id, 'caseonly', 'caseonly')
    mapping = next(r for r in owner.legacy.learned_mappings_for_game(primary_id) if r['to'] == 'caseonly')
    page._show_edit_sheet(mapping)
    page.edit_canonical.setText('CaseONLY')
    click(page.edit_save_button)
    check('case-only edit stored atomically', any(r['from'] == r['to'] == 'CaseONLY' for r in owner.legacy.learned_mappings_for_game(primary_id)))
    owner.legacy.delete_learned_mappings(primary_id, [('CaseONLY', 'CaseONLY')])
    page._notify_library_changed()
    page.refresh_current_game()

    page.show_import_dialog()
    page.import_editor.setPlainText('berlin\nBorlin → 其他名字\nS0PP')
    check('import previews explicit conflicts and protected case', '冲突' in page.import_preview.toPlainText()
          and 'BerLIN' in page.import_preview.toPlainText(), page.import_preview.toPlainText())
    shot('glossary-import-conflict-preview')
    page._import_cleanup()
    export_path = output / 'canonical-library-export.json'
    page._export_library_to(export_path)
    exported = json.loads(export_path.read_text('utf8'))
    check('export canonical fields match stored evidence', exported['mappings'] == owner.legacy.learned_mappings_for_game(primary_id))

    page.game_input.setText('验收另一个词库')
    click(page.add_game_button)
    second_id = page._library_key()
    results['library_ids'].append(second_id)
    page.term_editor.setText('NovaID')
    click(page.add_term_button)
    click(page.use_game)
    check('two independent libraries enabled', owner._enabled_glossary_ids() == [primary_id, second_id], owner._enabled_glossary_ids())
    page._rename_library(second_id, '验收选手词库')
    check('rename retains ID and immediate Home choice', second_id in owner._enabled_glossary_ids()
          and owner.game_box.findData(second_id) >= 0 and owner.game_box.itemText(owner.game_box.findData(second_id)) == '验收选手词库')
    owner._switch_page(owner.settings_scroll)
    settle()
    owner._refresh_glossary_chips()
    check('Home actual enabled names and effective count', '验收瓦罗兰特' in owner.batch_glossary_status.text()
          and '验收选手词库' in owner.batch_glossary_status.text() and '3' in owner.batch_glossary_status.text(), owner.batch_glossary_status.text())
    owner.settings_scroll.ensureWidgetVisible(owner.batch_glossary_status, 0, 24)
    settle()
    shot('home-enabled-glossaries')

    snapshot = snapshot_glossaries(owner.legacy, owner._enabled_glossary_ids())
    options = RunOptions(content_name='验收瓦罗兰特', enabled_glossary_ids=tuple(owner._enabled_glossary_ids()), enable_domain_terms=True,
        glossary_snapshot_json=json.dumps(snapshot.to_dict(), ensure_ascii=False))
    context = options.create_runtime_context(owner.legacy)
    with activate_runtime_context(context):
        check('task runtime actually loads selected canonical evidence', {'BerLIN', 'S0PP', 'NovaID'}.issubset(set(owner.legacy.learned_canonical_terms())))
    check('task snapshot deterministic correction offline', TermResolver(snapshot).resolve('Borlin也没有接住').text == 'BerLIN也没有接住')
    results['snapshot'] = snapshot.summary()
    results['passed'] = True
    (output / 'glossary-effective-checks.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), 'utf8')
    return results
