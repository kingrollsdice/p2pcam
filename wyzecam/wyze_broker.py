from typing import List, Optional

from pydantic import BaseModel

from .api_models import P2PCamera, P2PSettings, WyzeAccount, WyzeCredential
from .async_api import async_get_camera_list, async_get_user_info, async_login


class WyzeBroker:
    def __init__(self, *, settings: P2PSettings = None) -> None:
        self._settings = settings

    async def async_prepare(
        self,
        *,
        reset_account=False,
        reload_cameras=False,
    ):
        settings = self._settings
        if reset_account or not settings.credential:
            settings.credential = await async_login(settings.login)
        if reset_account or not settings.account:
            settings.account = await async_get_user_info(settings.credential)
        if reset_account or reload_cameras or not settings.cameras:
            settings.cameras = await async_get_camera_list(settings.credential)
