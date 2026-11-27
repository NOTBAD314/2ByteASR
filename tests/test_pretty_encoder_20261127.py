"""frozen_json_text.pretty: its own encoder, text identical to json (2026-11-27).

The formal save spent about half its time in json's pure-Python indent path.
"""
import json
import math
import random

import pytest

from twobyteasr.projects.frozen_json_text import pretty


def _fuzz(rng, depth=0):
    kind = rng.randrange(9 if depth < 4 else 6)
    if kind == 0:
        return rng.choice([None, True, False])
    if kind == 1:
        return rng.randrange(-10**20, 10**20)
    if kind == 2:
        return rng.choice([0.0, -0.0, 1e-7, 1e16, 3.14, math.nan, math.inf, -math.inf, rng.random()])
    if kind in (3, 4, 5):
        return "".join(rng.choice('{}[],:"\\ \n\t\x00\x1fab中文😀 ') for _ in range(rng.randrange(12)))
    if kind == 6:
        return [_fuzz(rng, depth + 1) for _ in range(rng.randrange(5))]
    if kind == 7:
        return tuple(_fuzz(rng, depth + 1) for _ in range(rng.randrange(4)))
    return {str(_fuzz(rng, 9)): _fuzz(rng, depth + 1) for _ in range(rng.randrange(5))}


EDGE_VALUES = [None, 1, -1.5, "", "{}[],:", '"q" \\', [], {}, [[]], [{}], {"a": []}, {"a": {}},
               {"x": [1, [2, [3, {}]]], "y": {"z": [[], {}]}}, (1, 2), [(), ()], {2: "a", 10: "b"},
               {True: 1}, {None: 1}, {1.5: 2}, {"k": "a\nb"}, 10**30, math.nan, [math.inf, -math.inf]]


def test_pretty_is_json_dumps_with_indent():
    rng = random.Random(20261127)
    for value in EDGE_VALUES + [_fuzz(rng) for _ in range(3000)]:
        assert pretty(value) == json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def test_pretty_raises_like_json():
    for value in ({"a": object()}, {(1, 2): 3}, {1: "x", "a": "y"}):
        with pytest.raises(TypeError):
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
        with pytest.raises(TypeError):
            pretty(value)
    loop = []
    loop.append(loop)
    with pytest.raises(ValueError):
        pretty(loop)
