#!/usr/bin/env python3
"""Generate maps/sl_arsenal_test.vmf - the Shattered Life arsenal/mechanics test map.

Layout: one sealed outer shell (world brushes, nodraw) with all playable
geometry built as func_detail.  Nothing can leak, the whole map is a single
vis leaf (no vis tuning, fast compiles) and none of the test areas are ever
culled out of view.

Zones:
  HUB (centre)       spawn, re-arm pad, health/suit chargers
  GUN RANGE (east)   deagle / organic rifle / aperture GL lanes, 256u floor bands
                     plus a spawn bay (npc_maker pads) for damage testing
  PARKOUR (north)    jumps, crouch tunnel, pit with teleport-back, grapple beam
  PORTAL LAB (west)  walk-through portals, 256u drop platform, no-portal volume
  BLAST PIT (south)  splash/AoE sandbox with destructible targets

Usage:
    python3 tools/build_sl_arsenal_test.py
Then compile from the mod root, e.g.:
    wine "<HL2>/bin/vbsp.exe" -game . maps/sl_arsenal_test.vmf
    wine "<HL2>/bin/vvis.exe" -game . maps/sl_arsenal_test
    wine "<HL2>/bin/vrad.exe" -game . maps/sl_arsenal_test
"""

import os

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "maps", "sl_arsenal_test.vmf")

# --------------------------------------------------------------------------
# materials known to ship with HL2
# --------------------------------------------------------------------------
FLOOR = "CONCRETE/CONCRETEFLOOR001A"
FLOOR_ALT = "DEV/DEV_MEASUREGENERIC01B"
CEIL = "CONCRETE/CONCRETECEILING001A"
WALL = "CONCRETE/CONCRETEWALL006A"
PANEL = "DEV/DEV_MEASUREWALL01A"
METAL = "METAL/METALWALL048A"
METAL_FLOOR = "METAL/METALFLOOR002A"
GLASS = "GLASS/GLASSWINDOW007A"
NODRAW = "TOOLS/TOOLSNODRAW"
BUTTON = "LIGHTS/FLUORESCENTWHITE001A"

_uid = [100]


def uid():
    _uid[0] += 1
    return _uid[0]


def q(s):
    return '"%s"' % s


FACE_AXES = {
    # point order matches the shipped sl_cold_open.vmf brushes
    "+x": ("({Mx} {my} {Mz})", "({Mx} {My} {Mz})", "({Mx} {My} {mz})", "[0 1 0 0]", "[0 0 -1 0]"),
    "-x": ("({mx} {My} {mz})", "({mx} {My} {Mz})", "({mx} {my} {Mz})", "[0 1 0 0]", "[0 0 -1 0]"),
    "-y": ("({mx} {my} {Mz})", "({Mx} {my} {Mz})", "({Mx} {my} {mz})", "[1 0 0 0]", "[0 0 -1 0]"),
    "+y": ("({Mx} {My} {mz})", "({Mx} {My} {Mz})", "({mx} {My} {Mz})", "[1 0 0 0]", "[0 0 -1 0]"),
    "-z": ("({Mx} {my} {mz})", "({Mx} {My} {mz})", "({mx} {My} {mz})", "[1 0 0 0]", "[0 -1 0 0]"),
    "+z": ("({mx} {My} {Mz})", "({Mx} {My} {Mz})", "({Mx} {my} {Mz})", "[1 0 0 0]", "[0 -1 0 0]"),
}


def box_solid(mn, mx, mat, lightmap=16):
    x1, y1, z1 = mn
    x2, y2, z2 = mx
    assert x2 > x1 and y2 > y1 and z2 > z1, (mn, mx)
    fmt = dict(mx=x1, my=y1, mz=z1, Mx=x2, My=y2, Mz=z2)
    out = ["\tsolid", "\t{", '\t\t"id" %s' % q(uid())]
    for key in ("+x", "-x", "-y", "+y", "-z", "+z"):
        p0, p1, p2, uax, vax = FACE_AXES[key]
        out += [
            "\t\tside",
            "\t\t{",
            '\t\t\t"id" %s' % q(uid()),
            '\t\t\t"plane" %s' % q("%s %s %s" % (p0.format(**fmt),
                                                     p1.format(**fmt),
                                                     p2.format(**fmt))),
            '\t\t\t"material" %s' % q(mat),
            '\t\t\t"uaxis" %s' % q("%s 0.25" % uax),
            '\t\t\t"vaxis" %s' % q("%s 0.25" % vax),
            '\t\t\t"rotation" "0"',
            '\t\t\t"lightmapscale" "%d"' % lightmap,
            '\t\t\t"smoothing_groups" "0"',
            "\t\t}",
        ]
    out.append("\t}")
    return "\n".join(out)


class Vmf:
    def __init__(self):
        self.world_brushes = []
        self.entities = []
        self.world_kv = []

    # ---- geometry ---------------------------------------------------
    def world(self, mn, mx, mat=NODRAW, lightmap=16):
        self.world_brushes.append(box_solid(mn, mx, mat, lightmap))

    def detail(self, mn, mx, mat=FLOOR, lightmap=16):
        self.entity("func_detail", {}, [box_solid(mn, mx, mat, lightmap)])

    def brush_entity(self, classname, kv, boxes, mat=FLOOR, lightmap=16):
        self.entity(classname, kv,
                    [box_solid(mn, mx, mat, lightmap) for mn, mx in boxes])

    # ---- point entities ---------------------------------------------
    def entity(self, classname, kv, solids=None):
        kv = dict(kv)
        kv["classname"] = classname
        kv["id"] = str(uid())

        body = ["entity", "{"]
        order = ["classname", "targetname"]
        keys = [k for k in order if k in kv] + \
               [k for k in kv if k not in order]
        for k in keys:
            body.append("\t%s %s" % (q(k), q(kv[k])))
        for s in (solids or []):
            body.append(s)
        body.append("}")
        self.entities.append("\n".join(body))

    def build(self):
        head = [
            "versioninfo", "{",
            '\t"editorversion" "400"',
            '\t"editorbuild" "8075"',
            '\t"mapversion" "1"',
            '\t"formatversion" "100"',
            '\t"prefab" "0"', "}",
            "visgroups", "{", "}",
            "viewsettings", "{",
            '\t"bSnapToGrid" "1"',
            '\t"bShowGrid" "1"',
            '\t"nGridSpacing" "16"',
            '\t"bShow3DGrid" "0"', "}",
            "world", "{",
            '\t"id" "1"',
            '\t"mapversion" "1"',
            '\t"classname" "worldspawn"',
        ]
        for k, kv in self.world_kv:
            head.append("\t%s %s" % (q(k), q(kv)))
        head += self.world_brushes
        head.append("}")
        return "\n".join(head + self.entities) + "\n"


# --------------------------------------------------------------------------
# geometry helpers
# --------------------------------------------------------------------------
WALL_T = 16


def wall(v, mat, axis, pos, a1, a2, z1, z2, doors=(), thickness=WALL_T):
    """Wall slab at pos..pos+thickness with optional door holes.

    axis 'x': constant x, spans y in [a1,a2]
    axis 'y': constant y, spans x in [a1,a2]
    doors: (centre, width, height) holes from z1 upward.
    """
    def emit(aa, bb, bz1, bz2):
        if axis == "x":
            v.detail((pos, aa, bz1), (pos + thickness, bb, bz2), mat)
        else:
            v.detail((aa, pos, bz1), (bb, pos + thickness, bz2), mat)

    cursor = a1
    for centre, width, height in sorted(doors, key=lambda d: d[0]):
        d1, d2 = centre - width // 2, centre + width // 2
        if d1 > cursor:
            emit(cursor, d1, z1, z2)
        if z1 + height < z2:
            emit(d1, d2, z1 + height, z2)
        cursor = d2
    if cursor < a2:
        emit(cursor, a2, z1, z2)


def floor_slab(v, x1, y1, x2, y2, z=0, mat=FLOOR, t=16):
    v.detail((x1, y1, z - t), (x2, y2, z), mat)


def ceiling_slab(v, x1, y1, x2, y2, z, mat=CEIL, t=16):
    v.detail((x1, y1, z), (x2, y2, z + t), mat)


def pit(v, x1, y1, x2, y2, depth=-208, top=-16, mat=FLOOR, wall_mat=WALL):
    """Sunken pit: bottom slab plus shaft walls outside the hole."""
    floor_slab(v, x1, y1, x2, y2, depth, METAL_FLOOR)
    v.detail((x1 - WALL_T, y1, depth), (x1, y2, top), wall_mat)
    v.detail((x2, y1, depth), (x2 + WALL_T, y2, top), wall_mat)
    v.detail((x1 - WALL_T, y1 - WALL_T, depth), (x2 + WALL_T, y1, top), wall_mat)
    v.detail((x1 - WALL_T, y2, depth), (x2 + WALL_T, y2 + WALL_T, top), wall_mat)


# _distance 0 means "no falloff" in Source: every light then reaches every
# surface in the map and the sum of them blows the lightmaps out to white.
# Give each light a real radius so pools of light stay local.
def light(v, x, y, z, bright=260, colour=(255, 250, 235), dist=512):
    r, g, b = colour
    v.entity("light", {
        "origin": "%d %d %d" % (x, y, z),
        "_light": "%d %d %d %d" % (r, g, b, bright),
        "_distance": "%d" % dist,
    })


def lights_grid(v, x1, y1, x2, y2, z, step, bright=260, dist=512):
    x = x1
    while x <= x2:
        y = y1
        while y <= y2:
            light(v, x, y, z, bright, dist=dist)
            y += step
        x += step


def text(v, name, message, channel=2, x="0.03", y="0.30", hold=6,
         colour=(255, 235, 140)):
    r, g, b = colour
    v.entity("game_text", {
        "targetname": name,
        "message": message,
        "x": x, "y": y,
        "channel": str(channel),
        "color": "%d %d %d" % (r, g, b),
        "color2": "%d %d %d" % (r, g, b),
        "effect": "0", "fxtime": "0",
        "holdtime": str(hold),
        "spawnflags": "0",
    })


def hint(v, text_name, mn, mx):
    """Trigger volume that re-displays a game_text for players entering a zone."""
    v.brush_entity("trigger_multiple",
                   {"targetname": "trg_" + text_name, "wait": "20",
                    "spawnflags": "1"},
                   [(mn, mx)], mat=NODRAW)
    # NOTE: this vbsp build keeps only ONE connection per output name on an
    # entity, so every hint gets its own trigger and every output name is used
    # at most once per entity (see OUTPUTS).


def prop(v, model, origin, angles="0 0 0", cls="prop_physics"):
    v.entity(cls, {"origin": origin, "angles": angles, "model": model})


def breakable(v, mn, mx, health=10, mat_index=0, mat=GLASS):
    v.brush_entity("func_breakable",
                   {"health": str(health), "material": str(mat_index),
                    "spawnflags": "0", "explosion": "0"},
                   [(mn, mx)], mat=mat)


# --------------------------------------------------------------------------
# the map
# --------------------------------------------------------------------------
def build():
    v = Vmf()
    v.world_kv = [
        ("skyname", "sky_day01_01"),
        ("maxpropscreenwidth", "-1"),
        ("detailvbsp", "detail.vbsp"),
        ("detailmaterial", "detail/detailsprites"),
    ]

    # ---------------- sealed outer shell (never visible) ----------------
    v.world((-3552, -2160, -352), (3808, 3600, -288))        # floor
    v.world((-3552, -2160, 1104), (3808, 3600, 1168))        # ceiling
    v.world((-3552, -2160, -288), (-3488, 3536, 1104))       # west
    v.world((3744, -2160, -288), (3808, 3536, 1104))         # east
    v.world((-3488, -2160, -288), (3744, -2096, 1104))       # south
    v.world((-3488, 3536, -288), (3744, 3600, 1104))         # north

    # =====================================================================
    # HUB  interior x[-512,512] y[-384,384] z[0,320]
    # =====================================================================
    floor_slab(v, -544, -416, 544, 416)
    ceiling_slab(v, -544, -416, 544, 416, 320)
    wall(v, WALL, "x", -544, -416, 416, 0, 320, doors=[(0, 128, 144)])
    wall(v, WALL, "x", 512, -416, 416, 0, 320, doors=[(0, 128, 144)])
    wall(v, WALL, "y", -416, -544, 544, 0, 320, doors=[(0, 128, 144)])
    wall(v, WALL, "y", 384, -544, 544, 0, 320, doors=[(0, 128, 144)])

    # corridors (span the gap between the room walls they connect).  Floors
    # run from one room floor edge to the other so nothing can be stepped
    # through into the shell, and threshold strips cover the wall footprints.
    v.detail((544, -80, 0), (672, -64, 160), WALL)          # east
    v.detail((544, 64, 0), (672, 80, 160), WALL)
    floor_slab(v, 544, -80, 672, 80, 0, FLOOR_ALT)
    ceiling_slab(v, 544, -80, 672, 80, 144)
    floor_slab(v, 672, -80, 688, 80, 0, FLOOR_ALT)          # range threshold

    v.detail((-672, -80, 0), (-544, -64, 160), WALL)        # west
    v.detail((-672, 64, 0), (-544, 80, 160), WALL)
    floor_slab(v, -672, -80, -544, 80, 0, FLOOR_ALT)
    ceiling_slab(v, -672, -80, -544, 80, 144)
    floor_slab(v, -688, -80, -672, 80, 0, FLOOR_ALT)        # portal threshold

    v.detail((-80, 416, 0), (-64, 528, 160), WALL)          # north
    v.detail((64, 416, 0), (80, 528, 160), WALL)
    floor_slab(v, -80, 416, 80, 528, 0, FLOOR_ALT)
    ceiling_slab(v, -80, 416, 80, 528, 144)

    v.detail((-80, -544, 0), (-64, -416, 160), WALL)        # south
    v.detail((64, -544, 0), (80, -416, 160), WALL)
    floor_slab(v, -80, -544, 80, -416, 0, FLOOR_ALT)
    ceiling_slab(v, -80, -544, 80, -416, 144)
    floor_slab(v, -80, -544, 80, -528, 0, FLOOR_ALT)        # blast threshold

    lights_grid(v, -300, -200, 300, 200, 288, 400, 55, 520)

    v.entity("info_player_start", {"origin": "-300 -200 16", "angles": "0 30 0"})
    v.entity("item_healthcharger", {
        "origin": "-140 -392 20", "angles": "0 90 0",
        "model": "models/props_combine/health_charger001.mdl",
    })
    v.entity("item_suitcharger", {
        "origin": "140 376 20", "angles": "0 270 0",
        "model": "models/props_combine/suit_charger001.mdl",
    })

    # re-arm pad on the east wall.  A func_button brush here makes this mod's
    # client hang during map load (bisected: geometry+lights+button alone hangs,
    # the same map without it loads), so the refill is a touch pad instead.
    v.detail((470, -220, 0), (500, -120, 8), BUTTON)
    v.brush_entity("trigger_multiple",
                   {"targetname": "trg_rearm", "wait": "20",
                    "spawnflags": "1"},
                   [((462, -220, 0), (500, -120, 96))], mat=NODRAW)

    v.entity("point_servercommand", {"targetname": "sl_cmd"})
    # Give the arsenal only once the player is actually in the world.  Running
    # it from OnMapSpawn (during signon) is what froze the first build.
    v.brush_entity("trigger_once",
                   {"targetname": "trg_arm", "spawnflags": "1",
                    "wait": "0"},
                   [((-470, -394, 0), (-130, -110, 170))], mat=NODRAW)

    for i, (x, y) in enumerate([(260, 250), (170, 300), (-260, 250)]):
        prop(v, "models/props_junk/wood_crate001a.mdl",
             "%d %d 0" % (x, y), "%d 0 0" % (15 * i))
    prop(v, "models/props_c17/oildrum001.mdl", "300 -80 0", "0 20 0")

    text(v, "txt_hub",
         "SL ARSENAL TEST MAP -- step on the east pad to re-arm",
         1, "0.16", "0.22", 12)
    text(v, "txt_hub2",
         "E gun range | W portal lab | N parkour | S blast pit",
         3, "0.18", "0.31", 12)
    hint(v, "txt_hub", (-460, -384, 0), (-140, -120, 160))
    hint(v, "txt_hub2", (-460, -384, 0), (-140, -120, 160))

    # =====================================================================
    # GUN RANGE  interior x[688,3600] y[-768,768] z[0,448]
    # =====================================================================
    x, band = 688, 0
    while x < 3600:                                  # 256u measuring bands
        x2 = min(x + 256, 3600)
        floor_slab(v, x, -784, x2, 784, 0,
                   FLOOR if band % 2 == 0 else FLOOR_ALT)
        x, band = x2, band + 1
    ceiling_slab(v, 672, -784, 3616, 784, 448)
    wall(v, WALL, "x", 672, -784, 784, 0, 448, doors=[(0, 128, 144)])
    wall(v, WALL, "x", 3600, -784, 784, 0, 448)
    wall(v, WALL, "y", -784, 672, 3616, 0, 448)
    wall(v, WALL, "y", 768, 672, 3616, 0, 448)
    lights_grid(v, 960, -512, 3360, 512, 420, 768, 75, 860)

    lanes = (-420, 0, 420)
    for lane in lanes:                               # 256u
        prop(v, "models/props_junk/wood_crate001a.mdl", "944 %d 0" % lane)
        prop(v, "models/props_junk/wood_crate001a.mdl",
             "944 %d 52" % lane, "0 18 0")
        prop(v, "models/props_junk/wood_crate001a.mdl",
             "1000 %d 0" % lane, "0 32 0")
    for lane in lanes:                               # 512u
        prop(v, "models/props_c17/oildrum001.mdl", "1200 %d 0" % lane)
    for lane in lanes:                               # 1024u
        breakable(v, (1656, lane - 64, 0), (1664, lane + 64, 96), 10, 0)
        breakable(v, (1656, lane - 64, 112), (1664, lane + 64, 208), 10, 0)
    for lane in lanes:                               # 2048u
        prop(v, "models/props_c17/metalpot001a.mdl", "2736 %d 0" % lane)
        breakable(v, (2700, lane - 32, 40), (2708, lane + 32, 104), 30, 2, METAL)

    text(v, "txt_range",
         "GUN RANGE -- floor bands are 256u: targets at 256 / 512 / 1024 / 2048",
         2, "0.03", "0.26", 8)
    hint(v, "txt_range", (688, -80, 0), (770, 80, 160))

    # ------------------------------------------------------------------
    # SPAWN BAY - enemy spawners for damage testing.  Each pad fires the
    # Spawn input of an npc_maker that sits out on the open floor, so the
    # NPC appears ~520u in front of whoever stepped on the pad.  The
    # spawners are disabled at map start (no auto-timer); the pad is the
    # only thing that makes one.
    # ------------------------------------------------------------------
    spawners = [
        ("mk_combine", "trg_sp_combine", "npc_combine_s", 1752),
        ("mk_zombie", "trg_sp_zombie", "npc_zombie", 1892),
        ("mk_crab", "trg_sp_crab", "npc_headcrab", 2032),
        ("mk_turret", "trg_sp_turret", "npc_turret_floor", 2172),
    ]
    for (maker, pad, cls, sx) in spawners:
        v.detail((sx - 32, 640, 0), (sx + 32, 704, 8), BUTTON)
        v.brush_entity("trigger_multiple",
                       {"targetname": pad, "wait": "1", "spawnflags": "1"},
                       [((sx - 32, 640, 0), (sx + 32, 704, 96))], mat=NODRAW)
        v.entity("npc_maker", {
            "targetname": maker,
            "NPCType": cls,
            "MaxNPCCount": "4",
            "MaxLiveChildren": "4",
            "SpawnFrequency": "0",
            "StartDisabled": "1",
            "origin": "%d 120 8" % sx,
            "angles": "0 90 0",
        })
    # clear pad - npc_kill removes everything the makers spawned
    v.detail((2240, 640, 0), (2304, 704, 8), BUTTON)
    v.brush_entity("trigger_multiple",
                   {"targetname": "trg_sp_clear", "wait": "1",
                    "spawnflags": "1"},
                   [((2240, 640, 0), (2304, 704, 96))], mat=NODRAW)
    text(v, "txt_spawn",
         "SPAWN BAY -- pads: soldier | zombie | headcrab | turret | clear",
         4, "0.03", "0.36", 8)
    hint(v, "txt_spawn", (1640, 560, 0), (2320, 704, 140))

    # =====================================================================
    # PARKOUR  interior x[-600,600] y[544,3456] z[0,1024]
    # =====================================================================
    floor_slab(v, -616, 528, 616, 2720)
    pit(v, -600, 2720, 600, 3456, depth=-224, top=-16)
    ceiling_slab(v, -616, 528, 616, 3472, 1024)
    wall(v, WALL, "x", -616, 528, 3472, 0, 1024)
    wall(v, WALL, "x", 600, 528, 3472, 0, 1024)
    wall(v, WALL, "y", 528, -616, 616, 0, 1024, doors=[(0, 128, 144)])
    wall(v, WALL, "y", 3456, -616, 616, 0, 1024)
    lights_grid(v, -400, 800, 400, 3200, 1000, 800, 65, 820)

    # platform ladder - each step is 48u, inside a standing jump
    for (px1, px2, py1, py2, top) in [
        (-200, 200, 760, 960, 48),
        (-160, 160, 1060, 1200, 96),
        (-120, 120, 1310, 1420, 144),
        (-100, 100, 1540, 1620, 192),
        (-100, 100, 1760, 1830, 240),
        (-100, 100, 1980, 2040, 288),
    ]:
        v.detail((px1, py1, 0), (px2, py2, top), PANEL)

    v.detail((-300, 2260, 0), (300, 2620, 320), PANEL)      # landing
    v.detail((-300, 2380, 368), (300, 2480, 1024), WALL)    # 48u crawl gap

    for sx, sy in [(-380, 2850), (0, 3000), (380, 3150)]:   # stepping stones
        v.detail((sx - 50, sy - 50, 320), (sx + 50, sy + 50, 352), PANEL)
    v.detail((-300, 3260, 352), (300, 3400, 384), PANEL)    # finish

    v.detail((-616, 2580, 900), (616, 2600, 920), METAL)    # grapple beam
    v.detail((-616, 2900, 600), (-450, 3300, 632), METAL_FLOOR)  # high ledge

    v.entity("info_teleport_destination", {
        "origin": "0 700 24", "angles": "0 90 0", "targetname": "tp_parkour",
    })
    v.brush_entity("trigger_teleport", {"target": "tp_parkour", "spawnflags": "1"},
                   [((-600, 2740, -224), (600, 3450, -140))], mat=NODRAW)

    text(v, "txt_parkour",
         "PARKOUR -- jumps, 48u crawl tunnel, pit (falling teleports you back)",
         2, "0.03", "0.26", 8)
    hint(v, "txt_parkour", (-80, 544, 0), (80, 630, 160))

    # =====================================================================
    # PORTAL LAB  interior x[-3472,-672] y[-784,784] z[0,768]
    # =====================================================================
    # drop pit x[-3000,-2400] y[-400,400]
    floor_slab(v, -3488, -784, -3000, 784)
    floor_slab(v, -2400, -784, -672, 784)
    floor_slab(v, -3000, 400, -2400, 784)
    floor_slab(v, -3000, -784, -2400, -400)
    pit(v, -3000, -400, -2400, 400, depth=-224, top=-16)

    ceiling_slab(v, -3488, -784, -672, 784, 768)
    wall(v, WALL, "x", -3488, -784, 784, 0, 768)
    wall(v, WALL, "x", -688, -784, 784, 0, 768, doors=[(0, 128, 144)])
    wall(v, WALL, "y", -784, -3488, -672, 0, 768)
    wall(v, WALL, "y", 768, -3488, -672, 0, 768)
    lights_grid(v, -3200, -600, -800, 600, 740, 800, 65, 860)

    # A) 256u-high drop platform east of the pit, 16u stairs up its east side
    v.detail((-2400, -400, 0), (-2000, 400, 256), PANEL)
    for i in range(16):
        x2 = -2000 + 24 * (i + 1)
        v.detail((x2 - 24, -160, 0), (x2, 160, 16 * (i + 1)), WALL)

    # B) walk-through portals: two facing walls 600u apart
    v.detail((-1500, -300, 0), (-1476, 300, 448), PANEL)
    v.detail((-900, -300, 0), (-876, 300, 448), PANEL)

    # C) tall pillar for vertical tests
    v.detail((-1400, 400, 0), (-1150, 760, 576), PANEL)

    text(v, "txt_portal",
         "PORTAL LAB -- walk-through portals, 256u drop, tall pillar",
         2, "0.03", "0.26", 8)
    hint(v, "txt_portal", (-760, -80, 0), (-672, 80, 160))

    # =====================================================================
    # BLAST PIT  interior x[-600,600] y[-2080,-544] z[0,384]
    # =====================================================================
    floor_slab(v, -616, -1000, 616, -544)
    floor_slab(v, -616, -2080, 616, -1600)
    floor_slab(v, -616, -1600, -320, -1000)
    floor_slab(v, 320, -1600, 616, -1000)
    pit(v, -320, -1600, 320, -1000, depth=-224, top=-16)

    ceiling_slab(v, -616, -2096, 616, -528, 384)
    wall(v, WALL, "x", -616, -2096, -528, 0, 384)
    wall(v, WALL, "x", 600, -2096, -528, 0, 384)
    wall(v, WALL, "y", -2096, -616, 616, 0, 384)
    wall(v, WALL, "y", -544, -616, 616, 0, 384, doors=[(0, 128, 144)])
    lights_grid(v, -300, -1900, 300, -700, 356, 600, 55, 520)

    # staircase out of the pit (6 x 32u risers)
    for i in range(6):
        v.detail((320 - 32 * (i + 1), -1560, -224),
                 (320, -1440, -208 + 32 * (i + 1)), PANEL)

    for i, (px, py) in enumerate([(-200, -1400), (-60, -1300), (120, -1450),
                                  (-140, -1150), (220, -1200)]):
        prop(v, "models/props_junk/wood_crate001a.mdl",
             "%d %d -208" % (px, py), "0 %d 0" % (17 * i))
    prop(v, "models/props_c17/oildrum001_explosive.mdl", "0 -1070 -208")
    prop(v, "models/props_c17/oildrum001.mdl", "180 -1080 -208")
    breakable(v, (-200, -1584, -208), (200, -1576, -80), 40, 2, METAL)

    text(v, "txt_blast",
         "BLAST PIT -- aperture GL / organic rifle splash, 224u sunken pit",
         2, "0.03", "0.26", 8)
    hint(v, "txt_blast", (-80, -544, 0), (80, -460, 160))

    return v


# --------------------------------------------------------------------------
# I/O wiring
# --------------------------------------------------------------------------
# One connection per output name per entity: this vbsp build keeps only the
# last connection stored under a given output key.
OUTPUTS = {
    "trg_arm": [("OnStartTouch", "sl_cmd", "Command",
                 "sv_cheats 1;sl_give_arsenal", 2.0)],
    "trg_rearm": [("OnStartTouch", "sl_cmd", "Command",
                   "sv_cheats 1;sl_give_arsenal", 0.0)],
    "trg_txt_hub": [("OnStartTouch", "txt_hub", "Display", "", 0.0)],
    "trg_txt_hub2": [("OnStartTouch", "txt_hub2", "Display", "", 0.1)],
    "trg_txt_range": [("OnStartTouch", "txt_range", "Display", "", 0.0)],
    "trg_txt_parkour": [("OnStartTouch", "txt_parkour", "Display", "", 0.0)],
    "trg_txt_portal": [("OnStartTouch", "txt_portal", "Display", "", 0.0)],
    "trg_txt_blast": [("OnStartTouch", "txt_blast", "Display", "", 0.0)],
    "trg_txt_spawn": [("OnStartTouch", "txt_spawn", "Display", "", 0.0)],
    "trg_sp_combine": [("OnStartTouch", "mk_combine", "Spawn", "", 0.0)],
    "trg_sp_zombie": [("OnStartTouch", "mk_zombie", "Spawn", "", 0.0)],
    "trg_sp_crab": [("OnStartTouch", "mk_crab", "Spawn", "", 0.0)],
    "trg_sp_turret": [("OnStartTouch", "mk_turret", "Spawn", "", 0.0)],
    "trg_sp_clear": [("OnStartTouch", "sl_cmd", "Command", "npc_kill", 0.0)],
}


def emit():
    v = build()
    out = []
    for ent in v.entities:
        lines = ent.split("\n")
        name = None
        for ln in lines:
            if ln.strip().startswith('"targetname"'):
                name = ln.strip().split('"')[3]
                break
        conns = OUTPUTS.get(name or "", [])
        if conns:
            seen = set()
            extra = []
            for (o, t, inp, param, delay) in conns:
                assert o not in seen, (name, o)
                seen.add(o)
                extra.append('\t%s %s' % (q(o), q("%s,%s,%s,%s,-1" %
                                                     (t, inp, param, delay))))
            # outputs are plain keys: this vbsp only serialises them that way
            lines = lines[:-1] + extra + [lines[-1]]
        out.append("\n".join(lines))
    v.entities = out
    return v.build()


if __name__ == "__main__":
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        f.write(emit())
    print("wrote", OUT)
