# type: ignore[attr-defined]
"""Python package for communicating with wyze cameras over the local network"""

try:
    from importlib.metadata import PackageNotFoundError, version
except ImportError:  # pragma: no cover
    from importlib_metadata import PackageNotFoundError, version

try:
    __version__ = version(__name__)
except PackageNotFoundError:  # pragma: no cover
    __version__ = "unknown"

from wyzecam.api import get_camera_list, get_user_info, login
from wyzecam.api_models import (
    P2PCamera,
    P2PSettings,
    WyzeAccount,
    WyzeCredential,
)
from wyzecam.iotc import P2PPlatform, P2PSession, WyzeIOTCSessionState
from wyzecam.wyze_broker import WyzeBroker

from .motion import MotionDetector
