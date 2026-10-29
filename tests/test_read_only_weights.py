"""2026-10-15: model workers map weight files read-only on Windows (os error 1455)."""
import importlib
from pathlib import Path

import pytest

torch = pytest.importorskip('torch')
safetensors = pytest.importorskip('safetensors')
safetensors_torch = pytest.importorskip('safetensors.torch')

from twobyteasr import read_only_weights  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _sample(path):
    tensors = {'w': torch.randn(3, 5).to(torch.bfloat16), 'b': torch.randn(7), 'ids': torch.arange(4, dtype=torch.int64),
               'scalar': torch.tensor(2.5, dtype=torch.float16), 'empty': torch.zeros(0, 3), 'flag': torch.tensor([True, False])}
    safetensors_torch.save_file(tensors, str(path), metadata={'format': 'pt'})
    return tensors


def test_safe_open_reads_the_same_tensors_through_a_read_only_view(tmp_path):
    path = tmp_path / 'model.safetensors'
    original = _sample(path)
    official = safetensors.safe_open
    with read_only_weights.read_only_weight_files(torch) as views:
        from safetensors import safe_open
        assert safe_open is not official and safetensors_torch.safe_open is not official
        with safe_open(str(path), framework='pt', device='cpu') as handle:
            assert handle.keys() == sorted(original)
            assert handle.metadata() == {'format': 'pt'}
            for name, tensor in original.items():
                loaded = handle.get_tensor(name)
                assert loaded.dtype == tensor.dtype and loaded.shape == tensor.shape and torch.equal(loaded, tensor)
                assert views.holds(loaded) == bool(tensor.numel())
            part = handle.get_slice('w')
            assert part.get_shape() == [3, 5] and part.get_dtype() == 'BF16'
            assert torch.equal(part[1:], original['w'][1:]) and torch.equal(part[...], original['w'])
        loaded = safetensors_torch.load_file(str(path))
        assert all(torch.equal(loaded[name], tensor) for name, tensor in original.items())
        del loaded, part
    views.close()
    assert safetensors.safe_open is official and safetensors_torch.safe_open is official


def test_torch_load_maps_the_checkpoint_read_only(tmp_path):
    from torch.utils.serialization import config
    path = tmp_path / 'model.pth.tar'
    state = {'encoder.weight': torch.randn(4, 6), 'decoder.bias': torch.randn(3).half()}
    torch.save({'model_state_dict': state, 'args': {'layers': 2}}, path)
    with read_only_weights.read_only_weight_files(torch, torch_load_mmap=True) as views:
        assert config.load.mmap is True
        package = torch.load(path, map_location=lambda storage, location: storage, weights_only=True)
        assert package['args'] == {'layers': 2}
        for name, tensor in state.items():
            assert torch.equal(package['model_state_dict'][name], tensor)
            assert views.holds(package['model_state_dict'][name])
    assert 'from_file' not in torch.UntypedStorage.__dict__ and config.load.mmap is False
    del package
    views.close()


def test_detach_copies_parameters_left_in_a_view(tmp_path):
    path = tmp_path / 'model.safetensors'
    weight = torch.randn(4, 3)
    safetensors_torch.save_file({'weight': weight, 'bias': torch.randn(4)}, str(path))
    with read_only_weights.read_only_weight_files(torch) as views:
        module = torch.nn.Linear(3, 4)
        module.load_state_dict(safetensors_torch.load_file(str(path)), assign=True)
    assert views.holds(module.weight) and views.holds(module.bias)
    assert views.detach(module) == 2
    assert not views.holds(module.weight) and torch.equal(module.weight, weight)
    module.weight.data.mul_(2)  # writable again
    views.close()


def test_load_reports_a_problem_and_uses_the_official_loading(monkeypatch):
    monkeypatch.setattr(read_only_weights, 'ENABLED', True)
    calls, reports = [], []

    def loader():
        calls.append('from_file' in torch.UntypedStorage.__dict__)
        if len(calls) == 1:
            raise OSError('broken header')
        return 'model'

    result = read_only_weights.load(torch, loader, lambda model: [], report=lambda *args: reports.append(args))
    assert result == ('model', 'official')
    assert calls == [True, False] and reports == [('OSError', 'broken header')]
    assert read_only_weights.load(torch, lambda: torch.nn.Linear(1, 1), lambda model: [model])[1] == 'read_only_map'
    monkeypatch.setattr(read_only_weights, 'ENABLED', False)
    hooked = []
    assert read_only_weights.load(torch, lambda: hooked.append('from_file' in torch.UntypedStorage.__dict__) or 'plain',
                                  lambda model: []) == ('plain', 'official')
    assert hooked == [False]


def test_switch_and_platform(monkeypatch):
    monkeypatch.setenv('TWOBYTEASR_READ_ONLY_WEIGHTS', '0')
    try:
        assert importlib.reload(read_only_weights).ENABLED is False
    finally:
        monkeypatch.delenv('TWOBYTEASR_READ_ONLY_WEIGHTS')
        importlib.reload(read_only_weights)
    import os
    assert read_only_weights.ENABLED is (os.name == 'nt')


def test_moss_worker_loads_the_module_by_path():
    """The 3.12 MOSS runtime cannot import the twobyteasr package; it loads this one file."""
    import moss_worker
    module = moss_worker._read_only_weights(ROOT)
    assert module.__name__ == 'twobyteasr_read_only_weights' and callable(module.read_only_weight_files)
