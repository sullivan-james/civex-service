from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("civex")
except PackageNotFoundError:
    __version__ = "0.0.0.dev"

from civex._sdk_repair import repair_sdk_if_needed  # noqa: E402

repair_sdk_if_needed()
