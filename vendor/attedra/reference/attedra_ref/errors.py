"""Write failures (conformance README §6)."""


class WriteError(Exception):
    """A rejected write. `code` is a README §6 code: 'occupied', '10.2.2'..'10.2.9',
    'duplicate_key', 'number_out_of_range', 'plan_stale', 'plan_unknown'."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code
