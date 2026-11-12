"""Shared source precondition, with safe diagnostics for local and SMB access."""
from .source import make_source, source_error


def precheck(config):
    """Return the read-only source and listing, or a sanitized failure."""
    try:
        source = make_source(config)
        names = source.names()
    except Exception as error:
        raise source_error(error, config.smb_password,
                           local=not config.source_path.startswith(('//', '\\\\')),
                           operation='list', path=config.source_path,
                           username=config.smb_username) from None
    return source, names
