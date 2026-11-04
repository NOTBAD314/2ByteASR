"""Independent operation tokens; generation numbers only gate UI ownership."""
from dataclasses import dataclass, field
import threading
import uuid


@dataclass
class RequestOperation:
    kind: str
    generation: int
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    cancel: threading.Event = field(default_factory=threading.Event)
    done: bool = False


class RequestOperations:
    def __init__(self):
        self.current = {}
        self.by_generation = {}

    def begin(self, kind, generation):
        old = self.current.get(kind)
        if old is not None and not old.done:
            old.cancel.set()
        self.by_generation = {key: value for key, value in self.by_generation.items()
                              if not value.done}
        # Keep cancelled identities until their terminal callbacks arrive.
        # Bound abandoned callbacks without allowing them to own new UI.
        for key in list(self.by_generation)[:-128]:
            if self.by_generation[key].cancel.is_set():self.by_generation.pop(key)
        operation = RequestOperation(kind, generation)
        self.current[kind] = operation
        self.by_generation[generation] = operation
        return operation

    def finish(self, generation):
        operation = self.by_generation.pop(generation, None)
        if operation is not None:
            operation.done = True
        return operation
