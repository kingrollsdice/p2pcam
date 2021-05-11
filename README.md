# wyzecam

<div align="center">

[![Build status](workflows/build/badge.svg?branch=master&event=push)](actions?query=workflow%3Abuild)
[![Python Version](https://img.shields.io/pypi/pyversions/wyzecam.svg)](https://pypi.org/project/wyzecam/)
[![Dependencies Status](https://img.shields.io/badge/dependencies-up%20to%20date-brightgreen.svg)](pulls?utf8=%E2%9C%93&q=is%3Apr%20author%3Aapp%2Fdependabot)

[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Security: bandit](https://img.shields.io/badge/security-bandit-green.svg)](https://github.com/PyCQA/bandit)
[![Pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://github.com/kroo/wyzecam/blob/master/.pre-commit-config.yaml)
[![Semantic Versions](https://img.shields.io/badge/%F0%9F%9A%80-semantic%20versions-informational.svg)](https://github.com/kroo/wyzecam/releases)
[![License](https://img.shields.io/github/license/kroo/wyzecam)](blob/master/LICENSE)

</div>

p2pcam is a library for streaming audio and video from your wyze cameras using the wyze native firmware. It is derived from https://github.com/kroo/wyzecam/

That means no need to flash rtsp-specific firmware, and full support for the v3 hardware!

## Basic Usage

Streaming video in 11 lines of code!

```python
import asyncio
import logging
from os import PathLike
from typing import Any, Optional, Union
import aiofiles
import cv2
from p2pcam import MotionDetector, P2PSession, P2PSettings, ServiceBroker

_Logger = logging.getLogger(__name__)


async def run_app(*,
                  data: Any = None,
                  file: Optional[Union[PathLike, str]] = None):

    settings = await P2PSettings.parse(data=data, file=file)

    broker = ServiceBroker(settings=settings)
    await broker.async_prepare()

    async with aiofiles.open(file, 'wb') as file:
        raw_data = settings.json().encode('utf-8')
        await file.write(raw_data)

    with P2PSession(settings=settings,
                    camera=1,
                    bitrate=P2PSession.BITRATE_360P) as sess:
        motion_detector = MotionDetector()
        for (frame, frame_info) in sess.recv_video_frame_ndarray():
            frame, thframe = motion_detector.detect(frame=frame)
            if frame is None:
                continue
            cv2.imshow("Video Feed", frame)
            cv2.imshow("Motion Feed", thframe)
            # Press 'esc' for quit
            if cv2.waitKey(1) == 27:
                break

    # Destroy all windows
    cv2.destroyAllWindows()


def main():
    file = './settings.json'
    email = "example@example.com"
    password = "my super secret"
    asyncio.run(run_app(file=file))


if __name__ == "__main__":
    main()

```

## Features

- Send local commands (via `WyzeIOTC` class)
- Support for all wyze camera types (including v3 cameras!)
- Uses the [tutk](https://github.com/nblavoie/wyzecam-api/tree/master/wyzecam-sdk) protocol for communicating over the
  local network. 
- Optional support for opencv and libav for easy decoding of the video feed!


## Installation

```bash
pip install -U wyzecam
```

To install shared library use

```bash
p2pcam_install_libs "https://github.com/nblavoie/wyzecam-api/blob/master/wyzecam-sdk/TUTK_IOTC_Platform_14W42P1.zip"
```
This will download, unzip and copy the required files.

You will then need a copy of the shared library `libAVAPIs.so` and `libIOTCAPIs.so`. You can use [this SDK](https://github.com/nblavoie/wyzecam-api/tree/master/wyzecam-sdk) 
or another version that contains the files. 

In case you have shared library files, you can add directly by using following
```bash
p2pcam_install_libs /path/to/file/libAVAPIs.so /path/to/file/libIOTCAPIs.so
```

## 🛡 License

[![License](https://img.shields.io/github/license/kroo/wyzecam)](https://github.com/kroo/wyzecam/blob/master/LICENSE)

This project is licensed under the terms of the `MIT` license.
See [LICENSE](https://github.com/kroo/wyzecam/blob/master/LICENSE) for more details.

## 📃 Citation

```
@misc{wyzecam,
  author = {kroo},
  title = {Python package for communicating with wyze cameras over the local network},
  year = {2021},
  publisher = {GitHub},
  journal = {GitHub repository},
  howpublished = {\url{https://github.com/kroo/wyzecam}}
}
```

## Credits

Special thanks to the work by folks at [nblavoie/wyzecam-api](https://github.com/nblavoie/wyzecam-api), without which
this project would have been much harder.
