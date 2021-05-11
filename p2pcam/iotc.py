from typing import Dict, Iterator, Optional, Tuple, Union

import atexit
import enum
import logging
import os
import pathlib
import platform
import time
import warnings
from ctypes import CDLL, RTLD_GLOBAL, c_int

from .models import P2PCamera, P2PSettings

_Logger = logging.getLogger(__name__)

try:
    import av
    import av.video.frame
except ImportError:
    av = None

try:
    import cv2
except ImportError:
    cv2 = None

try:
    import numpy as np
except ImportError:
    np = None  # type: ignore

from .tutk import tutk
from .tutk.tutk_ioctl_mux import TutkIOCtrlMux
from .tutk.tutk_protocol import (
    K10000ConnectRequest,
    K10056SetResolvingBit,
    respond_to_ioctrl_10001,
)

LIBRARY_FILES = ["libIOTCAPIs_ALL"]
LIBRARY_FILE_EXT = [".so", ".dyall"]
AV_LIBRARY_FILE = "libAVAPIs.so"
IOTC_LIBRARY_FILE = "libIOTCAPIs.so"


class P2PPlatform:

    _instance: Optional["P2PPlatform"] = None

    @classmethod
    def instance(cls):
        return cls._instance

    @classmethod
    def load_Platform(
        cls,
        tutk_platform_lib: Optional[Union[str, CDLL]] = None,
        udp_port: int = 0,
        max_num_av_channels: int = 2,
    ) -> "P2PPlatform":
        if cls._instance is not None:
            return cls._instance
        cls._instance = P2PPlatform(
            tutk_platform_lib, udp_port, max_num_av_channels
        )
        cls._instance._initialize()
        return cls._instance

    @classmethod
    def unload_Platform(cls):
        if cls._instance is None:
            return
        cls._instance._deinitialize()
        cls._instance = None

    """Wyze IOTC singleton, used to construct iotc_sessions

    This object should generally be used inside a context manager, i.e.:

    ```python
    with WyzeIOTC() as wyze:
        with wyze.connect_and_auth(account, camera) as session:
            ...  # send commands to the camera, then start streaming
    ```

    :var tutk_platform_lib: the underlying c library used to communicate with the wyze
                            device; see [wyzecam.tutk.tutk.load_library][]
    :var udp_port: the UDP port used on this machine for communication with wyze cameras on the same network
    :vartype udp_port: int
    :var max_num_av_channels: the maximum number of simultaneous sessions this object supports.
    :vartype max_num_av_channels: int
    :var version: the version of the underyling `tutk_platform_lib`
    """

    def __init__(
        self,
        tutk_platform_lib: Optional[Union[str, CDLL]] = None,
        udp_port: Optional[int] = None,
        max_num_av_channels: Optional[int] = None,
    ) -> None:
        """Construct a WyzeIOTC session object

        You should only create one of these at a time.

        :param tutk_platform_lib: The underlying c library (from tutk.load_library()), or the path
                                  to this library.
        :param udp_port: Specify a UDP port. Random UDP port is used if it is specified as 0.
        :param max_num_av_channels: The max number of AV channels. If it is specified
                                    less than 1, AV will set max number of AV channels as 1.

        """
        if tutk_platform_lib is None:
            iotc_lib, av_lib = P2PPlatform._load_library()
            self.iotc_lib: CDLL = iotc_lib
            self.av_lib: CDLL = av_lib
        elif isinstance(tutk_platform_lib, str):
            path = pathlib.Path(tutk_platform_lib)
            tutk_platform_lib = tutk.load_library(str(path.absolute()))
            self.iotc_lib = tutk_platform_lib
            self.av_lib = tutk_platform_lib
        elif isinstance(tutk_platform_lib, CDLL):
            self.iotc_lib = tutk_platform_lib
            self.av_lib = tutk_platform_lib

        self.initd = False
        self.udp_port = udp_port
        self.max_num_av_channels = max_num_av_channels

    @staticmethod
    def _load_library() -> Tuple[CDLL, CDLL]:
        libpath = pathlib.Path(__file__).parent.joinpath("lib")

        iotcLibPath = str(libpath.joinpath(IOTC_LIBRARY_FILE))
        iotcLib = CDLL(name=iotcLibPath, mode=RTLD_GLOBAL)

        avLibPath = str(libpath.joinpath(AV_LIBRARY_FILE))
        avLib = CDLL(name=avLibPath, mode=RTLD_GLOBAL)

        return iotcLib, avLib

    def _initialize(self):
        """Initialize the underlying TUTK library

        This is called automatically by the context manager,
        and should only be called if you intend to manually handle
        cleanup of this classes resources (by calling deinitialize
        when done with it!)
        """
        if self.initd:
            return
        self.initd = True

        errno = tutk.iotc_initialize(self.iotc_lib, udp_port=self.udp_port or 0)
        if errno < 0:
            raise tutk.TutkError(errno)

        actual_num_chans = tutk.av_initialize(
            self.av_lib, max_num_channels=self.max_num_av_channels
        )
        if actual_num_chans < 0:
            raise tutk.TutkError(errno)
        atexit.register(self._deinitialize)

        self.max_num_av_channels = actual_num_chans

    def _deinitialize(self):
        """Deinitialize the underlying TUTK library

        This is called automatically by the context manager
        """
        tutk.av_deinitialize(self.av_lib)
        tutk.iotc_deinitialize(self.iotc_lib)
        atexit.unregister(self._deinitialize)

    @property
    def version(self):
        """Get the version of the underlying TUTK library"""
        return tutk.iotc_get_version(self.iotc_lib)


class WyzeIOTCSessionState(enum.IntEnum):
    """An enum describing the possible states of a WyzeIOTCSession"""

    DISCONNECTED = 0
    """Not yet connected"""

    IOTC_CONNECTING = 1
    """Currently attempting to connect the IOTC session"""

    AV_CONNECTING = 2
    """Currently attempting to connect the AV session"""

    CONNECTED = 3
    """Fully connected to the camera, but have not yet attempted to authenticate"""

    AUTHENTICATING = 4
    """Attempting to authenticate"""

    AUTHENTICATION_SUCCEEDED = 5
    """Fully connected and authenticated"""

    AUTHENTICATION_FAILED = 6
    """Authentication failed, and likely no longer connected"""


class P2PSession:
    BITRATE_360P = 0x1E
    """
    The bitrate used by the "360P" setting in the app.  Approx 30 KB/s.
    """

    BITRATE_SD = 0x3C
    """
    The bitrate used by the "SD" setting in the app.  Approx 60 KB/s.
    """
    BITRATE_HD = 0x78
    """
    The bitrate used by the "HD" setting in the app.  Approx 120 KB/s.
    """

    BITRATE_SUPER_HD = 0x96
    """
    A bitrate higher than the "HD" setting in the app.  Approx 150 KB/s.
    """

    BITRATE_SUPER_SUPER_HD = 0xF0
    """
    A bitrate higher than the "HD" setting in the app.  Approx 240 KB/s.
    """

    FRAME_SIZE_1080P = 0
    """
    Represents the size of the video stream sent back from the server; 1080P
    or 1920x1080 pixels.
    """

    FRAME_SIZE_360P = 1
    """
    Represents the size of the video stream sent back from the server; 360P
    or 640x360 pixels.
    """

    @classmethod
    def get_platform(cls):
        platform = P2PPlatform._instance
        if platform is None:
            raise ValueError("call load_platform() before accessing.")
        return platform

    @classmethod
    def load_Platform(
        cls,
        tutk_platform_lib: Optional[Union[str, CDLL]] = None,
        udp_port: int = 0,
        max_num_av_channels: int = 2,
    ) -> None:
        P2PPlatform.load_Platform(
            tutk_platform_lib, udp_port, max_num_av_channels
        )

    @classmethod
    def unload_Platform(cls):
        P2PPlatform.unload_Platform()

    """An IOTC session object, used for communicating with Wyze cameras

    This is constructed from a WyzeIOTC object:

    ```python
    with WyzeIOTC() as wyze:
        with wyze.connect_and_auth(account, camera) as session:
            ...  # send configuration commands, or stream video
    ```

    However, you can construct it manually, which can be helpful if you intend to set a
    different frame size or bitrate than the defaults:

    ```python
    with WyzeIOTCSession(lib, account, camera, bitrate=tutk.BITRATE_SD)
        ...
    ```

    > **Note:** WyzeIOTCSession is intended to be used as a context manager.  Otherwise,
    >    you will need to manually tell the session to connect and authenticate, by calling
    >    session._connect() followed by session._auth(), and session._disconnect() when you're
    >    ready to disconnect the session.

    :var tutk_platform_lib: The underlying c library (from [tutk.load_library][wyzecam.tutk.tutk.load_library])
    :var account: A [WyzeAccount][wyzecam.api_models.WyzeAccount] instance, see
                    [api.get_user_info][wyzecam.api.get_user_info]
    :var camera: A [WyzeCamera][wyzecam.api_models.WyzeCamera] instance, see
                   [api.get_camera_list][wyzecam.api.get_camera_list]
    :var preferred_frame_size: The preferred size of the video stream returned by the camera.
                                 See [wyzecam.tutk.tutk.FRAME_SIZE_1080P][].
    :var preferred_bitrate: The preferred bitrate of the video stream returned by the camera.
                              See [wyzecam.tutk.tutk.BITRATE_HD][].
    :var session_id: The id of this session, once connected.
    :var av_chan_id: The AV channel of this session, once connected.
    :var state: The current connection state of this session.  See
                [WyzeIOTCSessionState](../iotc_session_state/).
    """

    def __init__(
        self,
        settings: P2PSettings,
        camera: Union[int, str, P2PCamera],
        frame_size: int = tutk.FRAME_SIZE_1080P,
        bitrate: int = tutk.BITRATE_HD,
    ) -> None:
        """Construct a wyze iotc session

        :param tutk_platform_lib: The underlying c library (from
                        [tutk.load_library][wyzecam.tutk.tutk.load_library])
        :param account: A [WyzeAccount][wyzecam.api_models.WyzeAccount] instance, see
                        [api.get_user_info][wyzecam.api.get_user_info]
        :param camera: A [WyzeCamera][wyzecam.api_models.WyzeCamera] instance, see
                       [api.get_camera_list][wyzecam.api.get_camera_list]
        :param frame_size: Configures the size of the video stream returned by the camera.
                           See [wyzecam.tutk.tutk.FRAME_SIZE_1080P][].
        :param bitrate: Configures the bitrate of the video stream returned by the camera.
                        See [wyzecam.tutk.tutk.BITRATE_HD][].
        """
        P2PSession.load_Platform()
        self.settings = settings
        if isinstance(camera, int):  # index
            camera = settings.cameras[camera]
        elif isinstance(camera, str):  # name
            cams = [
                c
                for c in settings.cameras
                if c.nickname and camera in c.nickname
            ]
            camera = cams[0]

        self.camera: P2PCamera = camera
        self.session_id: Optional[c_int] = None
        self.av_chan_id: Optional[c_int] = None
        self.state: WyzeIOTCSessionState = WyzeIOTCSessionState.DISCONNECTED

        self.preferred_frame_size: int = frame_size
        self.preferred_bitrate: int = bitrate

    @property
    def av_lib(self):
        return P2PSession.get_platform().av_lib

    @property
    def iotc_lib(self):
        return P2PSession.get_platform().iotc_lib

    def session_check(self) -> tutk.SInfoStruct:
        """Used by a device or a client to check the IOTC session info.

        A device or a client may use this function to check if the IOTC session is
        still alive as well as getting the IOTC session info.

        :returns: A [`tutk.SInfoStruct`][wyzecam.tutk.tutk.SInfoStruct]
        """
        assert (
            self.session_id is not None
        ), "Please call _connect() before session_check()"

        errcode, sess_info = tutk.iotc_session_check(
            self.iotc_lib, self.session_id
        )
        if errcode < 0:
            raise tutk.TutkError(errcode)

        return sess_info

    def _auth(self):
        assert (
            self.state == WyzeIOTCSessionState.CONNECTED
        ), f"Auth expected state to be connected but not authed; state={self.state}"

        with self.iotctrl_mux() as mux:
            challenge = mux.send_ioctl(K10000ConnectRequest())
            challenge_response = respond_to_ioctrl_10001(
                challenge.result(),
                challenge.resp_protocol,
                self.camera.enr,
                self.camera.product_model,
                self.camera.mac,
                self.settings.account.phone_id,
                self.settings.account.open_user_id,
            )
            auth_response = mux.send_ioctl(challenge_response).result()
            assert (
                auth_response["connectionRes"] == "1"
            ), f"Authentication did not succeed! {auth_response}"
            self.camera.set_camera_info(auth_response["cameraInfo"])
            resolving = mux.send_ioctl(
                K10056SetResolvingBit(
                    self.preferred_frame_size, self.preferred_bitrate
                )
            )

            mux.waitfor(resolving)

        return self

    def connect_and_auth(self):
        self._connect()
        self._auth()

    def iotctrl_mux(self) -> TutkIOCtrlMux:
        """Constructs a new TutkIOCtrlMux for this session

        Use this to send configuration messages, such as change the cameras resolution.

        Note that you either should treat the result of this as a context manager (using
        with), or call start_listening() explicitly on the result.  This starts a separate
        thread listening for the responses from the camera.

        ```python
        with session.ioctrl_mux() as mux:
            msg = tutk_protocol.K10056SetResolvingBit(
                tutk.FRAME_SIZE_1080P, tutk.BITRATE_SD)
            future = mux.send_ioctl(msg)
            assert future.result() == True, "Change bitrate failed!"
        ```

        """
        assert self.av_chan_id is not None, "Please call _connect() first!"
        return TutkIOCtrlMux(self.av_lib, self.av_chan_id)

    def __enter__(self):
        self._connect()
        self._auth()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._disconnect()

    def recv_video_data(
        self,
    ) -> Iterator[Tuple[Optional[bytes], tutk.FrameInfoStruct]]:
        """A generator for returning raw video frames!

        By iterating over the return value of this function, you will
        get raw video frame data in the form of a bytes object.  This
        is convenient for accessing the raw video data without doing
        the work of decoding or transcoding the actual video feed.  If
        you want to save the video to disk, display it, or otherwise process
        the video, I highly recommend using `recv_video_frame` or
        `recv_video_frame_nparray` instead of this function.

        The second item in the tuple returned by this function, 'frame_info', is a useful
        set of metadata about the frame as returned by the camera.  See
        [tutk.FrameInfoStruct][wyzecam.tutk.tutk.FrameInfoStruct] for more details about
        the contents of this object.

        Note that the format of this data is either raw h264 or HVEC H265 video. You will
        have to introspect the frame_info object to determine the format!


        ```python
        with wyzecam.WyzeIOTC() as wyze_iotc:
            with wyze_iotc.connect_and_auth(account, camera) as sess:
                for (frame, frame_info) in sess.recv_video_data():
                    # do something with the video data! :)
        ```

        In order to use this, you will need to install [PyAV](https://pyav.org/docs/stable/).

        :returns: A generator, which when iterated over, yields a tuple containing the decoded image
                 (as a [PyAV VideoFrame](https://pyav.org/docs/stable/api/video.html#av.video.frame.VideoFrame)),
                 as well as metadata about the frame (in the form of a
                 [tutk.FrameInfoStruct][wyzecam.tutk.tutk.FrameInfoStruct]).


        """
        assert self.av_chan_id is not None, "Please call _connect() first!"

        while True:
            errno, frame_data, frame_info, frame_idx = tutk.av_recv_frame_data(
                self.av_lib, self.av_chan_id
            )
            if errno < 0:
                if errno == tutk.AV_ER_DATA_NOREADY:
                    time.sleep(1.0 / 40)
                    continue
                elif errno == tutk.AV_ER_INCOMPLETE_FRAME:
                    warnings.warn("Received incomplete frame")
                    continue
                elif errno == tutk.AV_ER_LOSED_THIS_FRAME:
                    warnings.warn("Lost complete frame")
                    continue
                else:
                    raise tutk.TutkError(errno)
            assert frame_info is not None, "Got no frame info without an error!"
            if frame_info.frame_size != self.preferred_frame_size:
                print("skipping smaller frame at start of stream")
                continue
            yield frame_data, frame_info

    def recv_video_frame(
        self,
    ) -> Iterator[Tuple["av.VideoFrame", tutk.FrameInfoStruct]]:
        """A generator for returning decoded video frames!

        By iterating over the return value of this function, you will conveniently
        get nicely decoded frames in the form of a PyAV VideoFrame object.  This is
        convenient for recording the video to disk.

        The second item in the tuple returned by this function, 'frame_info', is a useful
        set of metadata about the frame as returned by the camera.  See
        [tutk.FrameInfoStruct][wyzecam.tutk.tutk.FrameInfoStruct] for more details about
        the contents of this object.

        ```python
        with wyzecam.WyzeIOTC() as wyze_iotc:
            with wyze_iotc.connect_and_auth(account, camera) as sess:
                for (frame, frame_info) in sess.recv_video_frame():
                    # do something with the video data! :)
        ```

        In order to use this, you will need to install [PyAV](https://pyav.org/docs/stable/).

        :returns: A generator, which when iterated over, yields a tuple containing the decoded image
                 (as a [PyAV VideoFrame](https://pyav.org/docs/stable/api/video.html#av.video.frame.VideoFrame)),
                 as well as metadata about the frame (in the form of a
                 [tutk.FrameInfoStruct][wyzecam.tutk.tutk.FrameInfoStruct]).
        """
        if av is None:
            raise RuntimeError(
                "recv_video_frame requires PyAv to parse video frames. "
                "Install with `pip install av` and try again."
            )

        codec = None
        for frame_data, frame_info in self.recv_video_data():
            if codec is None:
                codec = self._av_codec_from_frameinfo(frame_info)
            packets = codec.parse(frame_data)
            for packet in packets:
                frames = codec.decode(packet)
                for frame in frames:
                    yield frame, frame_info

    def recv_video_frame_ndarray(
        self,
    ) -> Iterator[Tuple["np.ndarray", tutk.FrameInfoStruct]]:
        """A generator for returning decoded video frames!

        By iterating over the return value of this function, you will conveniently
        get nicely decoded frames in the form of a numpy array (suitable for
        [matplotlib.imshow](https://matplotlib.org/stable/api/_as_gen/matplotlib.pyplot.imshow.html)
        or [cv2.imshow](https://docs.opencv.org/master/dd/d43/tutorial_py_video_display.html).

        The second item in the tuple returned by this function, 'frame_info', is a useful
        set of metadata about the frame as returned by the camera.  See
        [tutk.FrameInfoStruct][wyzecam.tutk.tutk.FrameInfoStruct] for more details about
        the contents of this object.

        ```python
        with wyzecam.WyzeIOTC() as wyze_iotc:
            with wyze_iotc.connect_and_auth(account, camera) as sess:
                for (frame, frame_info) in sess.recv_video_frame_ndarray():
                    # do something with the video data! :)
        ```

        In order to use this, you will need to install [PyAV](https://pyav.org/docs/stable/)
        and [numpy](https://numpy.org/).

        :returns: A generator, which when iterated over, yields a tuple containing the decoded image
                 (as a numpy array), as well as metadata about the frame (in the form of a
                 [tutk.FrameInfoStruct][wyzecam.tutk.tutk.FrameInfoStruct]).
        """
        if np is None:
            raise RuntimeError(
                "recv_video_frame_ndarray requires numpy to convert to a numpy array. "
                "Install with `pip install numpy` and try again."
            )

        for frame, frame_info in self.recv_video_frame():
            img = frame.to_ndarray(format="bgr24")
            yield img, frame_info

    def recv_video_frame_ndarray_with_stats(
        self,
        stat_window_size: int = 210,
        draw_stats: Optional[
            str
        ] = "{width}x{height} {kilobytes_per_second} kB/s {frames_per_second} FPS",
    ) -> Iterator[Tuple["np.ndarray", tutk.FrameInfoStruct, Dict[str, int]]]:
        """
        Does everything recv_video_frame_ndarray does, but also computes a number
        of useful / interesting debug metrics including effective framerate, bitrate,
        and frame size information.  Optionally, if you specify a format string to the
        `draw_stats` function, this information will be used to draw a line of text
        onto the image in the top-right corner with this debug information.

        ```python
        with wyzecam.WyzeIOTC() as wyze_iotc:
            with wyze_iotc.connect_and_auth(account, camera) as sess:
                for (frame, frame_info, frame_stats) in sess.recv_video_frame_ndarray_with_stats():
                    # do something with the video data! :)
        ```


        This method gives you an additional 'frame_stats' value every frame, which is a
        dict with the following keys:

         - "bytes_per_second"
         - "kilobytes_per_second"
         - "window_duration"
         - "frames_per_second"
         - "width"
         - "height"

        This dictionary is available in the draw_stats string as arguments to a python
        str.format() call, allowing you to quickly change the debug string in the top corner
        of the video.

        In order to use this, you will need to install [PyAV](https://pyav.org/docs/stable/),
        [numpy](https://numpy.org/), and [PyOpenCV](https://pypi.org/project/opencv-python/).

        :param stat_window_size: the number of consecutive frames to use as the window function
                                 for computing the above metrics.  The larger the window size,
                                 the longer period over which the metrics are averaged.  Note that
                                 this method is not performant for very large window sizes.
        :param draw_stats: if specified, this python format() string is used to draw some debug text
                           in the upper right hand corner.

        :returns: A generator, which when iterated over, yields a 3-tuple containing the decoded image
                 (as a numpy array), metadata about the frame (in the form of a
                 [tutk.FrameInfoStruct][wyzecam.tutk.tutk.FrameInfoStruct]), and some performance
                 statistics (in the form of a dict).

        """
        stat_window = []
        for frame_ndarray, frame_info in self.recv_video_frame_ndarray():
            stat_window.append(frame_info)
            if len(stat_window) > stat_window_size:
                stat_window = stat_window[len(stat_window) - stat_window_size :]

            if len(stat_window) > 1:
                stat_window_start = (
                    stat_window[0].timestamp
                    + stat_window[0].timestamp_ms / 1_000_000
                )
                stat_window_end = (
                    stat_window[-1].timestamp
                    + stat_window[-1].timestamp_ms / 1_000_000
                )
                stat_window_duration = stat_window_end - stat_window_start
                stat_window_total_size = sum(
                    b.frame_len for b in stat_window[:-1]
                )  # skip the last reading
                bytes_per_second = int(
                    stat_window_total_size / stat_window_duration
                )
                frames_per_second = int(len(stat_window) / stat_window_duration)
            else:
                bytes_per_second = 0
                stat_window_duration = 0
                frames_per_second = 0

            stats = {
                "bytes_per_second": bytes_per_second,
                "kilobytes_per_second": int(bytes_per_second / 1000),
                "window_duration": stat_window_duration,
                "frames_per_second": frames_per_second,
                "width": frame_ndarray.shape[1],
                "height": frame_ndarray.shape[0],
            }

            if draw_stats:
                text = draw_stats.format(**stats)
                cv2.putText(
                    frame_ndarray,
                    text,
                    (50, 50),
                    cv2.FONT_HERSHEY_DUPLEX,
                    1,
                    (0, 0, 0),
                    2,
                    cv2.LINE_AA,
                )
                cv2.putText(
                    frame_ndarray,
                    text,
                    (50, 50),
                    cv2.FONT_HERSHEY_DUPLEX,
                    1,
                    (255, 255, 255),
                    1,
                    cv2.LINE_AA,
                )

            yield frame_ndarray, frame_info, stats

    def _av_codec_from_frameinfo(self, frame_info):
        if frame_info.codec_id == 78:
            codec_name = "h264"
        elif frame_info.codec_id == 80:
            codec_name = "hevc"
        else:
            codec_name = "h264"
            print(f"Unexpected codec! got {frame_info.codec_id}.")
        # noinspection PyUnresolvedReferences
        codec = av.CodecContext.create(codec_name, "r")
        return codec

    def _connect(
        self,
        timeout_secs=10,
        channel_id=0,
        username=b"admin",
        password=b"888888",
        max_buf_size=5 * 1024 * 1024,
    ):
        self.state = WyzeIOTCSessionState.IOTC_CONNECTING
        self.session_id = tutk.iotc_connect_by_uid(
            self.iotc_lib, self.camera.p2p_id
        )
        self.session_check()

        self.state = WyzeIOTCSessionState.AV_CONNECTING
        av_chan_id, pn_serv_type = tutk.av_client_start(
            self.av_lib,
            self.session_id,
            username,
            password,
            timeout_secs,
            channel_id,
        )

        if av_chan_id < 0:  # type: ignore
            raise tutk.TutkError(av_chan_id)
        self.av_chan_id = av_chan_id
        self.state = WyzeIOTCSessionState.CONNECTED

        print(
            f"AV Client Start: "
            f"chan_id={av_chan_id} "
            f"expected_chan={channel_id} "
            f"pn_serv_type={pn_serv_type.value}"
        )

        tutk.av_client_set_max_buf_size(self.av_lib, max_buf_size)

    def _disconnect(self):
        if self.av_chan_id:
            tutk.av_client_stop(self.av_lib, self.av_chan_id)
        self.av_chan_id = None
        if self.session_id:
            tutk.iotc_session_close(self.iotc_lib, self.session_id)
        self.session_id = None
        self.state = WyzeIOTCSessionState.DISCONNECTED
