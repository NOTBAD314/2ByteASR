"""Cooperative boundaries for GUI-owned construction and hydration."""
from time import perf_counter

GUI_YIELD = object()


class GuiSlice:
    def __init__(self, milliseconds=4):
        self.budget = milliseconds / 1000
        self.resume()

    def resume(self):
        self.started = perf_counter()

    def due(self):
        return perf_counter() - self.started >= self.budget

    def checkpoint(self):
        if self.due():
            yield GUI_YIELD
            self.resume()


def finish(steps):
    """Compatibility for existing callers that explicitly need synchronous build."""
    while True:
        try:
            next(steps)
        except StopIteration as result:
            return result.value
