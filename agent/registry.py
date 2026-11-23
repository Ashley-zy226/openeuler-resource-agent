"""Named capabilities shared by the Tool and Skill registries."""


class Registry:
    def __init__(self):
        self._capabilities = {}

    def register(self, name, capability):
        if name in self._capabilities:
            raise ValueError(f"Capability already registered: {name}")
        if not callable(capability):
            raise TypeError(f"Capability must be callable: {name}")
        self._capabilities[name] = capability

    def __getitem__(self, name):
        return self._capabilities[name]
