"""Expected failures at configuration and stage boundaries."""


class ConfigError(Exception):
    """Invalid configuration or unusable database."""

    def __init__(self, problems: str | list[str]):
        self.problems = [problems] if isinstance(problems, str) else problems
        super().__init__("\n".join(self.problems))


class LayoutError(Exception):
    """An unsupported report layout."""


class ReconciliationError(LayoutError):
    """Report values fail reconciliation."""


class ArchiveIntegrityError(Exception):
    """An archived file is missing or has changed."""


class RunLockedError(Exception):
    """Another process holds the run lock."""
