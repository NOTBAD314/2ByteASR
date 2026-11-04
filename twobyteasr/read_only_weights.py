"""Read-only views of model weight files while a local model worker loads them.

2026-10-15: on Windows, safetensors and ``torch.load(mmap=True)`` map weight
files copy-on-write (safetensors' ``safe_open`` briefly holds a second such
view of its own), and Windows charges a copy-on-write view in full against the
system commit limit (RAM plus page file) although nothing writes to it. Loading
Qwen3-ASR 1.7B or FireRedASR2-AED needed about 14 GB of commit, and PCs with a
small page file failed with os error 1455 ("页面文件太小"). A read-only view is
charged nothing.

Inside ``read_only_weight_files`` the official loaders run unchanged; only how
the files are mapped differs: ``safe_open`` reads through a read-only view and
``torch.UntypedStorage.from_file`` (what ``torch.load(mmap=True)`` uses)
returns one. Model classes, config, dtype and device placement stay the
official ones. The files have been checked against their locked hashes before.
A tensor that stays on the CPU in the file's dtype would still point into a
read-only view; ``ReadOnlyViews.detach`` copies those before inference.

Stdlib only at import: moss_worker.py loads this file by path because its
3.12 runtime cannot import the ``twobyteasr`` package.
"""
from __future__ import annotations

import contextlib
import gc
import json
import mmap
import os
import struct
import sys
import warnings

# Windows only: elsewhere a private file mapping is not charged up front.
# TWOBYTEASR_READ_ONLY_WEIGHTS=0 restores the plain official loading.
ENABLED = os.name == "nt" and os.environ.get("TWOBYTEASR_READ_ONLY_WEIGHTS", "1") != "0"

_SAFETENSORS_DTYPES = {"BOOL": "bool", "U8": "uint8", "I8": "int8", "I16": "int16", "U16": "uint16",
                       "F16": "float16", "BF16": "bfloat16", "I32": "int32", "U32": "uint32", "F32": "float32",
                       "F64": "float64", "I64": "int64", "U64": "uint64", "F8_E5M2": "float8_e5m2",
                       "F8_E4M3": "float8_e4m3fn"}


class ReadOnlyViews:
    """The read-only mappings opened inside one ``read_only_weight_files`` block."""

    def __init__(self, torch):
        self.torch = torch
        self.files = []
        self.ranges = []

    def open(self, filename):
        """``(view, base_address)`` of a new read-only mapping of the whole file."""
        with open(os.fspath(filename), "rb") as stream:
            view = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)  # "The given buffer is not writable"
            address = self.torch.frombuffer(view, dtype=self.torch.uint8, count=1).data_ptr()
        self.files.append((os.fspath(filename), view))
        self.ranges.append((address, address + len(view)))
        return view, address

    def storage(self, filename, nbytes=0):
        """Stand-in for ``torch.UntypedStorage.from_file(filename, shared=False, nbytes)``."""
        view, _ = self.open(filename)
        nbytes = int(nbytes or len(view))
        if nbytes > len(view):
            raise ValueError(f"{filename} is shorter than the {nbytes} bytes requested")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            return self.torch.frombuffer(view, dtype=self.torch.uint8, count=nbytes).untyped_storage()

    def holds(self, tensor) -> bool:
        if tensor.device.type != "cpu" or not tensor.numel():
            return False
        address = tensor.untyped_storage().data_ptr()
        return any(start <= address < end for start, end in self.ranges)

    def detach(self, *modules) -> int:
        """Copy every CPU parameter or buffer that still points into a view; returns how many."""
        copied = 0
        for module in modules:
            for tensor in [*module.parameters(), *module.buffers()]:
                if self.holds(tensor):
                    tensor.data = tensor.data.clone()
                    copied += 1
        return copied

    def close(self) -> None:
        """Unmap what nothing references any more; a view still in use goes with its last tensor."""
        gc.collect()
        for _, view in self.files:
            try:
                view.close()
            except BufferError:
                pass
        self.files.clear()


class _Slice:
    """``safe_open(...).get_slice(name)``: shape and dtype first, data on indexing."""

    def __init__(self, handle, name):
        self.handle, self.name = handle, name
        self.spec = handle.header[name]

    def get_shape(self):
        return list(self.spec["shape"])

    def get_dtype(self):
        return self.spec["dtype"]

    def __getitem__(self, index):
        return self.handle._place(self.handle._tensor(self.name)[index])


class ReadOnlySafeOpen:
    """The parts of ``safetensors.safe_open`` (framework "pt") the transformers loaders use."""

    def __init__(self, views, filename, framework="pt", device="cpu", backend=None):
        if framework not in ("pt", "torch"):
            raise ValueError(f"read-only safe_open only serves PyTorch, not {framework}")
        self.torch, self.device = views.torch, device
        self.view, _ = views.open(filename)
        if len(self.view) < 8:
            raise ValueError(f"{filename} is not a safetensors file")
        size = struct.unpack("<Q", self.view[:8])[0]
        if 8 + size > len(self.view):
            raise ValueError(f"{filename} has a broken safetensors header")
        self.header = json.loads(self.view[8:8 + size])
        self._metadata = self.header.pop("__metadata__", None)
        self.base = 8 + size

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def keys(self):
        return sorted(self.header)

    def offset_keys(self):
        return sorted(self.header, key=lambda name: self.header[name]["data_offsets"][0])

    def metadata(self):
        return self._metadata

    def get_slice(self, name):
        return _Slice(self, name)

    def get_tensor(self, name):
        return self._place(self._tensor(name))

    def get_tensors(self):
        return {name: self.get_tensor(name) for name in self.offset_keys()}

    def _tensor(self, name):
        torch = self.torch
        spec = self.header[name]
        dtype = getattr(torch, _SAFETENSORS_DTYPES.get(spec["dtype"], ""), None)
        if dtype is None:
            raise ValueError(f"safetensors dtype {spec['dtype']} of {name} is not supported here")
        shape = [int(size) for size in spec["shape"]]
        begin, end = (int(offset) for offset in spec["data_offsets"])
        count = 1
        for size in shape:
            count *= size
        if end - begin != count * torch.empty((), dtype=dtype).element_size() or self.base + end > len(self.view):
            raise ValueError(f"safetensors entry {name} does not match its shape and dtype")
        if not count:
            return torch.empty(shape, dtype=dtype)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            return torch.frombuffer(self.view, dtype=dtype, count=count, offset=self.base + begin).reshape(shape)

    def _place(self, tensor):
        if self.device in (None, "cpu") or str(self.device) == "cpu":
            return tensor
        return tensor.to(self.device)


def load(torch, loader, modules, *, torch_load_mmap=False, report=None):
    """``(loader(), weights_loader)``: on Windows ``loader()`` runs inside read-only views.

    ``modules(result)`` names the torch modules to detach from the views. Any
    exception there goes to ``report(error_type, detail)`` and ``loader()``
    runs again the official way, so this route never stops a model loading.
    """
    if ENABLED:
        try:
            with read_only_weight_files(torch, torch_load_mmap=torch_load_mmap) as views:
                result = loader()
            views.detach(*modules(result))
            views.close()
            return result, "read_only_map"
        except Exception as exc:
            if report is not None:
                report(type(exc).__name__, str(exc)[:300])
        # Past the except block its traceback, and any half-loaded model in it, is gone.
        result = views = None
        gc.collect()
        cuda = getattr(torch, "cuda", None)
        if cuda is not None and cuda.is_available():
            cuda.empty_cache()
    return loader(), "official"


@contextlib.contextmanager
def read_only_weight_files(torch, *, torch_load_mmap=False):
    """Inside the block, safetensors files and ``torch.load(mmap=True)`` use read-only views.

    ``safe_open`` is replaced in ``safetensors`` and in every loaded module that
    imported it by name (transformers.modeling_utils and others).
    ``torch_load_mmap`` also makes ``torch.load`` calls that do not pass
    ``mmap`` map the file (FireRed's own checkpoint loader) instead of reading
    every tensor into private memory. Yields the ``ReadOnlyViews``.
    """
    import safetensors

    views = ReadOnlyViews(torch)
    storage_class = torch.UntypedStorage
    official_from_file = storage_class.from_file
    saved_from_file = storage_class.__dict__.get("from_file")
    official_safe_open = safetensors.safe_open

    def from_file(filename, shared=False, nbytes=0):
        if shared:
            return official_from_file(filename, shared, nbytes)
        return views.storage(filename, nbytes)

    def safe_open(filename, framework="pt", device="cpu", **options):
        if framework not in ("pt", "torch"):
            return official_safe_open(filename, framework=framework, device=device, **options)
        return ReadOnlySafeOpen(views, filename, framework, device, options.get("backend"))

    # vars(), not getattr(): lazy modules would import on an unknown attribute.
    importers = [module for module in list(sys.modules.values())
                 if getattr(module, "__dict__", {}).get("safe_open") is official_safe_open]
    config = previous_mmap = None
    if torch_load_mmap:
        from torch.utils.serialization import config
        previous_mmap, config.load.mmap = config.load.mmap, True
    storage_class.from_file = staticmethod(from_file)
    for module in importers:
        module.safe_open = safe_open
    try:
        yield views
    finally:
        for module in importers:
            module.safe_open = official_safe_open
        if saved_from_file is None:
            del storage_class.from_file
        else:
            storage_class.from_file = saved_from_file
        if config is not None:
            config.load.mmap = previous_mmap
