#!/usr/bin/env python3
"""Generate maps/sl_dev_room.vmf -- the empty room to start a new map in.

Everything a first map needs and nothing more: a sealed 1024x1024x384 room of
dev-textured world brushes (so it never leaks and always vis-compiles), an
info_player_start, and a light. Copy it in Hammer (File > Save As under a new
name) rather than editing this one in place, or the next run of this script
overwrites you.

    python3 tools/build_sl_dev_room.py            # writes maps/sl_dev_room.vmf

Brush/solid emission is reused from tools/build_prototype_v1.py so the plane
winding matches the shipped maps exactly.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from build_prototype_v1 import Vmf, uid, q, box_solid  # noqa: E402

MOD = os.path.dirname(HERE)
OUT = os.path.join(MOD, "maps", "sl_dev_room.vmf")

# dev textures that ship with HL2 (materials/dev/)
DEV = "DEV/DEV_MEASUREGENERIC01B"
GRID = "DEV/DEV_MEASUREWALL01A"

# room interior
X1, X2 = -512, 512
Y1, Y2 = -512, 512
Z1, Z2 = 0, 384
WALL = 16

COL_FLOOR = 200
COL_CEIL = 320


def build():
    v = Vmf()
    v.world_kv = [("skyname", "sky_day01_01")]

    # shell: floor, ceiling, four walls (world brushes -> seals the map)
    v.world((X1 - WALL, Y1 - WALL, Z1 - WALL), (X2 + WALL, Y2 + WALL, Z1), DEV, 16)      # floor
    v.world((X1 - WALL, Y1 - WALL, Z2), (X2 + WALL, Y2 + WALL, Z2 + WALL), DEV, 16)     # ceiling
    v.world((X1 - WALL, Y1 - WALL, Z1), (X1, Y2 + WALL, Z2), GRID, 16)                  # -x
    v.world((X2, Y1 - WALL, Z1), (X2 + WALL, Y2 + WALL, Z2), GRID, 16)                  # +x
    v.world((X1, Y1 - WALL, Z1), (X2, Y1, Z2), GRID, 16)                                # -y
    v.world((X1, Y2, Z1), (X2, Y2 + WALL, Z2), GRID, 16)                                # +y

    # spawn: on the floor, in the middle, looking down +X (yaw 0)
    v.entity("info_player_start", {"origin": "0 0 %d" % (Z1 + 24), "angles": "0 0 0"})

    # lighting: one overhead lamp plus a weak fill so the room is never black
    v.entity("light", {
        "origin": "0 0 %d" % COL_CEIL,
        "_light": "255 244 220 300",
        "_distance": "700",
    })
    v.entity("light", {
        "origin": "0 0 %d" % (Z1 + 120),
        "_light": "90 100 120 60",
        "_distance": "900",
    })

    # cubemap so reflective materials in the room have something to sample
    v.entity("env_cubemap", {"origin": "0 0 %d" % (Z1 + 180)})

    # a couple of reference props to check scale against
    v.entity("prop_physics", {
        "origin": "%d %d %d" % (X1 + 200, Y1 + 200, Z1 + 16),
        "angles": "0 30 0",
        "model": "models/props_junk/wood_crate001a.mdl",
    })
    v.entity("prop_physics", {
        "origin": "%d %d %d" % (X1 + 200, Y1 + 120, Z1 + 16),
        "angles": "0 0 0",
        "model": "models/props_c17/oildrum001.mdl",
    })

    return v.build()


def main():
    text = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        f.write(text)
    print("wrote %s (%d bytes)" % (OUT, len(text)))
    print("open it in Hammer, then File > Save As to start your own map")


if __name__ == "__main__":
    main()
