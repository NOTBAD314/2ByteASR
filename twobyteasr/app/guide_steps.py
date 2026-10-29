"""Walkthrough step helpers shared by the setup guides (2026-10-14, slimmed 2026-10-18).

The picture step cards (``StepCards``) gave way to the one-step-at-a-time
walkthrough of 「申请与设置 API」 (user, 2026-10-18: the boxed five-card row
looked uncertain and heavy). What stays here: the step record, the icon each
step role uses (qtawesome Phosphor names, drawn in the theme's colours), and
``topup_step``, which other code and tests read to know whether a service
asks for credit first.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

ICONS = ('account', 'globe', 'key', 'paste', 'check', 'download', 'folder', 'chat', 'coin')

# Step role -> icon (shown when a step has no screenshot of the official page).
STEP_ICONS = {'account': 'ph.user-circle', 'topup': 'ph.coin', 'key': 'ph.key', 'storage': 'ph.hard-drives',
              'paste': 'ph.clipboard-text', 'fill': 'ph.chat-circle-text'}


@dataclass(frozen=True)
class GuideStep:
    title: str
    icon: str = 'check'
    action_label: str = ''
    url: str = ''
    callback: Callable[[], None] | None = None


def topup_step(guide) -> GuideStep | None:
    """“先充值” (2026-10-15, user: many people do not know a key needs credit).

    Only for services whose guide links a top-up or billing page; a service
    that gives free credit to try with first (MOSS 云端, 2026-10-18) has none.
    """
    from ..providers.api_setup_catalog import walkthrough
    step = next((item for item in walkthrough(guide) if item.role == 'topup'), None)
    if step is None:
        return None
    return GuideStep(step.title, 'coin', '打开网页', step.url)
