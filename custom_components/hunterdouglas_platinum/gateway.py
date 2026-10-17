"""Async client for the Hunter Douglas Platinum gateway (TCP port 522).

Protocol notes (plain text, no auth):
  * On connect the gateway sends a greeting ending in "HunterDouglas Shade Controller".
  * Every line it sends is prefixed with "<n> " and terminated with "\\n\\r".
  * $dat            -> streams configuration + state, ends with "$upd01-"
  * $pssSS-FF-LLL   -> stage a move (shade SS, feature FF, level 000-255), ack "$done"
  * $rls            -> execute all staged moves, ack "$act00-00-"
  * $inmNN-         -> run scene NN, ack "$act00-00-"
  * $dmy            -> ping, ack "$ack"

Known feature codes:
  04 = bottom rail (standard shade position)
  18 = middle rail on top-down/bottom-up shades
  Vane/tilt features are reported by the gateway in $cp lines and discovered at runtime.

The gateway copes badly with concurrent connections, so every exchange is
serialised through one lock and done in a short-lived session.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
import re

_LOGGER = logging.getLogger(__name__)

DEFAULT_PORT = 522
GREETING = "Shade Controller"

SENTINEL_DATA = "$upd01-"
SENTINEL_STAGED = "$done"
SENTINEL_ACT = "$act00-00-"
SENTINEL_PING = "$ack"

_PREFIX_RE = re.compile(r"^\d+\s+")
_LINE_SPLIT_RE = re.compile(r"[\r\n]+")

_ROOM_RE = re.compile(r"^\$cr(\d\d)-(\d\d)-([^-]*)-(.*)$")
_SHADE_RE = re.compile(r"^\$cs(\d\d)-(\d\d)-([^-]*)-(.*)$")
_SCENE_RE = re.compile(r"^\$cm(\d\d)-(.*)$")
_POS_RE = re.compile(r"^\$cp(\d\d)-(\d\d)-(\d{3})-?$")
_FIRM_RE = re.compile(r"^\$firm\d*-(.*)$")
_MAC_RE = re.compile(r"^\$MAC0x(.*?)-?$")
_HOUSE_RE = re.compile(r"^\$ct(.*)$")


class PlatinumError(Exception):
    """Communication problem with the gateway."""


@dataclass
class Room:
    id: str
    shade_type: str
    name: str
    shade_ids: list[str] = field(default_factory=list)


@dataclass
class Shade:
    id: str
    room_id: str
    name: str
    # feature code -> level 0-255, as last reported / commanded
    positions: dict[str, int] = field(default_factory=dict)


@dataclass
class Scene:
    id: str
    name: str


@dataclass
class PlatinumData:
    house_name: str = ""
    firmware: str = ""
    mac: str = ""
    rooms: dict[str, Room] = field(default_factory=dict)
    shades: dict[str, Shade] = field(default_factory=dict)
    scenes: dict[str, Scene] = field(default_factory=dict)
    raw_lines: list[str] = field(default_factory=list)


def _last_field(text: str) -> str:
    """Names are the last '-' separated field; fall back to the whole text."""
    name = text.rsplit("-", 1)[-1].strip()
    return name or text.strip("- ").strip()


def parse_data(lines: list[str]) -> PlatinumData:
    """Parse the lines returned by $dat."""
    data = PlatinumData(raw_lines=list(lines))
    for line in lines:
        if m := _POS_RE.match(line):
            shade_id, feature, level = m.group(1), m.group(2), int(m.group(3))
            shade = data.shades.setdefault(shade_id, Shade(shade_id, "", f"Shade {shade_id}"))
            shade.positions[feature] = level
        elif m := _SHADE_RE.match(line):
            shade_id = m.group(1)
            shade = data.shades.setdefault(shade_id, Shade(shade_id, "", ""))
            shade.room_id = m.group(2)
            shade.name = m.group(4).strip() or f"Shade {shade_id}"
        elif m := _ROOM_RE.match(line):
            data.rooms[m.group(1)] = Room(m.group(1), m.group(2), m.group(4).strip() or f"Room {m.group(1)}")
        elif m := _SCENE_RE.match(line):
            data.scenes[m.group(1)] = Scene(m.group(1), _last_field(m.group(2)) or f"Scene {m.group(1)}")
        elif m := _FIRM_RE.match(line):
            data.firmware = m.group(1).strip()
        elif m := _MAC_RE.match(line):
            data.mac = m.group(1).strip()
        elif line.startswith("$ct") and (m := _HOUSE_RE.match(line)):
            data.house_name = m.group(1).strip()

    for shade in data.shades.values():
        if room := data.rooms.get(shade.room_id):
            room.shade_ids.append(shade.id)
    return data


class _Session:
    """One TCP session with the gateway."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, timeout: float) -> None:
        self._reader = reader
        self._writer = writer
        self._timeout = timeout
        self._buffer = ""
        self._lines: list[str] = []

    async def _next_line(self) -> str:
        while not self._lines:
            chunk = await asyncio.wait_for(self._reader.read(1024), self._timeout)
            if not chunk:
                raise PlatinumError("Gateway closed the connection")
            self._buffer += chunk.decode("ascii", errors="replace")
            parts = _LINE_SPLIT_RE.split(self._buffer)
            self._buffer = parts.pop()  # incomplete tail
            for part in parts:
                part = _PREFIX_RE.sub("", part.strip())
                if part:
                    self._lines.append(part)
            # The greeting / sentinels may arrive without a trailing newline.
            tail = _PREFIX_RE.sub("", self._buffer.strip())
            if tail.endswith(GREETING) or tail in (SENTINEL_DATA, SENTINEL_STAGED, SENTINEL_ACT, SENTINEL_PING):
                self._lines.append(tail)
                self._buffer = ""
        return self._lines.pop(0)

    async def read_until(self, sentinel: str) -> list[str]:
        lines: list[str] = []
        while True:
            line = await self._next_line()
            if line == sentinel or line.endswith(sentinel):
                return lines
            if line.startswith("$ctb"):  # unsolicited noise some firmware emits
                continue
            lines.append(line)

    async def greet(self) -> None:
        while True:
            line = await self._next_line()
            if line.endswith(GREETING):
                return

    async def command(self, cmd: str, sentinel: str) -> list[str]:
        _LOGGER.debug("-> %s", cmd)
        self._writer.write(cmd.encode("ascii"))
        await self._writer.drain()
        lines = await self.read_until(sentinel)
        _LOGGER.debug("<- %d lines (sentinel %s)", len(lines), sentinel)
        return lines

    async def close(self) -> None:
        self._writer.close()
        try:
            await self._writer.wait_closed()
        except OSError:
            pass


class PlatinumGateway:
    """High level gateway API."""

    def __init__(self, host: str, port: int = DEFAULT_PORT, timeout: float = 10.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._lock = asyncio.Lock()
        self._pending: dict[tuple[str, str], int] = {}
        self._flush_task: asyncio.Task | None = None
        self._flush_done: asyncio.Future | None = None
        self._collecting = False
        self.batch_delay = 0.4

    async def _run(self, commands: list[tuple[str, str]]) -> list[list[str]]:
        async with self._lock:
            last_err: Exception | None = None
            for attempt in range(2):
                try:
                    reader, writer = await asyncio.wait_for(
                        asyncio.open_connection(self.host, self.port), self.timeout
                    )
                except (OSError, asyncio.TimeoutError) as err:
                    last_err = err
                    await asyncio.sleep(1)
                    continue
                session = _Session(reader, writer, self.timeout)
                try:
                    await session.greet()
                    return [await session.command(c, s) for c, s in commands]
                except (OSError, asyncio.TimeoutError, PlatinumError) as err:
                    last_err = err
                    _LOGGER.debug("Attempt %s failed: %s", attempt + 1, err)
                finally:
                    await session.close()
                    # The gateway needs a moment before it accepts the next connection.
                    await asyncio.sleep(0.3)
                await asyncio.sleep(1)
            raise PlatinumError(f"Could not talk to gateway {self.host}:{self.port}: {last_err}")

    async def get_data(self) -> PlatinumData:
        (lines,) = await self._run([("$dat", SENTINEL_DATA)])
        return parse_data(lines)

    async def ping(self) -> None:
        await self._run([("$dmy", SENTINEL_PING)])

    async def set_positions(self, moves: list[tuple[str, str, int]]) -> None:
        """Stage several moves and execute them together with a single $rls."""
        if not moves:
            return
        cmds = [
            (f"$pss{int(shade):02d}-{int(feature):02d}-{max(0, min(255, int(level))):03d}", SENTINEL_STAGED)
            for shade, feature, level in moves
        ]
        cmds.append(("$rls", SENTINEL_ACT))
        await self._run(cmds)

    async def queue_move(self, shade_id: str, feature: str, level: int) -> None:
        """Queue a move; moves arriving within batch_delay are sent in one session.

        This keeps the gateway happy when an automation moves a whole room at once.
        """
        self._pending[(shade_id, feature)] = level
        if not self._collecting:
            loop = asyncio.get_running_loop()
            self._collecting = True
            self._flush_done = loop.create_future()
            self._flush_task = loop.create_task(self._flush(self._flush_done))
        assert self._flush_done is not None
        await asyncio.shield(self._flush_done)

    async def _flush(self, done: asyncio.Future) -> None:
        await asyncio.sleep(self.batch_delay)
        moves = [(s, f, lvl) for (s, f), lvl in self._pending.items()]
        self._pending.clear()
        self._collecting = False  # later moves start a new batch
        try:
            await self.set_positions(moves)
        except Exception as err:  # noqa: BLE001 - propagate to every waiter
            if done and not done.done():
                done.set_exception(err)
        else:
            if done and not done.done():
                done.set_result(None)

    async def activate_scene(self, scene_id: str) -> None:
        await self._run([(f"$inm{int(scene_id):02d}-", SENTINEL_ACT)])
