from typing import List, Optional

from pydantic import BaseModel

from .api_models import WyzeAccount, WyzeCamera, WyzeCredential, WyzeSettings
from .async_api import async_get_camera_list, async_get_user_info, async_login


class WyzeBroker:
    def __init__(self, *, settings: WyzeSettings = None) -> None:
        self._settings = settings

    async def async_prepare(
        self,
        *,
        reset_credential=False,
        reset_account=False,
        reload_cameras=False,
    ):
        settings = self._settings
        if reset_credential or not settings.credential:
            settings.credential = await async_login(settings.login)
        if reset_account or not settings.account:
            settings.account = await async_get_user_info(settings.credential)
        if reload_cameras or not settings.cameras:
            settings.cameras = await async_get_camera_list(settings.credential)
