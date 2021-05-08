from typing import Any, Dict, List, Optional, Type, TypeVar, Union

import asyncio
import time
import uuid
from hashlib import md5
from os import PathLike

import aiofiles
from aiofiles.threadpool.text import AsyncTextIOWrapper
from aiohttp import ClientSession
from pydantic import BaseModel
from pydantic.types import SecretStr
from wyzecam.api_models import P2PCamera, WyzeAccount, WyzeCredential, WyzeLogin

SV_VALUE = "e1fe392906d54888a9b99b88de4162d7"
SC_VALUE = "9f275790cab94a72bd206c8876429f3c"
WYZE_APP_API_KEY = "WMXHYf79Nr5gIlt3r0r7p9Tcw5bvs6BB4U8O8nGJ"

SCALE_USER_AGENT = "Wyze/2.19.24 (iPhone; iOS 14.4.2; Scale/3.00)"
WYZE_APP_VERSION_NUM = "2.19.24"


async def _post(url, json, headers):
    async with ClientSession() as session:
        session: ClientSession
        response = await session.post(
            url, json=json, headers=headers, raise_for_status=True
        )
        data = await response.json()
        return data


async def async_login(login: WyzeLogin) -> WyzeCredential:
    """Authenticate with Wyze

    This method calls out to the `/user/login` endpoint of
    `auth-prod.api.wyze.com` (using https), and retrieves an access token
    necessary to retrieve other information from the wyze server.

    :param email: Email address used to log into wyze account
    :param password: Password used to log into wyze account.  This is used to
                     authenticate with the wyze API server, and return a credential.
    :param phone_id: the ID of the device to emulate when talking to wyze.  This is
                     safe to leave as None (in which case a random phone id will be
                     generated)

    :returns: a [WyzeCredential][wyzecam.api.WyzeCredential] with the access information, suitable
              for passing to [get_user_info()][wyzecam.api.get_user_info], or
              [get_camera_list()][wyzecam.api.get_camera_list].
    """
    if login.phone_id is None:
        login.phone_id = str(uuid.uuid4())
    if login.password is None:
        if login.hashed_password is None:
            raise ValueError(
                "Must provide password or hashed password but not both"
            )
    else:
        if login.hashed_password is not None:
            raise ValueError(
                "Must provide password or hashed password but not both"
            )
        else:
            login.hashed_password = triplemd5(login.password)

    payload = {"email": login.email, "password": login.hashed_password}
    resp = await _post(
        "https://auth-prod.api.wyze.com/user/login",
        json=payload,
        headers=get_headers(login.phone_id),
    )
    return WyzeCredential.parse_obj(dict(resp, phone_id=login.phone_id))


async def async_get_user_info(auth_info: WyzeCredential) -> WyzeAccount:
    """Gets Wyze Account Information

    This method calls out to the `/app/user/get_user_info`
    endpoint of `api.wyze.com` (using https), and retrieves the
    account details of the authenticated user.

    :param auth_info: the result of a [`login()`][wyzecam.api.login] call.
    :returns: a [WyzeAccount][wyzecam.api.WyzeAccount] with the user's info, suitable
          for passing to [`WyzeIOTC.connect_and_auth()`][wyzecam.iotc.WyzeIOTC.connect_and_auth].

    """
    payload = _get_payload(auth_info.access_token, auth_info.phone_id)
    ui_headers = get_headers(auth_info.phone_id, SCALE_USER_AGENT)
    resp_json = await _post(
        "https://api.wyzecam.com/app/user/get_user_info",
        json=payload,
        headers=ui_headers,
    )
    assert resp_json["code"] == "1", "Call failed"

    return WyzeAccount.parse_obj(
        dict(resp_json["data"], phone_id=auth_info.phone_id)
    )


async def async_get_homepage_object_list(
    auth_info: WyzeCredential,
) -> Dict[str, Any]:
    """Gets all homepage objects"""
    payload = _get_payload(auth_info.access_token, auth_info.phone_id)
    ui_headers = get_headers(auth_info.phone_id, SCALE_USER_AGENT)
    resp_json = await _post(
        "https://api.wyzecam.com/app/v2/home_page/get_object_list",
        json=payload,
        headers=ui_headers,
    )

    data = resp_json["data"]  # type: Dict[str, Any]
    return data


async def async_get_camera_list(auth_info: WyzeCredential) -> List[P2PCamera]:
    data = await async_get_homepage_object_list(auth_info)
    result = []
    for device in data["device_list"]:  # type: Dict[str, Any]
        if device["product_type"] != "Camera":
            continue

        p2p_id: Optional[str] = device.get("device_params", {}).get("p2p_id")
        enr: Optional[str] = device.get("enr")
        mac: Optional[str] = device.get("mac")
        product_model: Optional[str] = device.get("product_model")
        nickname: Optional[str] = device.get("nickname")
        timezone_name: Optional[str] = device.get("timezone_name")

        if not p2p_id:
            continue
        if not enr:
            continue
        if not mac:
            continue
        if not product_model:
            continue

        result.append(
            P2PCamera(
                p2p_id=p2p_id,
                enr=enr,
                mac=mac,
                product_model=product_model,
                nickname=nickname,
                timezone_name=timezone_name,
            )
        )
    return result


def _get_payload(access_token, phone_id):
    payload = {
        "sc": SC_VALUE,
        "sv": SV_VALUE,
        "app_ver": f"com.hualai.WyzeCam___{WYZE_APP_VERSION_NUM}",
        "app_version": f"{WYZE_APP_VERSION_NUM}",
        "app_name": "com.hualai.WyzeCam",
        "phone_system_type": "1",
        "ts": int(time.time() * 1000),
        "access_token": access_token,
        "phone_id": phone_id,
    }
    return payload


def get_headers(phone_id, user_agent="wyze_ios_2.19.24"):
    return {
        "X-API-Key": WYZE_APP_API_KEY,
        "Phone-Id": phone_id,
        "User-Agent": user_agent,
    }


def triplemd5(password: SecretStr):
    """Runs hashlib.md5() algorithm 3 times"""
    encoded = password.get_secret_value()
    for i in range(3):
        encoded = md5(encoded.encode("ascii")).hexdigest()  # nosec
    return encoded


Model = TypeVar("Model", bound="BaseModel")


async def async_parse_file(cls: Type["Model"], file: PathLike) -> "Model":
    async with aiofiles.open(file, "rb") as f:
        f: AsyncTextIOWrapper
        raw_data = await f.read()
        return cls.parse_raw(raw_data)


BaseModel.async_parse_file = classmethod(async_parse_file)
