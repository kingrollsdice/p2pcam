from typing import IO, Iterable, List, Optional, Text, Tuple

import argparse
import asyncio
import os
import platform
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from zipfile import ZipFile

from aiohttp import ClientSession
from yarl import URL


class Setup:
    CHUNK_SIZE = 1024 * 10
    PLATFORM_X64 = ["x86_64", "x64", "AMD64"]

    FILE_LIST = ["/libAVAPIs.so", "/libIOTCAPIs.so"]

    @staticmethod
    async def _download_file(url: URL, tempfile: IO[bytes]) -> None:
        async with ClientSession() as session:
            response = await session.get(url, raise_for_status=True)
            while True:
                chunk = await response.content.read(Setup.CHUNK_SIZE)
                if not chunk:
                    break
                tempfile.write(chunk)
            tempfile.flush()

    @staticmethod
    def _detect_system(
        system: Optional[str] = None, machine: Optional[str] = None
    ) -> Tuple[str, str]:
        asystem, _, _, _, amachine, _ = platform.uname()
        if amachine in Setup.PLATFORM_X64:
            amachine = "x64"
        if system is None:
            system = asystem
            print(f"Autodetected system is {system}")
        else:
            print(f"using system {system}")
        if machine is None:
            machine = amachine
            print(f"Autodetected machine is {machine}")
        else:
            if machine in Setup.PLATFORM_X64:
                machine = "x64"
            print(f"using machine {machine}")

        return system, machine

    @staticmethod
    def _find_files(zip: ZipFile, system: str, machine: str) -> Iterable[str]:
        files = [
            fname
            for fname in zip.namelist()
            for f in Setup.FILE_LIST
            if fname.endswith(f) and system in fname and machine in fname
        ]
        return files

    @staticmethod
    def _get_target_dir():
        return Path.cwd().joinpath("p2pcam", "lib")

    @staticmethod
    def _extract_lib(
        fd: IO[bytes],
        system: Optional[str] = None,
        machine: Optional[str] = None,
    ) -> None:
        system, machine = Setup._detect_system(system, machine)
        targetdir = Setup._get_target_dir()
        os.makedirs(targetdir, exist_ok=True)
        with ZipFile(file=fd) as zip:
            files = Setup._find_files(zip, system, machine)
            for file in files:
                targetpath = targetdir.joinpath(Path(file).name)
                with zip.open(file) as source, targetpath.open("wb") as target:
                    shutil.copyfileobj(source, target)

    @staticmethod
    async def _process_url(
        url: URL,
        system: Optional[str] = None,
        machine: Optional[str] = None,
    ) -> None:
        try:
            with tempfile.NamedTemporaryFile(mode="r+b") as fd:
                await Setup._download_file(url, fd)
                Setup._extract_lib(fd, system=system, machine=machine)
        except Exception as ex:
            print(ex)

    @staticmethod
    async def _process_file(files: Iterable[Path]) -> None:
        targetdir = Setup._get_target_dir()
        for file in files:
            targetpath = targetdir.joinpath(file.name)
            shutil.copyfile(file, targetpath)


def install_libs(args=None):
    parser = argparse.ArgumentParser(
        description="Install platform shared library"
    )

    parser.add_argument(
        "-v",
        "--version",
        help="version",
        action="version",
        version="p2pcam 1.0",
    )
    parser.add_argument(
        "paths",
        metavar="URL or FILES",
        type=str,
        action="append",
        help="url to the sdk zip or paths to lib files added. See README",
    )
    parser.add_argument(
        "--system",
        default=None,
        type=str,
        help="system name like Linux, Windows; use with url; system is autodetected if skipped.",
    )
    parser.add_argument(
        "--machine",
        default=None,
        type=str,
        help="machine name like x64, x86; use with url; machine is autodetected if skipped.",
    )

    args = parser.parse_args(args=args)
    paths: List[str] = args.paths
    if len(paths) == 1:
        result = urlparse(paths[0])
        if all([result.scheme, result.netloc, result.path]):
            url = URL(paths[0])
            process = Setup._process_url(url, args.system, args.machine)
            asyncio.run(process)
        else:
            parser.error(f"Bad url")
    else:
        files = [Path(f) for f in paths if os.path.isfile(f)]
        if len(files) == 0:
            parser.error(f"Files does not exist")
        if args.system:
            parser._print_message("Ignoring option --system")
        if args.machine:
            parser._print_message("Ignoring option --machine")
        process = Setup._process_file(files)
