from .store import Handbook, HandbookError

__all__ = ["Handbook", "HandbookError", "version"]


def version() -> str:
    """This server's version, from the installed distribution (pyproject.toml's)."""
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as dist_version

    try:
        return dist_version("refhandbookmcp")
    except PackageNotFoundError:  # a source tree on sys.path without an install
        return "0+source"
