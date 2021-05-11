import pytest
from p2pcam.iotc import P2PPlatform
from p2pcam.mock.mock_tutk_library import MockTutkLibrary  # type: ignore


@pytest.fixture
def tutk_platform_lib():
    return MockTutkLibrary()


@pytest.fixture
def iotc(tutk_platform_lib):
    return P2PPlatform(tutk_platform_lib)


def test_get_version() -> None:
    platform = P2PPlatform.load_Platform()
    assert platform.version == 17630976
    P2PPlatform.unload_Platform()
