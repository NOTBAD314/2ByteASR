"""Detailed first-run setup dialog: every recognition role and model, with
presets for this computer (CUDA, Apple Silicon, online).

The quick chooser is ``app/quick_setup.py``; the first-run flow that opens
either one (``_offer_first_run_setup`` and friends) stays in ``app/ui.py``
because it saves through ``persist_asr_configuration`` there.
Split out of ``app/ui.py`` on 2026-10-15; ``ui`` still exports the dialog.
Tests that fake the CUDA probe patch ``detect_cuda_runtime`` on this module.
"""
from __future__ import annotations

import sys
import threading

from PySide6.QtCore import QObject, QSignalBlocker, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QVBoxLayout,
)

from ..design.main_ui_dialogs import SpringDialog
from ..design.main_ui_popup import FramelessPopupCombo
from ..design.ui_widgets import AnimatedButton
from ..i18n import LANGUAGE_NATIVE_NAMES, bind_text, current_language, save_language, tr
from ..system.hardware import detect_cuda_runtime


class _CudaProbeRelay(QObject):
    """Carries the background CUDA probe result to the GUI thread."""

    finished = Signal(object)


class GuidedSetupDialog(SpringDialog):
    """First-run model-combination chooser. Nothing is downloaded implicitly."""

    cuda_probe_finished = Signal(object)

    PRESETS = {
        "quality": ("moss", "local", "local"),
        "light": ("sensevoice", "off", "off"),
        "online": ("api", "off", "off"),
        # Cloud text + local word times; the aligner runs on the CPU without CUDA.
        "online_align": ("api", "qwen_aligner", "off"),
        "custom": ("none", "off", "off"),
    }
    SIZES = {
        "mlx_qwen3_asr": 1.0,
        "mlx_qwen3_asr_1_7b": 2.5,
        "mlx_qwen_aligner": 1.3,
        "moss": 1.7,
        "firered": 4.4,
        "qwen_local": 4.7,
        "whisper_turbo": 1.6,
        "sensevoice": 0.9,
        "paraformer": 1.0,
        "funasr_nano": 2.4,
        "local_timeline": 4.4,
        "qwen_aligner": 1.8,
        "local_review": 4.7,
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.open_workshop = False
        self.auto_download = False
        self._applying_preset = False
        self._cuda_status = None
        self._cuda_probe_started = False
        self.cuda_probe_finished.connect(self._cuda_probe_ready)
        # Presets follow this computer (2026-10-13): Apple Silicon gets the MLX
        # plan instead of the CUDA one; an Intel Mac has no local plan.
        from ..recognition.mlx_backend import platform_supported
        self._apple_silicon = platform_supported()
        self._intel_mac = sys.platform == "darwin" and not self._apple_silicon
        self.PRESETS = dict(type(self).PRESETS)
        if self._apple_silicon:
            self.PRESETS["apple_local"] = ("mlx_qwen3_asr", "mlx_qwen_aligner", "off")
            self.PRESETS["online_align"] = ("api", "mlx_qwen_aligner", "off")
        bind_text(self, '首次使用设置 - 2ByteASR', property='windowTitle')
        self.setMinimumSize(760, 610)
        self.resize(820, 760)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("先选择一套字幕识别组合")
        title.setStyleSheet("font-size: 21px; font-weight: 700;")
        title_box.addWidget(title)
        hint = QLabel("随时可以在模型工坊替换。这里不会偷偷下载任何模型。")
        hint.setObjectName("muted")
        title_box.addWidget(hint)
        header.addLayout(title_box, 1)
        self.lang_combo = FramelessPopupCombo()
        for code, label in LANGUAGE_NATIVE_NAMES.items():
            self.lang_combo.addItem(label, code)
        self.lang_combo.setCurrentIndex(max(0, self.lang_combo.findData(current_language())))
        self.lang_combo.currentIndexChanged.connect(self._change_lang)
        header.addWidget(self.lang_combo)
        layout.addLayout(header)

        preset_heading = QLabel("① 先选择一种使用方式")
        preset_heading.setStyleSheet("font-size: 15px; font-weight: 700;")
        layout.addWidget(preset_heading)
        preset_hint = QLabel("选中的方案会用绿色边框标出；下方仍可逐项调整模型。")
        preset_hint.setObjectName("muted")
        layout.addWidget(preset_hint)

        preset_row = QGridLayout()
        preset_row.setSpacing(10)
        self.preset_group = QButtonGroup(self)
        online_align_note = "上传音频；本机补字级时间"
        preset_copy = (
            ("quality", "质量优先", "MOSS + FireRed + Qwen"),
            ("light", "快速轻量", "CPU 友好，小体积"),
            ("online", "在线疾速", "免下载，需要 API Key"),
            ("online_align", "云端 + 本地对齐", online_align_note),
            ("custom", "稍后决定", "先看界面，不下载"),
        )
        if self._apple_silicon:
            preset_copy = (("apple_local", "Mac 本地识别", "M 系列芯片，不上传音频"),) + preset_copy[1:]
        elif self._intel_mac:
            # No PyTorch or MLX build exists for Intel Macs: cloud only.
            preset_copy = tuple(row for row in preset_copy if row[0] in {"online", "custom"})
        columns = 3 if len(preset_copy) > 4 else max(1, len(preset_copy))
        for index, (key, label, note) in enumerate(preset_copy):
            button = QPushButton(f"{label}\n{note}")
            button.setCheckable(True)
            button.setMinimumHeight(98)
            button.setProperty("preset", key)
            button.setObjectName("presetCard")
            # Equal columns; every note fits at the dialog's minimum width.
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            self.preset_group.addButton(button, index)
            preset_row.addWidget(button, index // columns, index % columns)
        for column in range(columns):
            preset_row.setColumnStretch(column, 1)
        self.preset_group.buttonClicked.connect(self._preset_clicked)
        layout.addLayout(preset_row)

        panel = QFrame()
        panel.setObjectName("surface")
        form = QFormLayout(panel)
        form.setContentsMargins(18, 18, 18, 18)
        form.setSpacing(12)
        self.primary_combo = FramelessPopupCombo()
        for label, value in (
            ("MOSS（推荐，长音频与说话人区分）", "moss"),
            ("FireRedASR2-AED（中文与方言）", "firered"),
            ("Qwen3-ASR 1.7B 本地", "qwen_local"),
            ("FireRedASR2-LLM 本地", "firered_llm"),
            ("Whisper large-v3-turbo", "whisper_turbo"),
            ("SenseVoice Small（CPU 友好）", "sensevoice"),
            ("Paraformer（中文快速）", "paraformer"),
            ("Fun-ASR Nano（中文与方言）", "funasr_nano"),
            *((("Qwen3-ASR 0.6B（Apple Silicon · MLX）", "mlx_qwen3_asr"),
               ("Qwen3-ASR 1.7B（Apple Silicon · MLX）", "mlx_qwen3_asr_1_7b")) if self._apple_silicon else ()),
            ("在线 ASR API", "api"),
            ("尚未选择", "none"),
        ):
            self.primary_combo.addItem(label, value)
        self.timeline_combo = FramelessPopupCombo()
        for label, value in (
            ("FireRed 字幕时间轴（字级，推荐）", "local"),
            ("Qwen3 ForcedAligner 字幕时间轴", "qwen_aligner"),
            ("Whisper 字幕时间轴（短块级）", "whisper_turbo"),
            ("Paraformer 字幕时间轴", "paraformer"),
            *((("Qwen3 ForcedAligner 字幕时间轴（Apple Silicon · MLX）", "mlx_qwen_aligner"),)
              if self._apple_silicon else ()),
            ("不生成字幕时间轴（仅 TXT）", "off"),
        ):
            self.timeline_combo.addItem(label, value)
        self.review_combo = FramelessPopupCombo()
        for label, value in (
            ("Qwen3-ASR 本地复核（更准确）", "local"),
            ("FireRedASR2-LLM 本地复核", "firered_llm"),
            ("在线 ASR API 复核", "api"),
            ("Whisper 本地复核", "whisper_turbo"),
            ("SenseVoice 本地复核", "sensevoice"),
            ("Fun-ASR Nano 本地复核", "funasr_nano"),
            ("不使用独立文字复核", "off"),
        ):
            self.review_combo.addItem(label, value)
        form.addRow("主力转写", self.primary_combo)
        form.addRow("字幕时间轴", self.timeline_combo)
        form.addRow("文字复核", self.review_combo)
        layout.addWidget(panel)

        self.combo_summary = QLabel()
        self.combo_summary.setWordWrap(True)
        self.combo_summary.setObjectName("muted")
        layout.addWidget(self.combo_summary)
        self.gpu_info = QLabel()
        self.gpu_info.setWordWrap(True)
        layout.addWidget(self.gpu_info)
        for combo in (self.primary_combo, self.timeline_combo, self.review_combo):
            combo.currentIndexChanged.connect(self._selection_changed)

        layout.addStretch(1)
        actions = QHBoxLayout()
        reminder = QLabel("模型可断点续传，缺少时会在开始任务前明确提示。")
        reminder.setObjectName("muted")
        actions.addWidget(reminder, 1)
        browse = AnimatedButton("只保存，暂不下载")
        browse.setObjectName("outline")
        browse.clicked.connect(self._accept_workshop)
        actions.addWidget(browse)
        self.install_button = AnimatedButton("确认组合并一键安装")
        start = self.install_button
        start.setObjectName("primary")
        start.clicked.connect(self._accept_install)
        actions.addWidget(start)
        layout.addLayout(actions)

        self.preset_group.button(0).setChecked(True)
        self._apply_preset(str(self.preset_group.button(0).property("preset")))
        self._start_cuda_probe()

    def _set_combo(self, combo, value):
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _preset_clicked(self, button):
        self._apply_preset(str(button.property("preset")))

    def _apply_preset(self, key):
        if self._applying_preset:
            return
        self._applying_preset = True
        try:
            primary, timeline, review = self.PRESETS[key]
            blockers = [
                QSignalBlocker(self.primary_combo),
                QSignalBlocker(self.timeline_combo),
                QSignalBlocker(self.review_combo),
            ]
            self._set_combo(self.primary_combo, primary)
            self._set_combo(self.timeline_combo, timeline)
            self._set_combo(self.review_combo, review)
            del blockers
            self._selection_changed()
        finally:
            self._applying_preset = False

    def _start_cuda_probe(self):
        if self._cuda_probe_started:
            return
        self._cuda_probe_started = True

        # The thread holds only a child relay, never the dialog: if the dialog
        # is closed before the probe ends, its last reference must not be
        # dropped (and the widget destroyed) on this thread (2026-10-14,
        # 0xC0000374 at teardown). A deleted relay just refuses the emit.
        relay = _CudaProbeRelay(self)
        relay.finished.connect(self.cuda_probe_finished)

        def probe():
            try:
                status = detect_cuda_runtime()
            except Exception:
                status = None
            try:
                relay.finished.emit(status)
            except RuntimeError:
                pass

        threading.Thread(target=probe, name="2ByteASR-CUDA-probe", daemon=True).start()

    def _cuda_probe_ready(self, status):
        self._cuda_status = status
        self._selection_changed()

    def _selection_changed(self, *_args):
        primary = str(self.primary_combo.currentData())
        timeline = str(self.timeline_combo.currentData())
        review = str(self.review_combo.currentData())
        selected_tuple = (primary, timeline, review)
        matched_preset = next(
            (key for key, values in self.PRESETS.items() if values == selected_tuple),
            None,
        )
        self.preset_group.setExclusive(False)
        for button in self.preset_group.buttons():
            button.setChecked(button.property("preset") == matched_preset)
        self.preset_group.setExclusive(True)
        size = self.estimate_size(primary, timeline, review)
        notes = []
        if primary not in {"moss", "none", "api"}:
            notes.append("非 MOSS 主力当前按单说话人输出")
        if primary in {"mlx_qwen3_asr", "mlx_qwen3_asr_1_7b"}:
            notes.append("只按语音段给文字，字词时间由对齐模型补上")
        if primary == "api" and timeline == "off":
            notes.append("时间精度取决于所选云端服务（有的只有句段时间）")
        if primary == "api" or review == "api":
            notes.append("需要在“申请与设置 API”里填写 API Key，识别时会上传音频")
        if primary == "none":
            notes.append("运行字幕前必须在模型工坊选择主力模型")
        if primary == "none":
            bind_text(self.install_button, '保存并打开模型工坊')
        elif primary == "api":
            bind_text(self.install_button, '保存并配置在线模型')
        else:
            bind_text(self.install_button, '确认组合并一键安装')
        bind_text(self.combo_summary, '预计模型下载约 {value0:.1f} GB。{value1}', value0=size, value1='；'.join(notes) if notes else tr('推荐用于中文长视频与多人内容。'))
        from twobyteasr.system.hardware import selected_cuda_components

        settings = {
            "models": {
                "primary_asr_backend": primary,
                "firered_asr_backend": timeline,
                "qwen_asr_backend": review,
            }
        }
        required = selected_cuda_components(settings)
        if not required:
            self.gpu_info.setObjectName("statusGood")
            bind_text(self.gpu_info, '这套组合不强制要求 NVIDIA CUDA，可在 CPU 或在线模式下开始。')
        elif self._cuda_status is None:
            self.gpu_info.setObjectName("muted")
            bind_text(self.gpu_info, '正在后台检查 CUDA；需要 CUDA 的组件：{value0}。选择组合时无需等待检查完成。', value0='、'.join(required))
        elif self._cuda_status.ready:
            self.gpu_info.setObjectName("statusGood")
            bind_text(self.gpu_info, 'CUDA 已就绪：{value0}。需要 CUDA 的组件：{value1}', value0=self._cuda_status.gpu_name, value1='、'.join(required))
        elif getattr(self._cuda_status, "code", "") == "torch_missing" and self._cuda_status.gpu_name:
            # A fresh install has no PyTorch yet; one-click install brings the CUDA build.
            self.gpu_info.setObjectName("statusGood")
            bind_text(self.gpu_info, '已检测到 NVIDIA 显卡：{value0}。一键安装会同时装好 CUDA 版 PyTorch。需要 CUDA 的组件：{value1}', value0=self._cuda_status.gpu_name, value1='、'.join(required))
        elif getattr(self._cuda_status, "code", "") == "torch_missing":
            self.gpu_info.setObjectName("statusBad")
            bind_text(self.gpu_info, '未检测到 NVIDIA 显卡或驱动，{value0} 需要 NVIDIA CUDA。可换成轻量/在线组合，或安装/更新 NVIDIA 显卡驱动后再安装。', value0='、'.join(required))
        else:
            self.gpu_info.setObjectName("statusBad")
            bind_text(self.gpu_info, '当前设备还不能运行：{value0}。可换成轻量/在线组合，或修复 NVIDIA 驱动与 PyTorch。', value0='、'.join(required))
        assessment = self._vram_assessment()
        if (required and self.gpu_info.objectName() == "statusGood" and assessment is not None
                and assessment.level in {"insufficient", "tight", "unknown"}):
            # The card is there; its memory may not be (2026-10-15, RTX 2060 6 GB report).
            from ..system.vram_check import inline_text
            self.gpu_info.setObjectName("statusWarn")
            bind_text(self.gpu_info, inline_text(assessment))
        self.gpu_info.style().unpolish(self.gpu_info)
        self.gpu_info.style().polish(self.gpu_info)

    @classmethod
    def estimate_size(cls, primary, timeline, review) -> float:
        """Approximate download in GB for one combination (shared with the quick chooser)."""
        size = cls.SIZES.get(primary, 0.0)
        if timeline == "local" and primary != "firered":
            size += cls.SIZES["local_timeline"]
        elif timeline in {"qwen_aligner", "mlx_qwen_aligner"}:
            size += cls.SIZES[timeline]
        elif timeline == "whisper_turbo" and primary != "whisper_turbo":
            size += cls.SIZES["whisper_turbo"]
        elif timeline == "paraformer" and primary != "paraformer":
            size += cls.SIZES["paraformer"]
        if review == "local" and primary != "qwen_local":
            size += cls.SIZES["local_review"]
        elif review not in {"off", "api", "local"} and review != primary:
            size += cls.SIZES.get(review, 0.0)
        return size

    def selected_backends(self):
        return (
            str(self.primary_combo.currentData()),
            str(self.timeline_combo.currentData()),
            str(self.review_combo.currentData()),
        )

    def selected_download_keys(self):
        return self.download_keys_for(*self.selected_backends())

    @staticmethod
    def download_keys_for(primary, timeline, review):
        primary_keys = {
            "moss": "moss",
            "firered": "firered_aed",
            "qwen_local": "qwen_asr",
            "whisper_turbo": "whisper_turbo",
            "sensevoice": "sensevoice",
            "paraformer": "paraformer",
            "funasr_nano": "funasr_nano",
            "glm_asr_nano": "glm_asr_nano",
            "canary_qwen": "canary_qwen",
            "mlx_qwen3_asr": "mlx_qwen3_asr_0_6b",
            "mlx_qwen3_asr_1_7b": "mlx_qwen3_asr_1_7b",
        }
        timeline_keys = {
            "local": "firered_aed",
            "qwen_aligner": "qwen_aligner",
            "mlx_qwen_aligner": "mlx_qwen_aligner",
            "whisper_turbo": "whisper_turbo",
            "paraformer": "paraformer",
        }
        review_keys = {
            "local": "qwen_asr",
            "whisper_turbo": "whisper_turbo",
            "sensevoice": "sensevoice",
            "funasr_nano": "funasr_nano",
        }
        return tuple(
            dict.fromkeys(
                key
                for key in (
                    primary_keys.get(primary),
                    timeline_keys.get(timeline),
                    review_keys.get(review),
                )
                if key
            )
        )

    def _vram_assessment(self):
        """How the selected local models fit this graphics card; None until the probe ends."""
        if self._cuda_status is None or sys.platform == "darwin":
            return None
        from ..system import vram_check
        return vram_check.assess(self.selected_download_keys(),
                                 vram_check.inventory_from_cuda_status(self._cuda_status))

    def _ask_vram(self, assessment) -> str:
        """'online' (改用 MOSS Pro 云端), 'keep' (仍然安装) or 'cancel'."""
        from PySide6.QtWidgets import QMessageBox
        from ..system.vram_check import warning_text
        title, body = warning_text(assessment)
        box = QMessageBox(QMessageBox.Icon.Warning, title, body, QMessageBox.StandardButton.NoButton, self)
        box.setObjectName("vramReminder")
        online = box.addButton(tr("改用 MOSS Pro 云端"), QMessageBox.ButtonRole.AcceptRole)
        keep = box.addButton(tr("仍然安装"), QMessageBox.ButtonRole.ActionRole)
        box.addButton(tr("返回"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(online)
        box.exec()
        return {id(online): "online", id(keep): "keep"}.get(id(box.clickedButton()), "cancel")

    def _accept_install(self):
        # 2026-10-15: remind before one-click install when the card is too
        # small, has no readable memory, or is not NVIDIA. Only a reminder.
        from ..system import vram_check
        keys = self.selected_download_keys()
        assessment = self._vram_assessment()
        if (assessment is not None and assessment.level in {"insufficient", "tight", "unknown", "no_nvidia"}
                and not vram_check.acknowledged(keys)):
            answer = self._ask_vram(assessment)
            if answer == "online":
                # Switch the combination to online recognition and stay here:
                # the button then reads 保存并配置在线模型.
                self._apply_preset("online")
                return
            if answer != "keep":
                return
            # Later workshop downloads of these models do not ask again.
            vram_check.acknowledge(keys)
        self.open_workshop = True
        self.auto_download = True
        self.accept()

    def _accept_workshop(self):
        self.open_workshop = True
        self.auto_download = False
        self.accept()

    def _change_lang(self, index):
        code = self.lang_combo.itemData(index) or "zh"
        save_language(code)
