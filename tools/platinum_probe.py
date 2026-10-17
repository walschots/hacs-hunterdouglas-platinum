#!/usr/bin/env python3
"""Probe a Hunter Douglas Platinum gateway from any computer (Python 3.11+, no extra packages).

  python3 platinum_probe.py 192.168.1.50 dump            # rooms, shades, feature codes, scenes
  python3 platinum_probe.py 192.168.1.50 raw             # raw $dat output
  python3 platinum_probe.py 192.168.1.50 watch           # print every feature change (find the vane code!)
  python3 platinum_probe.py 192.168.1.50 move 03 04 128  # shade 03, feature 04, level 0-255
  python3 platinum_probe.py 192.168.1.50 scene 01

Finding the vane code: start `watch`, then in the Platinum App tilt the vanes of one
shade. The line that changes tells you the feature code. Enter it in the integration's
options as "Vane feature code".
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "custom_components" / "hunterdouglas_platinum"))
from gateway import PlatinumGateway  # noqa: E402

KNOWN = {"04": "bottom rail", "18": "middle rail (top-down)"}


def describe(data) -> None:
    print(f"House: {data.house_name or '-'}   firmware: {data.firmware or '-'}   MAC: {data.mac or '-'}\n")
    for room in sorted(data.rooms.values(), key=lambda r: r.id):
        tdbu = "  [top-down/bottom-up]" if room.shade_type in ("02", "13") else ""
        print(f"Room {room.id} '{room.name}' (shade type {room.shade_type}){tdbu}")
        for sid in sorted(room.shade_ids):
            shade = data.shades[sid]
            print(f"   Shade {sid} '{shade.name}'")
            for feature, level in sorted(shade.positions.items()):
                print(f"      feature {feature}: {level:3d}/255 ({round(level * 100 / 255):3d}%)  {KNOWN.get(feature, '<- unknown, vanes?')}")
    orphans = [s for s in data.shades.values() if s.room_id not in data.rooms]
    for shade in orphans:
        print(f"Shade {shade.id} '{shade.name}' (no room) features {shade.positions}")
    if data.scenes:
        print("\nScenes:")
        for scene in sorted(data.scenes.values(), key=lambda s: s.id):
            print(f"   {scene.id} '{scene.name}'")


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("host")
    p.add_argument("--port", type=int, default=522)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("dump")
    sub.add_parser("raw")
    w = sub.add_parser("watch")
    w.add_argument("--interval", type=float, default=3.0)
    m = sub.add_parser("move")
    m.add_argument("shade")
    m.add_argument("feature")
    m.add_argument("level", type=int)
    s = sub.add_parser("scene")
    s.add_argument("scene")
    args = p.parse_args()

    gw = PlatinumGateway(args.host, args.port)
    if args.cmd == "dump":
        describe(await gw.get_data())
    elif args.cmd == "raw":
        print("\n".join((await gw.get_data()).raw_lines))
    elif args.cmd == "move":
        await gw.set_positions([(args.shade, args.feature, args.level)])
        print(f"Sent shade {args.shade} feature {args.feature} -> {args.level}")
    elif args.cmd == "scene":
        await gw.activate_scene(args.scene)
        print(f"Activated scene {args.scene}")
    elif args.cmd == "watch":
        prev = None
        print("Watching... change something in the Platinum App (Ctrl+C to stop)")
        while True:
            try:
                data = await gw.get_data()
            except Exception as err:  # noqa: BLE001
                print(f"  (gateway busy: {err})")
                await asyncio.sleep(args.interval)
                continue
            snap = {(s.id, f): lvl for s in data.shades.values() for f, lvl in s.positions.items()}
            if prev is None:
                describe(data)
                print("\nBaseline captured.")
            else:
                for key in sorted(set(snap) | set(prev)):
                    if snap.get(key) != prev.get(key):
                        sid, feat = key
                        name = data.shades[sid].name if sid in data.shades else "?"
                        print(f"  CHANGE shade {sid} '{name}' feature {feat}: {prev.get(key)} -> {snap.get(key)}  {KNOWN.get(feat, '<- candidate vane code')}")
            prev = snap
            await asyncio.sleep(args.interval)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
