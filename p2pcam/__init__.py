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

from .api import get_camera_list, get_user_info, login
from .iotc import P2PPlatform, P2PSession, WyzeIOTCSessionState
from .models import P2PCamera, P2PSettings, ServiceAccount, ServiceCredential
from .motion import MotionDetector
from .service_broker import ServiceBroker
