"""Small process-local cache for immutable published definitions."""

from collections import OrderedDict
from copy import deepcopy
from threading import RLock


class PublishedDefinitionCache:
    def __init__(self, max_entries=256):
        self.max_entries = max(1, int(max_entries))
        self._items = OrderedDict()
        self._lock = RLock()

    def get(self, version):
        key = (int(version.id), str(version.definition_hash or ""))
        with self._lock:
            value = self._items.get(key)
            if value is None:
                value = deepcopy(version.definition_json or {})
                self._items[key] = value
                while len(self._items) > self.max_entries:
                    self._items.popitem(last=False)
            else:
                self._items.move_to_end(key)
            return deepcopy(value)

    def clear(self):
        with self._lock:
            self._items.clear()


published_definition_cache = PublishedDefinitionCache()
