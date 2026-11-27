"""兔白's plush physics (2026-11-26, feel B): pendulum from the grab point, gravity, parts that swing."""
from __future__ import annotations

import math

from twobyteasr.design import bunny_physics as bp

SCALE = 150 / 664
BOUNDS = (0.0, 0.0, 1100.0, 720.0)


def _held(local, link=False, at=(500.0, 200.0)):
    body = bp.BodyPhysics(SCALE)
    body.pose.x, body.pose.y = at[0], at[1] + 80
    world = body.pose.world(*local)
    body.grab(local, world, link)
    return body, list(world)


def _hold_still(body, target, seconds):
    for _ in range(int(seconds / bp.STEP)):
        body.step_held(bp.STEP, tuple(target), BOUNDS)


def test_held_by_the_ring_she_hangs_upright():
    body, target = _held(bp.RING_TOP, link=True)
    _hold_still(body, target, 4)
    assert abs(bp.wrap(body.pose.angle)) < math.radians(4)
    top = body.pose.world(*bp.RING_TOP)
    assert math.hypot(top[0] - target[0], top[1] - target[1]) < 25   # the ring slid onto the finger
    assert body.pose.y > target[1]


def test_held_by_a_foot_she_hangs_upside_down():
    body, target = _held(bp.FEET)
    body.pose.angle = 0.3              # a nudge off the unstable balance
    _hold_still(body, target, 6)
    assert abs(abs(bp.wrap(body.pose.angle)) - math.pi) < math.radians(8)
    assert body.pose.y > target[1]                   # her head below the hand


def _swing(distance):
    body, target = _held(bp.RING_TOP, link=True)
    _hold_still(body, target, 3)
    steps = 40
    peak = 0.0
    for i in range(steps):                           # a quick move sideways, then the hand stops
        target[0] -= distance / steps
        body.step_held(bp.STEP, tuple(target), BOUNDS)
    for _ in range(int(2 / bp.STEP)):
        body.step_held(bp.STEP, tuple(target), BOUNDS)
        peak = max(peak, abs(bp.wrap(body.pose.angle)))
    return peak, body


def test_a_bigger_swing_of_the_hand_swings_her_more_and_it_dies_down():
    small, _ = _swing(40)
    big, body = _swing(240)
    assert small > math.radians(3)
    assert big > small * 2
    assert big < bp.SOFT_LIMIT + 0.6                 # no loop over the top
    _hold_still(body, (body.hold.hand[0], body.hold.hand[1]), 6)
    assert abs(bp.wrap(body.pose.angle)) < math.radians(5)


def test_shaking_her_makes_her_dizzy():
    body, target = _held(bp.HEAD)
    for i in range(int(1.0 / bp.STEP)):
        target[0] = 500 + 120 * math.sin(i * bp.STEP * 2 * math.pi * 3)
        body.step_held(bp.STEP, tuple(target), BOUNDS)
    assert body.release((0.0, 0.0))


def test_thrown_she_falls_bounces_and_comes_to_rest_inside_the_window():
    body = bp.BodyPhysics(SCALE)
    body.pose.x, body.pose.y = 300.0, 200.0
    body.release((1800.0, -900.0))
    r = body.radius()
    for _ in range(int(10 / bp.STEP)):
        hits = body.step_fly(bp.STEP, BOUNDS)
        for side, speed, x, y in hits:
            assert side in ('left', 'right', 'top', 'bottom') and speed > 0
        assert r - 1e-6 <= body.pose.x <= BOUNDS[2] - r + 1e-6
        assert body.pose.y <= BOUNDS[3] - r + 1e-6
        if body.stopped():
            break
    assert body.stopped() and body.on_floor
    assert abs(body.pose.y - (BOUNDS[3] - r)) < 1


def test_lying_upside_down_she_hops_upright():
    body = bp.BodyPhysics(SCALE)
    body.pose.x, body.pose.y, body.pose.angle = 500.0, BOUNDS[3] - body.radius(), 2.6
    body.release((0.0, 0.0))
    assert body.lying()
    body.hop_upright()
    for _ in range(int(3 / bp.STEP)):
        body.step_fly(bp.STEP, BOUNDS)
        if body.flight_s > 0.05 and body.stopped():
            break
    assert not body.lying()


def test_still_parts_keep_their_drawn_pose():
    rig = bp.Rig()
    pose = bp.Pose(400, 300, 0.0, SCALE)
    rig.advance(0, pose)
    for _ in range(60):
        rig.advance(1 / 60, pose)
    assert all(abs(state.angle) < 1e-3 for state in rig.parts.values())


def test_a_jolt_swings_her_ears_and_they_settle():
    rig = bp.Rig()
    pose = bp.Pose(400, 300, 0.0, SCALE)
    rig.advance(0, pose)
    swing = 0.0
    for i in range(120):
        x = 400 + (60 if i >= 10 else 0) * min(1.0, (i - 9) / 4) if i >= 10 else 400
        rig.advance(1 / 60, bp.Pose(x, 300, 0.0, SCALE))
        swing = max(swing, abs(rig.parts['earL'].angle))
    assert swing > math.radians(5)
    for _ in range(240):
        rig.advance(1 / 60, bp.Pose(460, 300, 0.0, SCALE))
    assert abs(rig.parts['earL'].angle) < math.radians(1)


def test_upside_down_her_ears_hang_the_other_way():
    rig = bp.Rig()
    rig.advance(0, bp.Pose(400, 300, 0.0, SCALE))
    for i in range(240):
        rig.advance(1 / 60, bp.Pose(400, 300, min(math.pi, i * 0.05), SCALE))
    # Upside down, gravity bends the ears away from the pose they were drawn to hold up.
    assert abs(rig.parts['earL'].angle) > 0.1 and abs(rig.parts['earR'].angle) > 0.1
