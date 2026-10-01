"""Qt glue for the game-term search skill: workers, review dialog, batch queue."""

from __future__ import annotations

from typing import Any, Mapping
from urllib.parse import urlparse

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QItemSelectionModel, Qt, QThread, Signal, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QMenu,
    QApplication,
    QSizePolicy,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .glossary_skill import (
    GlossarySearchError,
    apply_term_updates,
    is_core_recommendation,
    detect_search_capability,
    load_update_sessions,
    run_term_search,
    settings_with_service_override,
    undo_update_session,
)
from .i18n import current_language
from .main_ui_branding import _icon
from .ui_theme import GREEN
from .ui_widgets import AnimatedButton

from .i18n import bind_text

from .i18n import tr


def list_ai_services(settings: Mapping[str, Any]) -> list[dict]:
    """Services usable for glossary updates: CLI transports or stored API keys."""
    from .llm_config import AI_SERVICE_SPECS, read_scoped_api_key

    settings_dict = dict(settings) if isinstance(settings, Mapping) else {}
    result = []
    for service_id, spec in AI_SERVICE_SPECS.items():
        if service_id == "custom":
            continue  # 无固定密钥语义，跟随全局即可
        transport = str(spec.get("transport") or "")
        has_key = False
        if not transport.endswith("_cli"):
            provider = str(spec.get("provider") or service_id)
            base_url = str(spec.get("base_url") or "")
            try:
                key, _source = read_scoped_api_key(provider, base_url)
            except Exception:
                key = ""
            has_key = bool(key)
        result.append(
            {
                "service": service_id,
                "label": str(spec.get("label") or service_id),
                "transport": transport,
                "search": transport in {"grok_cli", "antigravity_cli"}
                or str(spec.get("provider")) == "bailian",
                "ready": has_key or transport.endswith("_cli"),
            }
        )
    result.sort(key=lambda item: (not item["ready"], not item["search"]))
    return result


class GlossaryUpdateWorker(QThread):
    """One game: search → validate → diff. Heavy IO/AI runs off the GUI thread."""

    stage_changed = Signal(str, str)      # stage key, human note
    finished_diff = Signal(str, object)   # game, result dict
    failed = Signal(str, str, str)        # game, code, message

    def __init__(self, legacy, game_name: str, settings: Mapping[str, Any], parent=None):
        super().__init__(parent)
        self.legacy = legacy
        self.game_name = str(game_name)
        self.settings = dict(settings) if isinstance(settings, Mapping) else {}
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            result = run_term_search(
                self.legacy,
                self.game_name,
                self.settings,
                progress=lambda stage, note: self.stage_changed.emit(stage, note),
                cancel_check=lambda: self._cancelled,
            )
            if self._cancelled:
                self.failed.emit(self.game_name, "cancelled", "已取消。")
                return
            self.finished_diff.emit(self.game_name, result)
        except GlossarySearchError as exc:
            self.failed.emit(self.game_name, exc.code, exc.detail)
        except Exception as exc:  # noqa: BLE001 - worker must always report
            self.failed.emit(self.game_name, "unexpected", " ".join(str(exc).split())[:240])


class BatchGlossaryUpdateWorker(QThread):
    """Sequential queue over selected games (concurrency 1: never并行付费调用)."""

    game_started = Signal(str)
    game_stage = Signal(str, str, str)    # game, stage, note
    game_diff = Signal(str, object)       # game, result (auto-applied per policy)
    game_failed = Signal(str, str, str)   # game, code, message
    queue_finished = Signal(dict)         # {"done": n, "failed": n, "skipped": n}

    def __init__(self, legacy, games: list[str], settings: Mapping[str, Any], parent=None):
        super().__init__(parent)
        self.legacy = legacy
        self.games = [str(game) for game in games]
        self.settings = dict(settings) if isinstance(settings, Mapping) else {}
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        done = failed = skipped = 0
        for game in self.games:
            if self._cancelled:
                skipped += len(self.games) - (done + failed + skipped)
                break
            self.game_started.emit(game)
            try:
                result = run_term_search(
                    self.legacy,
                    game,
                    self.settings,
                    progress=lambda stage, note, _game=game: self.game_stage.emit(_game, stage, note),
                    cancel_check=lambda: self._cancelled,
                )
                if self._cancelled:
                    skipped += 1
                    continue
                # 批量模式：只自动应用默认勾选的安全项（core/recommended 新增+别名），
                # 冲突与不可核实项保留在结果里供用户逐条审阅，不自动入库。
                safe = [diff for diff in result["diffs"] if diff.checked_by_default]
                if safe:
                    session = apply_term_updates(
                        self.legacy,
                        game,
                        safe,
                        model_label=result.get("model", ""),
                        service_label=result.get("service", ""),
                    )
                    result["auto_session"] = session
                result["auto_applied"] = result.get("auto_session", {}).get("added", 0)
                self.game_diff.emit(game, result)
                session = result.get("auto_session", {})
                if session.get("failed") or session.get("history_saved") is False:
                    failed += 1
                else:
                    done += 1
            except GlossarySearchError as exc:
                if exc.code == "cancelled":
                    skipped += 1
                    continue
                self.game_failed.emit(game, exc.code, exc.detail)
                failed += 1
            except Exception as exc:  # noqa: BLE001
                self.game_failed.emit(game, "unexpected", " ".join(str(exc).split())[:240])
                failed += 1
        self.queue_finished.emit({"done": done, "failed": failed, "skipped": skipped})


_CHANGE_GROUP_ORDER = (
    ("new", "新增词条"),
    ("alias_supplement", "别名补充"),
    ("conflict", "与已确认数据冲突"),
    ("unverifiable", "暂不能核实（无来源）"),
)

_CATEGORY_SORT = {
    "角色": 0, "技能": 1, "装备": 2, "物品": 2, "Boss": 3, "地点": 3,
    "阵营": 3, "机制": 1, "活动": 5, "货币": 5, "玩家用语": 6, "其他": 9,
}
_PRIORITY_SORT = {"core": 0, "recommended": 1, "optional": 2}

_VERIFICATION_LABELS = {
    "page_verified": "✓ 页面核对",
    "catalog_verified": "✓ 目录核对",
    "sourced": "URL 来源",
    "community": "社区来源",
    "none": "—",
}


def _site_label(url: str) -> str:
    try:
        host = urlparse(str(url)).netloc.lower().removeprefix("www.")
    except Exception:
        host = ""
    return host or "来源"


class DiffTableModel(QAbstractTableModel):
    """预览主表：Model-View（几百行不再逐行 setCellWidget），筛选/排序在模型层。"""

    HEADERS = ("", "词条", "分类", "变化", "核对", "来源", "优先")
    COLUMN_TERM, COLUMN_CATEGORY, COLUMN_CHANGE, COLUMN_VERIFY, COLUMN_SOURCE, COLUMN_PRIORITY = 1, 2, 3, 4, 5, 6

    def __init__(self, parent=None):
        super().__init__(parent)
        self._diffs: list = []
        self._checked: set[str] = set()
        self._view: list[int] = []          # 行 → self._diffs 下标
        self._change_filter = "all"
        self._category_filter = "all"
        self._text = ""
        self._sort_column = None
        self._sort_order = Qt.SortOrder.AscendingOrder
        self.review_choices = {}

    @staticmethod
    def identity(diff):
        from .glossary_skill import quote_normalize_term
        return quote_normalize_term(diff.term.term)

    def row_identity(self, row):
        diff = self.row_diff(row)
        return self.identity(diff) if diff is not None else None

    # ------------------------------------------------------------ 数据
    def set_diffs(self, diffs: list) -> None:
        self.beginResetModel()
        order = {key: index for index, (key, _label) in enumerate(_CHANGE_GROUP_ORDER)}
        self._diffs = sorted(
            diffs,
            key=lambda d: (
                order.get(getattr(d, "change_type", ""), 9),
                _CATEGORY_SORT.get(getattr(d.term, "category", ""), 9),
                _PRIORITY_SORT.get(getattr(d.term, "priority", ""), 9),
                getattr(d.term, "term", ""),
            ),
        )
        self._checked = {
            self.identity(diff)
            for index, diff in enumerate(self._diffs)
            if self.review_choices.get(self.identity(diff), getattr(diff, "checked_by_default", False))
        }
        self._rebuild_view()
        self.endResetModel()

    def append_diffs(self, diffs: list) -> None:
        """实时候选：增量追加（保持滚动位置由调用方处理）。"""
        known = {self.identity(d):i for i,d in enumerate(self._diffs)}
        updated = list(self._diffs)
        fresh = []
        for diff in diffs:
            identity = self.identity(diff)
            if identity not in known:
                fresh.append(diff)
                known[identity] = len(updated)
                updated.append(diff)
            else:
                updated[known[identity]] = diff
        if updated == self._diffs:
            return
        self.beginResetModel()
        self._diffs = updated
        for offset, diff in enumerate(fresh):
            index = len(self._diffs) - len(fresh) + offset
            if self.review_choices.get(self.identity(diff), getattr(diff, "checked_by_default", False)):
                self._checked.add(self.identity(diff))
        self._rebuild_view()
        self.endResetModel()

    def diffs(self) -> list:
        return list(self._diffs)

    def row_diff(self, row: int):
        if 0 <= row < len(self._view):
            return self._diffs[self._view[row]]
        return None

    def categories(self) -> list[str]:
        seen: dict[str, None] = {}
        for diff in self._diffs:
            seen.setdefault(getattr(diff.term, "category", "其他"), None)
        return list(seen)

    # ------------------------------------------------------------ 筛选
    def set_filters(self, change: str = "all", category: str = "all", text: str = "") -> None:
        self._change_filter = change
        self._category_filter = category
        self._text = str(text or "").strip().casefold()
        self.beginResetModel()
        self._rebuild_view()
        self.endResetModel()

    def _rebuild_view(self) -> None:
        self._view = []
        for index, diff in enumerate(self._diffs):
            change = getattr(diff, "change_type", "")
            if self._change_filter == "cross" and not getattr(diff, "cross_game", False):
                continue
            if self._change_filter not in {"all", "cross"} and change != self._change_filter:
                continue
            if self._category_filter != "all" and getattr(diff.term, "category", "") != self._category_filter:
                continue
            if self._text:
                haystack = " ".join(
                    [
                        getattr(diff.term, "term", ""),
                        " ".join(getattr(diff.term, "aliases", ()) or ()),
                        getattr(diff.term, "evidence", ""),
                    ]
                ).casefold()
                if self._text not in haystack:
                    continue
            self._view.append(index)
        if self._sort_column is not None:
            column = self._sort_column
            fields = {1: 'term', 2: 'category', 4: 'verification', 6: 'priority'}
            def value(index):
                diff = self._diffs[index]
                if column == 0:
                    return self.identity(diff) in self._checked
                if column == 3:
                    return diff.change_type
                if column == 5:
                    return ' '.join(diff.term.source_urls)
                return getattr(diff.term, fields.get(column, 'term'), '')
            self._view.sort(key=value, reverse=self._sort_order == Qt.SortOrder.DescendingOrder)

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        self.beginResetModel()
        self._sort_column, self._sort_order = column, order
        self._rebuild_view()
        self.endResetModel()

    # ------------------------------------------------------------ Qt 模型
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._view)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        diff = self.row_diff(index.row())
        if diff is None:
            return None
        column = index.column()
        term = diff.term
        if role == Qt.ItemDataRole.CheckStateRole and column == 0:
            row_index = self.identity(diff)
            return Qt.CheckState.Checked if row_index in self._checked else Qt.CheckState.Unchecked
        if role != Qt.ItemDataRole.DisplayRole:
            if role == Qt.ItemDataRole.ToolTipRole and column in (self.COLUMN_TERM, self.COLUMN_SOURCE, self.COLUMN_CHANGE):
                return self._tooltip_for(diff)
            return None
        if column == self.COLUMN_TERM:
            text = term.term
            if term.aliases:
                text += f"（别名 {'、'.join(term.aliases[:3])}）"
            if getattr(diff, "cross_game", False):
                text += "  ⚠跨游戏"
            return text
        if column == self.COLUMN_CATEGORY:
            return term.category
        if column == self.COLUMN_CHANGE:
            labels = dict(_CHANGE_GROUP_ORDER)
            return labels.get(diff.change_type, diff.change_type)
        if column == self.COLUMN_VERIFY:
            return _VERIFICATION_LABELS.get(getattr(term, "verification", "none"), "—")
        if column == self.COLUMN_SOURCE:
            urls = term.source_urls
            if not urls:
                return "无"
            sites = list(dict.fromkeys(_site_label(url) for url in urls))
            return f"{'、'.join(sites[:2])} ×{len(urls)}"
        if column == self.COLUMN_PRIORITY:
            return {"core": "核心", "recommended": "推荐", "optional": "可选"}.get(term.priority, term.priority)
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid() or role != Qt.ItemDataRole.CheckStateRole or index.column() != 0:
            return False
        row_index = self.row_identity(index.row())
        try:
            state = Qt.CheckState(value) if not isinstance(value, Qt.CheckState) else value
        except (TypeError, ValueError):
            state = Qt.CheckState.Unchecked
        if state == Qt.CheckState.Checked:
            self._checked.add(row_index)
        else:
            self._checked.discard(row_index)
        self.review_choices[row_index] = row_index in self._checked
        self.dataChanged.emit(index, index)
        return True

    def flags(self, index):
        # The view owns pointer/Space actions, including the checkbox cell.
        # Do not let the delegate perform a second independent toggle.
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    # ------------------------------------------------------------ 勾选
    def checked_diffs(self) -> list:
        return [diff for diff in self._diffs if self.identity(diff) in self._checked]

    def checked_count(self) -> int:
        return len(self._checked)

    def check_core_verified(self) -> None:
        """选择已核对的核心词：页面核对/有来源 + 核心/推荐 + 新增/别名，跨游戏除外。"""
        for diff in self._diffs:
            index = self.identity(diff)
            change = getattr(diff, "change_type", "")
            keep = (
                change in {"new", "alias_supplement"}
                and is_core_recommendation(diff.term)
                and not getattr(diff, "cross_game", False)
            )
            if keep:
                self._checked.add(index)
            else:
                self._checked.discard(index)
        self._notify_checks()

    def check_none(self) -> None:
        self._checked.clear()
        self._notify_checks()

    def _notify_checks(self):
        self.review_choices.update({self.identity(d):self.identity(d) in self._checked for d in self._diffs})
        self.dataChanged.emit(self.index(0, 0), self.index(max(0, len(self._view)-1), 0))

    def checked_in_filter(self):
        return sum(self.row_identity(row) in self._checked for row in range(self.rowCount()))

    def check_rows(self, rows, checked=None):
        ids = {self.row_identity(row) for row in rows} - {None}
        if checked is None:
            checked = not ids.issubset(self._checked)
        if checked:
            self._checked.update(ids)
        else:
            self._checked.difference_update(ids)
        self._notify_checks()

    def check_filtered(self, checked):
        if checked is None:
            self._checked.symmetric_difference_update(self.row_identity(row) for row in range(self.rowCount()))
            self._notify_checks()
        else:
            self.check_rows(range(self.rowCount()), checked)

    def _tooltip_for(self, diff) -> str:
        term = diff.term
        parts = [term.term]
        if term.aliases:
            parts.append("别名：" + "、".join(term.aliases))
        if term.evidence:
            parts.append("依据：" + term.evidence)
        if term.version_note:
            parts.append("版本：" + term.version_note)
        if term.frequency_note:
            parts.append("频率：" + term.frequency_note)
        parts.extend(term.source_urls)
        return "\n".join(parts)


class CandidateTableView(QTableView):
    """Ordinary clicks toggle once; modifiers only construct a selection range."""
    def mousePressEvent(self, event):
        self._press_index = self.indexAt(event.position().toPoint())
        self._press_pos = event.position().toPoint()
        self._plain_press = event.button() == Qt.MouseButton.LeftButton and not event.modifiers()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        index = self.indexAt(event.position().toPoint())
        activate = (getattr(self, '_plain_press', False) and index.isValid()
            and index == self._press_index
            and (event.position().toPoint()-self._press_pos).manhattanLength() < QApplication.startDragDistance()
            and self.indexWidget(index) is None)
        super().mouseReleaseEvent(event)
        self._plain_press = False
        if activate:
            self.model().check_rows([index.row()])

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not event.modifiers():
            rows = [index.row() for index in self.selectionModel().selectedRows()]
            self.model().check_rows(rows)
            event.accept()
            return
        super().keyPressEvent(event)


class DetailSummaryLabel(QLabel):
    """Two complete plain-text lines; elide by pixels, never clip half a line."""
    def set_summary(self, text):
        self._summary = str(text)
        self.setToolTip(self._summary[:1000])
        self._update_summary()

    def _update_summary(self):
        lines = getattr(self, '_summary', '').splitlines()
        rows = lines[:1] + ([' '.join(lines[1:])] if len(lines)>1 else [])
        metrics = self.fontMetrics()
        self.setText('\n'.join(metrics.elidedText(row, Qt.TextElideMode.ElideRight,
            max(0,self.contentsRect().width())) for row in rows))
        self.setFixedHeight(metrics.lineSpacing()*max(1,len(rows))+4)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_summary()


class GlossaryUpdateReviewDialog(QWidget):
    """Diff 预览（VII 轮重做）：大窗口 + Model-View 主表 + 筛选 + 详情区。

    主表来源列只显示"站点 ×N"短标签，完整 URL 在详情区/tooltip；
    勾选计数实时更新；支持任务进行中的实时候选视图（apply_locked=True）。
    """

    applied = Signal(str, int, int)  # legacy observers
    application_result = Signal(str, object)  # complete partial-failure receipt

    def __init__(self, owner, game_name: str, result: Mapping[str, Any], parent=None, *, apply_locked: bool = False):
        super().__init__(parent or owner)
        self.owner = owner
        self.game_name = str(game_name)
        self.result = dict(result)
        self.diffs = list(result.get("diffs", ()))
        self.apply_locked = apply_locked
        self._history_failed = False
        self.setObjectName("glossaryUpdateReview")
        layout = QVBoxLayout(self)
        outer = layout
        outer.setContentsMargins(16, 14, 16, 12)
        outer.setSpacing(8)
        # The modal host may be shorter than this page's sizeHint. Bound the
        # expanding execution/source section independently from table/footer.
        self.status_scroll = QScrollArea()
        self.status_scroll.setWidgetResizable(True)
        self.status_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.status_scroll.setMinimumHeight(54)
        self.status_scroll.setMaximumHeight(140)
        self.status_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        status_panel = QWidget()
        layout = QVBoxLayout(status_panel)
        self.status_scroll.setWidget(status_panel)
        outer.addWidget(self.status_scroll)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # ---- 头部
        head = QHBoxLayout()
        mode = str(result.get("mode") or "incremental")
        title = bind_text(QLabel(), '{value0}预览｜{value1}', value0=tr('完整建库') if mode == 'full' else tr('更新'), value1=self.game_name)
        title.setStyleSheet("font-weight:700; font-size:15px;")
        title.setTextFormat(Qt.TextFormat.PlainText)
        head.addWidget(title, 0, Qt.AlignmentFlag.AlignTop)
        meta_bits = []
        from .glossary_execution import summary_text, execution_summary, timestamp_text
        meta_bits.append(summary_text(result))
        if result.get("search_evidence"):
            meta_bits.append('收到真实检索回执')
        if result.get('quality_status'):
            meta_bits.append(str(result['quality_status']))
        if result.get("elapsed_seconds") is not None:
            meta_bits.append(f"耗时 {result['elapsed_seconds']}s")
        meta = QLabel(" · ".join(part for part in meta_bits if part))
        meta.setTextFormat(Qt.TextFormat.PlainText)
        meta.setWordWrap(True)
        meta.setMinimumWidth(0)
        meta.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        meta.setObjectName("muted")
        head.addWidget(meta, 1, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(head)
        if result.get("execution_events"):
            from .execution_process_view import ExecutionProcessView
            self.process_view=ExecutionProcessView(lambda:result.get("execution_events",[]),self)
            layout.addWidget(self.process_view)

        stats = self.result.get("build_stats") or {}
        if stats:
            stats_line = (
                f"版本 {stats.get('current_version') or '未知'}（{stats.get('game_version_status') or '未独立核对'}） · 目录页 {len(stats.get('catalogs', ()) or ())}"
                f" · 候选 {stats.get('names_kept', 0)} / 确定性采集 {stats.get('deterministic_count', 0)}"
                f" · 页面核对 {stats.get('page_verified', 0)}"
                f" · 目录核对 {stats.get('catalog_verified', 0)}"
                + (f" · 截断 {stats.get('names_truncated')}（名称超预算，按类别优先级保留）" if stats.get("names_truncated") else "")
            )
            stats_label = QLabel(stats_line)
            stats_label.setObjectName("muted")
            stats_label.setWordWrap(True)
            layout.addWidget(stats_label)
            coverage=QLabel(' · '.join(f'{category} {count}' for category,count in stats.get('category_counts',{}).items())
                +' · '+str(stats.get('coverage_status') or '完整性未知'))
            coverage.setWordWrap(True);coverage.setObjectName('muted');layout.addWidget(coverage)
            detail_button = QPushButton('来源回执与未完成项')
            detail_button.setCheckable(True)
            evidence_view = QPlainTextEdit()
            evidence_view.setReadOnly(True)
            evidence_view.setMaximumHeight(160)
            evidence_view.hide()
            lines = ['待补齐分类：' + '、'.join(stats.get('missing_categories', []))]
            execution = execution_summary(result)
            lines += [f"配置模型：{result.get('service','')} / {result.get('model','')}（不等于本次实际调用）",
                      f"本次执行：{summary_text(result)}",
                      f"模型参与阶段：{'、'.join(execution.get('model_stages',[])) or '无 / 未记录'}",
                      f"候选计数（去重）：缓存 {execution.get('cached_candidates','未知')}；新采集 {execution.get('new_candidates','未知')}；模型新增 {execution.get('model_added',0)}；总数 {execution.get('unique_candidates',result.get('candidate_count',0))}",
                      '核心推荐来自类别规则 / 实际模型评估；未测量直播词频。']
            for row in stats.get('source_results', []):
                lines.append(f"{row.get('url','')} · {'已读取' if row.get('read') else '未读取'} · {row.get('error','')}\n获取/最近核对：{timestamp_text(row.get('fetched_at'))} · 版本 {row.get('version','未知')} · {row.get('scope','范围未知')}")
            for row in stats.get('http_receipts', []):
                lines.append(f"HTTP {row.get('status','?')} · {row.get('url','')} · 正文 {row.get('body_chars',0)} 字符 · SHA256 {row.get('body_sha256','')}")
            evidence_view.setPlainText('\n'.join(lines))
            detail_button.toggled.connect(evidence_view.setVisible)
            layout.addWidget(detail_button)
            layout.addWidget(evidence_view)

        layout = outer
        # ---- 筛选行
        filters = QHBoxLayout()
        self.change_filter = QComboBox()
        self.change_filter.addItem("全部变化", "all")
        for key, label in _CHANGE_GROUP_ORDER:
            self.change_filter.addItem(label, key)
        self.change_filter.addItem("跨游戏标记", "cross")
        filters.addWidget(self.change_filter)
        self.category_filter = QComboBox()
        self.category_filter.addItem("全部分类", "all")
        filters.addWidget(self.category_filter)
        self.search_box = QLineEdit()
        bind_text(self.search_box, '筛选词条 / 别名 / 依据…', property='placeholderText')
        filters.addWidget(self.search_box, 1)
        self.checked_label = QLabel("")
        self.checked_label.setObjectName("muted")
        layout.addLayout(filters)
        layout.addWidget(self.checked_label)
        self.change_filter.currentIndexChanged.connect(self._apply_filters)
        self.category_filter.currentIndexChanged.connect(self._apply_filters)
        self.search_box.textChanged.connect(self._apply_filters)

        # ---- 主表
        self.model = DiffTableModel(self)
        self.model.review_choices = self.result.setdefault('review_choices', {})
        self.table = CandidateTableView()
        self.table.setModel(self.model)
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(self.model.COLUMN_TERM, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.model.COLUMN_CATEGORY, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.model.COLUMN_CHANGE, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.model.COLUMN_VERIFY, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.model.COLUMN_SOURCE, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.model.COLUMN_PRIORITY, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setColumnWidth(0, 34)
        self.table.setMinimumHeight(128)
        self.table.setSortingEnabled(True)
        self.table.selectionModel().currentRowChanged.connect(self._on_row_changed)
        layout.addWidget(self.table, 1)

        # ---- 详情区
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMinimumHeight(60)
        self.detail.setMaximumHeight(80)
        self.detail.hide()
        self.detail_summary = DetailSummaryLabel('')
        self.detail_summary.setTextFormat(Qt.TextFormat.PlainText)
        self.detail_summary.setWordWrap(False)
        self.detail_summary.setMinimumWidth(0)
        self.detail_summary.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.detail_toggle = QPushButton('展开完整依据与来源')
        self.detail_toggle.setCheckable(True)
        self.detail_toggle.toggled.connect(self.detail.setVisible)
        self.detail_toggle.toggled.connect(lambda expanded: self.detail_summary.setVisible(not expanded))
        self.copy_detail = QPushButton('复制详情')
        self.copy_detail.clicked.connect(lambda: QApplication.clipboard().setText(self.detail.toPlainText()))
        detail_frame = self.detail_frame = QFrame()
        detail_frame.setObjectName("reviewDetail")
        detail_layout = QVBoxLayout(detail_frame)
        detail_layout.setContentsMargins(10, 6, 10, 6)
        detail_heading = QHBoxLayout()
        detail_heading.addWidget(QLabel('当前词条详情'), 1)
        detail_heading.addWidget(self.detail_toggle)
        detail_heading.addWidget(self.copy_detail)
        detail_layout.addLayout(detail_heading)
        detail_layout.addWidget(self.detail_summary)
        detail_layout.addWidget(self.detail)
        layout.addWidget(detail_frame)

        # ---- 汇总
        group_counts = {
            key: sum(1 for diff in self.diffs if diff.change_type == key)
            for key, _label in _CHANGE_GROUP_ORDER
        }
        if not self.diffs:
            from .glossary_outcome import empty_result_message
            empty = QLabel(
                empty_result_message(self.result)
                if current_language() == "zh"
                else "No verified additions. Check source receipts; coverage is not established."
            )
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setObjectName("muted")
            layout.addWidget(empty, 1)
        summary_bits = [f"候选 {self.result.get('candidate_count', 0)}"]
        summary_bits += [
            f"{label} {group_counts[key]}" for key, label in _CHANGE_GROUP_ORDER
            if group_counts[key]
        ]
        summary = QLabel("；".join(summary_bits))
        summary.setObjectName("muted")
        summary.setWordWrap(True)
        layout.addWidget(summary)

        # ---- 按钮
        actions = QHBoxLayout()
        self.select_core = AnimatedButton("仅选全部核心推荐")
        self.select_core.setObjectName("flat")
        self.select_core.clicked.connect(self._check_core)
        actions.addWidget(self.select_core)
        self.select_none = AnimatedButton("批量勾选 ▾")
        self.select_none.setObjectName("flat")
        bulk_menu = QMenu(self.select_none)
        for label, mode in [('全选当前筛选结果', True), ('取消当前筛选结果', False), ('反选当前筛选结果', None)]:
            bulk_menu.addAction(label).triggered.connect(lambda _checked=False, mode=mode: self.model.check_filtered(mode))
        bulk_menu.addSeparator()
        bulk_menu.addAction('清空全部勾选（含筛选外）').triggered.connect(self.model.check_none)
        self.select_none.setMenu(bulk_menu)
        actions.addWidget(self.select_none)
        actions.addStretch(1)
        if self.apply_locked:
            lock_note = QLabel("任务仍在进行中——可先筛选查看，结束后才能应用。")
            lock_note.setObjectName("muted")
            actions.addWidget(lock_note)
        self.cancel_button = QPushButton("关闭")
        self.cancel_button.setObjectName("workshopSecondary")
        self.cancel_button.clicked.connect(self._close)
        actions.addWidget(self.cancel_button)
        self.apply_button = QPushButton("应用所选")
        self.apply_button.setProperty("studioPrimary", True)
        self.apply_button.clicked.connect(self._apply)
        actions.addWidget(self.apply_button)
        if not self.diffs or self.apply_locked:
            self.apply_button.setEnabled(False)
            self.select_core.setEnabled(False)
            self.select_none.setEnabled(False)
        layout.addLayout(actions)

        self.model.set_diffs(self.diffs)
        self.model.dataChanged.connect(lambda *_a: self._refresh_checked_label())
        self.model.modelReset.connect(self._refresh_checked_label)
        self.model.modelAboutToBeReset.connect(self._remember_view_identity)
        self.model.modelReset.connect(self._restore_view_identity)
        for category in self.model.categories():
            self.category_filter.addItem(category, category)
        self._refresh_checked_label()
        if self.diffs:
            self.table.selectRow(0)

    # ------------------------------------------------------------ 交互
    def _remember_view_identity(self):
        self._current_identity=self.model.row_identity(self.table.currentIndex().row())
        self._selected_identities={self.model.row_identity(i.row()) for i in self.table.selectionModel().selectedRows()}

    def _restore_view_identity(self):
        selection=self.table.selectionModel()
        for row in range(self.model.rowCount()):
            identity=self.model.row_identity(row)
            index=self.model.index(row,0)
            if identity in getattr(self,'_selected_identities',set()):
                selection.select(index,QItemSelectionModel.SelectionFlag.Select|QItemSelectionModel.SelectionFlag.Rows)
            if identity==getattr(self,'_current_identity',None):
                selection.setCurrentIndex(index,QItemSelectionModel.SelectionFlag.NoUpdate)

    def _apply_filters(self, *_args):
        identity = self.model.row_identity(self.table.currentIndex().row())
        self.model.set_filters(
            change=str(self.change_filter.currentData() or "all"),
            category=str(self.category_filter.currentData() or "all"),
            text=self.search_box.text(),
        )
        # 筛选后详情区不得残留已隐藏行的内容（P0：图文脱节）
        if self.model.rowCount():
            row = next((row for row in range(self.model.rowCount()) if self.model.row_identity(row) == identity), 0)
            self.table.selectRow(row)
        else:
            self._set_detail_text('当前筛选没有词条。')
        self._refresh_checked_label()

    def _on_row_changed(self, current, _previous):
        diff = self.model.row_diff(current.row()) if current.isValid() else None
        if diff is None:
            self._set_detail_text('')
            return
        term = diff.term
        bits = [term.term]
        if term.aliases:
            bits.append("别名：" + "、".join(term.aliases))
        priority_label = {"core": "核心", "recommended": "推荐", "optional": "可选"}.get(
            term.priority, term.priority
        )
        bits.append(f"{term.category} · {priority_label}")
        if term.evidence:
            bits.append("依据：" + term.evidence)
        if term.version_note:
            bits.append("版本：" + term.version_note)
        if term.frequency_note:
            bits.append("优先级依据：" + term.frequency_note)
        labels = dict(_CHANGE_GROUP_ORDER)
        bits.append(labels.get(diff.change_type, diff.change_type) + (" · ⚠跨游戏同名" if getattr(diff, "cross_game", False) else ""))
        links = [f'{_site_label(url)}：{url}' for url in term.source_urls]
        if links:
            bits.extend(links)
        for source in term.sources:
            fields = [('source_type','来源类型'),('registry_key','资源键'),('task_id','采集任务'),('version','版本'),('branch','分支'),('language','语言')]
            bits.extend(f'{label}：{source[key]}' for key,label in fields if source.get(key))
            if source.get('suggested_aliases'):
                bits.append('模型建议别名（未核对，不自动纳入别名）：' + '、'.join(source['suggested_aliases']))
        self._set_detail_text('\n'.join(bits), f'{term.term} · {term.category} · {priority_label}\n{term.evidence}')

    def _set_detail_text(self, text, summary=None):
        # Plain text never fetches embedded resources or executes external HTML.
        self.detail.setPlainText(text)
        short = text if summary is None else summary
        self.detail_summary.set_summary(short)

    def _check_core(self):
        self.model.check_core_verified()
        self._refresh_checked_label()

    def _refresh_checked_label(self):
        total = self.model.rowCount()
        checked = self.model.checked_count()
        inside = self.model.checked_in_filter()
        bind_text(self.checked_label, '总勾选 {checked}；当前筛选中 {inside}/{total}；筛选外 {value3}', checked=checked, inside=inside, total=total, value3=checked - inside)
        if not self.apply_locked:
            (bind_text(self.apply_button, '应用所选（{value0}）', value0=checked) if checked else bind_text(self.apply_button, '应用所选'))

    def _apply(self):
        if self.apply_locked:
            return
        selected = self.model.checked_diffs()
        if not selected:
            return
        session = apply_term_updates(
            self.owner.legacy,
            self.game_name,
            selected,
            model_label=self.result.get("model", ""),
            service_label=self.result.get("service", ""),
            task_id=self.result.get('task_id',''),
        )
        self.applied.emit(
            self.game_name,
            session.get("added", 0),
            session.get("duplicates", 0),
        )
        self.application_result.emit(self.game_name, session)
        self._history_failed = self._history_failed or session.get("history_saved") is False
        if session.get("failed"):
            failed_targets = {key[1] for key in session.get("failed_keys", [])}
            # Retain failed rows (including partial alias failures). Retrying is
            # idempotent at the real store, so successful mappings stay intact.
            self.diffs = [d for d in self.diffs if d not in selected or d.term.term in failed_targets]
            self.model.set_diffs(self.diffs)
            self.model._checked = {self.model.identity(d) for d in self.model._diffs if d in selected}
            self.model.layoutChanged.emit()
            self._refresh_checked_label()
            self._set_detail_text(f"已保存 {session['added']} 条，已存在 {session['duplicates']} 条，失败 {session['failed']} 条。失败候选已保留，请重试。")
            if self._history_failed:
                self._set_detail_text(self.detail.toPlainText() + " 本轮部分撤销记录未保存。")
            return
        if self._history_failed:
            self._set_detail_text(f"已保存 {session['added']} 条；撤销记录保存失败，不能通过更新历史撤销此次入库。请保留当前结果。")
            self.apply_button.setEnabled(False)
            return
        self._close()

    def _close(self):
        if self.isWindow():
            self.hide()
            return
        host = getattr(self.owner, "_modal_host", None)
        if host is not None:
            try:
                host.hide_content()
                return
            except Exception:
                pass
        self.hide()


class GlossaryTaskCandidatesDialog(QWidget):
    """任务进行中的实时候选视图（只读，任务结束后由正式预览接管）。"""

    def __init__(self, owner, task, parent=None):
        super().__init__(parent or owner)
        self.owner = owner
        self.task = task
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(8)
        head = QHBoxLayout()
        title = QLabel(f"{task.game} · {task.mode_label}")
        title.setStyleSheet("font-weight:700; font-size:15px;")
        head.addWidget(title, 1)
        self.count_label = QLabel("")
        self.count_label.setObjectName("muted")
        head.addWidget(self.count_label)
        self.stage_label = QLabel("")
        self.stage_label.setObjectName("muted")
        head.addWidget(self.stage_label, 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(head)
        self.identity_label=QLabel(f"{task.service_label} / {task.model_label}")
        layout.addWidget(self.identity_label)
        from .execution_process_view import ExecutionProcessView
        self.process_view=ExecutionProcessView(lambda:task.events,self)
        layout.addWidget(self.process_view)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["词条", "分类", "别名", "优先", "来源"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setWordWrap(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.setMinimumHeight(120)
        layout.addWidget(self.table, 1)
        hint = QLabel("任务进行中——以下为已到手的候选快照；全部批次完成后打开正式预览应用。")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        close = QPushButton("关闭")
        close.setObjectName("workshopSecondary")
        close.clicked.connect(self._close)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        layout.addLayout(row)
        self._snapshot_identity=None
        self.timer=QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def refresh(self):
        self.stage_label.setText(self.task.progress_line())
        bind_text(self.identity_label, '{value0} / {value1} · 总耗时 {value2}s · 距真实事件 {value3}s · {value4} 候选', value0=self.task.service_label, value1=self.task.model_label, value2=self.task.elapsed_seconds(), value3=self.task.idle_seconds(), value4=self.task.candidates)
        identity=id(self.task.partial_candidates)
        if identity != self._snapshot_identity:
            self._snapshot_identity=identity
            self._populate()

    def _populate(self):
        snapshot = getattr(self.task, "partial_candidates", ()) or ()
        bind_text(self.count_label, '已就绪 {value0} 条快照', value0=len(snapshot))
        self.table.setRowCount(0)
        for item in snapshot:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(item.get("term") or "")))
            self.table.setItem(row, 1, QTableWidgetItem(str(item.get("category") or "")))
            self.table.setItem(
                row, 2, QTableWidgetItem("、".join(item.get("aliases", ()) or ())[:60])
            )
            self.table.setItem(
                row, 3,
                QTableWidgetItem(
                    {"core": "核心", "recommended": "推荐", "optional": "可选"}.get(
                        str(item.get("priority") or ""), str(item.get("priority") or "")
                    )
                ),
            )
            sources = item.get("sources", ()) or ()
            sites = list(dict.fromkeys(_site_label(str(s.get("url") or "")) for s in sources if s.get("url")))
            self.table.setItem(row, 4, QTableWidgetItem(f"{'、'.join(sites[:2])} ×{len(sources)}" if sites else "无"))

    def _close(self):
        host = getattr(self.owner, "_modal_host", None)
        if host is not None:
            try:
                host.hide_content()
                return
            except Exception:
                pass
        self.hide()


class GlossaryUpdateHistoryDialog(QWidget):
    """更新会话回溯：查看每次合并的模型/来源，可撤销本次合并。"""

    def __init__(self, owner, game_name: str, parent=None):
        super().__init__(parent or owner)
        self.owner = owner
        self.game_name = str(game_name)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        title = bind_text(QLabel(), '更新记录｜{value0}', value0=self.game_name)
        title.setStyleSheet("font-weight:700; font-size:15px;")
        layout.addWidget(title)
        self.list = QListWidget()
        self.list.setMinimumHeight(260)
        layout.addWidget(self.list, 1)
        actions = QHBoxLayout()
        actions.addStretch(1)
        self.undo_button = AnimatedButton("撤销所选合并")
        self.undo_button.setObjectName("outline")
        self.undo_button.setIcon(_icon("fa5s.undo", GREEN))
        self.undo_button.clicked.connect(self._undo_selected)
        actions.addWidget(self.undo_button)
        close = QPushButton("关闭")
        close.setObjectName("workshopSecondary")
        close.clicked.connect(self._close)
        actions.addWidget(close)
        layout.addLayout(actions)
        self._sessions: list[dict] = []
        self._reload()

    def _reload(self):
        self.list.clear()
        self._sessions = list(reversed(load_update_sessions(self.game_name)))
        for session in self._sessions:
            at = str(session.get("at", ""))[:19].replace("T", " ")
            item = QListWidgetItem(
                f"{at} · {session.get('service', '')} / {session.get('model', '')}"
                f" · 应用 {len(session.get('applied_keys', []))} 条映射"
            )
            item.setData(Qt.ItemDataRole.UserRole, session)
            self.list.addItem(item)
        if not self._sessions:
            self.list.addItem(QListWidgetItem("还没有联网更新记录。"))

    def _undo_selected(self):
        item = self.list.currentItem()
        session = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not isinstance(session, dict) or not session.get("applied_keys"):
            return
        removed = undo_update_session(self.owner.legacy, session)
        self._reload()
        hint = getattr(self.owner, "term_hint", None)
        if hint is not None:
            bind_text(hint, '已撤销本次合并中的 {removed} 条映射。', removed=removed)

    def _close(self):
        host = getattr(self.owner, "_modal_host", None)
        if host is not None:
            try:
                host.hide_content()
                return
            except Exception:
                pass
        self.hide()


class BatchUpdateDialog(QWidget):
    """选择多个游戏按队列检查更新；逐游戏结果与失败原因互不影响。"""

    batch_finished = Signal(dict)

    def __init__(self, owner, games: list[str], settings_factory, parent=None):
        super().__init__(parent or owner)
        self.owner = owner
        self.games = [str(game) for game in games]
        self.settings_factory = settings_factory
        self.worker: BatchGlossaryUpdateWorker | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        title = QLabel("批量检查更新")
        title.setStyleSheet("font-weight:700; font-size:15px;")
        layout.addWidget(title)
        hint = QLabel("按队列逐个游戏联网检查（不并行调用）；取消立即停止后续调度，已完成结果保留。")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.list = QListWidget()
        self.list.setMinimumHeight(280)
        for game in self.games:
            item = QListWidgetItem(game)
            item.setData(Qt.ItemDataRole.UserRole, game)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.list.addItem(item)
        layout.addWidget(self.list, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, max(1, len(self.games)))
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.status = QLabel("")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        self.start_button = QPushButton("开始批量更新")
        self.start_button.setProperty("studioPrimary", True)
        self.start_button.clicked.connect(self._start)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setObjectName("workshopSecondary")
        self.cancel_button.clicked.connect(self._cancel)
        self.cancel_button.setEnabled(False)
        actions.addStretch(1)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.start_button)
        layout.addLayout(actions)
        self._results: dict[str, str] = {}
        self._review_results = {}
        self.list.itemDoubleClicked.connect(self._review_game)

    def _selected_games(self) -> list[str]:
        games = []
        for index in range(self.list.count()):
            item = self.list.item(index)
            if item.checkState() == Qt.CheckState.Checked:
                games.append(str(item.data(Qt.ItemDataRole.UserRole)))
        return games

    def _start(self):
        games = self._selected_games()
        if not games:
            bind_text(self.status, '请先勾选要更新的游戏。')
            return
        settings = self.settings_factory()
        self.worker = BatchGlossaryUpdateWorker(self.owner.legacy, games, settings, self)
        self.worker.game_started.connect(self._on_game_started)
        self.worker.game_stage.connect(self._on_game_stage)
        self.worker.game_diff.connect(self._on_game_diff)
        self.worker.game_failed.connect(self._on_game_failed)
        self.worker.queue_finished.connect(self._on_queue_finished)
        self.progress.setRange(0, len(games))
        self.progress.setValue(0)
        self.progress.show()
        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self._total = len(games)
        self._done = 0
        self.worker.start()

    def _cancel(self):
        if self.worker is not None:
            self.worker.cancel()
        bind_text(self.status, '正在取消…后续游戏将跳过。')

    def _on_game_started(self, game: str):
        bind_text(self.status, '[{game}] 检索来源…', game=game)

    def _on_game_stage(self, game: str, stage: str, note: str):
        stage_labels = {
            "检索来源": "检索来源", "提取候选": "提取候选", "去重/比较": "去重/比较",
        }
        self.status.setText(f"[{game}] {stage_labels.get(stage, stage)} {note}".rstrip())

    def _on_game_diff(self, game: str, result):
        self._done += 1
        self.progress.setValue(self._done)
        diffs = result.get("diffs", ())
        self._review_results[game] = result
        session = result.get("auto_session", {})
        failed_targets = {key[1] for key in session.get("failed_keys", [])}
        pending = sum(not d.checked_by_default or d.term.term in failed_targets for d in diffs)
        self._results[game] = (
            f"已保存映射 {result.get('auto_applied', 0)} · 失败 {session.get('failed', 0)}"
            f" · 待审阅词条 {pending}（双击查看/重试）"
            + (" · 撤销记录未保存" if session.get("history_saved") is False else "")
        )
        for index in range(self.list.count()):
            item = self.list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == game:
                mark = "!" if session.get("failed") or session.get("history_saved") is False else "✓"
                item.setText(f"{game}    {mark} {self._results[game]}")

    def _review_game(self, item):
        game = str(item.data(Qt.ItemDataRole.UserRole))
        result = self._review_results.get(game)
        if not result:
            return
        self._review_dialog = GlossaryUpdateReviewDialog(self.owner, game, result, self)
        self._review_dialog.application_result.connect(self._on_review_result)
        self._review_dialog._history_failed = result.get("auto_session", {}).get("history_saved") is False
        self._review_dialog.setWindowFlag(Qt.WindowType.Window, True)
        self._review_dialog.resize(1000, 680)
        self._review_dialog.show()

    def _on_review_result(self, game, session):
        self._results[game] = f"复核已保存 {session['added']} · 已存在 {session['duplicates']} · 失败 {session['failed']}"
        if session.get('history_saved') is False:
            self._results[game] += ' · 撤销记录未保存'
        for index in range(self.list.count()):
            item = self.list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == game:
                item.setText(f"{game}    {self._results[game]}")
        self.batch_finished.emit({'review_game': game, 'added': session['added'], 'failed': session['failed']})

    def _on_game_failed(self, game: str, code: str, message: str):
        self._done += 1
        self.progress.setValue(self._done)
        self._results[game] = f"失败（{code}）：{message}"
        for index in range(self.list.count()):
            item = self.list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == game:
                item.setText(f"{game}    ✗ {self._results[game]}")

    def _on_queue_finished(self, summary: dict):
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        bind_text(self.status, '批量完成：成功 {value0} · 失败 {value1} · 跳过 {value2}。已保存项已入库；双击结果可查看候选和重试失败项。', value0=summary.get('done', 0), value1=summary.get('failed', 0), value2=summary.get('skipped', 0))
        self.batch_finished.emit(summary)


def _retain_size(button) -> None:
    """隐藏时保留布局占位：按钮槽位纵向对齐的关键。"""
    policy = button.sizePolicy()
    policy.setRetainSizeWhenHidden(True)
    button.setSizePolicy(policy)


class GlossaryTaskStrip(QWidget):
    """术语库页常驻任务栏：运行中/排队任务持续可见（真实进度），完成后保留可查看/移除。"""

    request_review = Signal(str)   # task_id（查看候选/结果）
    request_cancel = Signal(str)   # task_id
    request_resume = Signal(str)   # task_id（cancelled/failed 完整建库 → 从检查点继续）
    request_remove = Signal(str)   # task_id（终态任务移出任务栏）

    STATUS_COLORS = {
        "queued": "#8a8f98",
        "running": "#e8a33d",
        "finished": "#5fbf77",
        "failed": "#d06a5a",
        "cancelled": "#8a8f98",
    }
    ACTIONS_WIDTH = 4 * 56  # 查看继续取消移除 四槽位固定宽 → 行间对齐

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.setObjectName("glossaryTaskStrip")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(0)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._rows: dict[str, dict] = {}
        self.refresh()

    # ---------------------------------------------------------------- 刷新
    def refresh(self):
        tasks = list(self.manager.tasks())
        finished = [t for t in tasks if t.status not in {"queued", "running"}]
        active = [t for t in tasks if t.status in {"queued", "running"}]
        tasks = active + finished[-3:]
        layout = self.layout()
        seen: set[str] = set()
        for task in tasks:
            seen.add(task.task_id)
            self._ensure_row(layout, task)
            self._update_row(task)
        for task_id in list(self._rows):
            if task_id not in seen:
                self._remove_row(layout, task_id)
        self.setVisible(bool(tasks))

    def _tick(self):
        if not self.isVisible():
            return
        for task in self.manager.tasks():
            if task.task_id in self._rows:
                self._update_row(task)

    # ---------------------------------------------------------------- 行构建
    def _ensure_row(self, layout, task):
        if task.task_id in self._rows:
            return
        if self._rows:
            separator = QFrame()
            separator.setFrameShape(QFrame.Shape.HLine)
            separator.setObjectName("glossaryTaskRowSeparator")
            separator.setFixedHeight(1)
            layout.addWidget(separator)
            self._rows.setdefault("__separators__", []).append(separator)
        row = QFrame()
        row.setObjectName("glossaryTaskRow")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(6, 5, 6, 5)
        row_layout.setSpacing(8)
        dot = QLabel("●")
        dot.setStyleSheet(f"color:{self.STATUS_COLORS.get(task.status, '#8a8f98')}; font-size:10px;")
        row_layout.addWidget(dot)
        title = QLabel("")
        title.setStyleSheet("font-weight:600;")
        row_layout.addWidget(title, 0)
        progress = QLabel("")
        progress.setObjectName("muted")
        row_layout.addWidget(progress, 1)
        elapsed = QLabel("")
        elapsed.setObjectName("muted")
        elapsed.setMinimumWidth(44)
        row_layout.addWidget(elapsed, 0)
        idle = QLabel("")
        idle.setObjectName("muted")
        row_layout.addWidget(idle, 0)
        # 操作区固定总宽：隐藏按钮不引起错位（P1 对齐）
        actions = QWidget()
        actions.setFixedWidth(self.ACTIONS_WIDTH)
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(4)
        review = AnimatedButton("查看")
        review.setObjectName("flat")
        review.setFixedWidth(52)
        _retain_size(review)
        review.clicked.connect(
            lambda _checked=False, tid=task.task_id: self.request_review.emit(tid)
        )
        actions_layout.addWidget(review)
        resume = AnimatedButton("继续")
        resume.setObjectName("flat")
        resume.setFixedWidth(52)
        _retain_size(resume)
        resume.clicked.connect(
            lambda _checked=False, tid=task.task_id: self.request_resume.emit(tid)
        )
        actions_layout.addWidget(resume)
        cancel = AnimatedButton("取消")
        cancel.setObjectName("flat")
        cancel.setFixedWidth(52)
        cancel.setStyleSheet("color:#d06a5a;")
        _retain_size(cancel)
        cancel.clicked.connect(
            lambda _checked=False, tid=task.task_id: self.request_cancel.emit(tid)
        )
        actions_layout.addWidget(cancel)
        remove = AnimatedButton("×")
        remove.setObjectName("flat")
        remove.setFixedWidth(28)
        _retain_size(remove)
        bind_text(remove, '从任务栏移除（不影响已入库结果）', property='toolTip')
        remove.clicked.connect(
            lambda _checked=False, tid=task.task_id: self.request_remove.emit(tid)
        )
        actions_layout.addWidget(remove)
        row_layout.addWidget(actions, 0)
        layout.addWidget(row)
        self._rows[task.task_id] = {
            "frame": row, "dot": dot, "title": title, "progress": progress,
            "elapsed": elapsed, "idle": idle, "review": review,
            "resume": resume, "cancel": cancel, "remove": remove,
        }

    def _remove_row(self, layout, task_id: str):
        row = self._rows.pop(task_id, None)
        if row is None:
            return
        row["frame"].setParent(None)
        row["frame"].deleteLater()

    def _update_row(self, task):
        row = self._rows.get(task.task_id)
        if row is None:
            return
        row["dot"].setStyleSheet(
            f"color:{self.STATUS_COLORS.get(task.status, '#8a8f98')}; font-size:10px;"
        )
        ai_bits = [bit for bit in (task.service_label, task.model_label) if bit]
        row["title"].setText(f"{task.game} · {task.mode_label}" + (f"（{' / '.join(ai_bits)}）" if ai_bits else ""))
        row["progress"].setText(task.progress_line())
        no_runtime = task.status == "queued" or (
            task.status == "cancelled" and not task.started
        )
        if no_runtime:
            row["elapsed"].setText("--:--")  # 排队（及排队即取消）没有真实耗时
        else:
            minutes, seconds = divmod(task.elapsed_seconds(), 60)
            row["elapsed"].setText(f"{minutes:02d}:{seconds:02d}")
        idle = task.idle_seconds()
        # 等待锚点时 progress_line 已含"已等待 Ns"，这里不重复显示
        (bind_text(row['idle'], '') if getattr(task, 'waiting_note', '') else (bind_text(row['idle'], '· {value0}s 无事件', value0=idle) if idle > 20 and task.status == 'running' else bind_text(row['idle'], '')))
        active = task.status in {"queued", "running"}
        terminal = task.status in {"finished", "failed", "cancelled", "partial"}
        row["review"].setVisible(not no_runtime)   # 排队/未开始：无数据可看
        row["review"].setEnabled(not no_runtime)
        row["cancel"].setVisible(active and not task.cancel_requested)
        row["remove"].setVisible(terminal)
        can_resume = (
            task.mode == "full"
            and task.status in {"cancelled", "failed", "partial"}
            and bool(getattr(task, "started", False))
        )
        row["resume"].setVisible(can_resume)
