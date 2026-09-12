"""Public failures never carry provider responses, headers or secret values."""


class ProviderError(Exception):
    def __init__(self, code: str, status_code: int = 400):
        self.code = code
        self.status_code = status_code
        self.latency_ms = None
        self.usage = None
        super().__init__(code)
