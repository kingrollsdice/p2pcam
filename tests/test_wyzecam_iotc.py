import pytest
import wyzecam.iotc
from wyzecam.mock.mock_tutk_library import MockTutkLibrary  # type: ignore


@pytest.fixture
def tutk_platform_lib():
    return MockTutkLibrary()


@pytest.fixture
def iotc(tutk_platform_lib):
    return wyzecam.iotc.P2PPlatform(tutk_platform_lib)


def test_get_version(iotc: wyzecam.iotc.P2PPlatform) -> None:
    with iotc:
        assert iotc.version == 0xDEADBEEF
