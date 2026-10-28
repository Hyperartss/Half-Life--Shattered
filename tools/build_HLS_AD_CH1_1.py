#!/usr/bin/env python3
"""Generate maps/HLS_AD_CH1_1.vmf - Chapter 1, map 1: the G-Man stasis area.

Adrian's side story, first playable map.  Blockout only: box geometry,
dev textures, placeholder sound and text, no art pass.

Flow (all one map, no loading screens):

  A  OSPREY CABIN   (0:00)  starts exactly where Opposing Force ends - Adrian
                            standing in the transport, G-Man in the aisle,
                            Black Mesa burning out the window.  Push forward,
                            the rift hits the aircraft, you are thrown out.
  B  STASIS VOID    (0:40)  torn floor plates of the Osprey hang in black
                            nothing, lit from nowhere.  Jump across floating
                            debris.  Falling sends you back.
  C  FROZEN HALL    (1:20)  a maze of people stopped mid-motion.  One figure
                            is lunging at you and will never arrive.  Three
                            stasis anchors (one per aisle) release the bridge
                            over the chasm.  Supply cache past it.
  D  PLAZA + RIFT   (3:00)  the Borealis is wedged through the far side of the
                            stasis space, prow-first into the tear.  Walk into
                            it, chapter ends.  Alternate worlds hang in the
                            distance the whole time.

Scale is real Source scale (player 72u, jump ~57u up / ~200u across), so
distances in here are already playable numbers, not sketches.

Usage:
    python3 tools/build_HLS_AD_CH1_1.py
Then compile from the mod root:
    wine "<HL2>/bin/vbsp.exe" -game . maps/HLS_AD_CH1_1.vmf
    wine "<HL2>/bin/vvis.exe" -game . maps/HLS_AD_CH1_1
    wine "<HL2>/bin/vrad.exe" -game . maps/HLS_AD_CH1_1

The VMF is a generated file - edit it in Hammer++ if you like, but re-running
this script overwrites it.  Change the numbers here instead when you want the
layout to survive a rebuild.
"""

import os
import random

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "maps", "HLS_AD_CH1_1.vmf")

# ---------------------------------------------------------------------------
# materials (all checked against the HL2 vpks shipped with this install)
# ---------------------------------------------------------------------------
VOID = "TOOLS/TOOLSBLACK"          # unlit black: the stasis void
NODRAW = "TOOLS/TOOLSNODRAW"
TRIGGER = "TOOLS/TOOLSTRIGGER"     # invisible in game, visible in Hammer
SKY = "TOOLS/TOOLSSKYBOX"
CONC = "CONCRETE/CONCRETEWALL006A"
FLOOR = "CONCRETE/CONCRETEFLOOR001A"
CEIL = "CONCRETE/CONCRETECEILING001A"
METAL = "METAL/METALWALL048A"
METAL2 = "METAL/METALWALL001A"
RUST = "METAL/METALWALL002A"
DEV = "DEV/DEV_MEASUREGENERIC01B"
DEVM = "DEV/DEV_MEASUREWALL01A"
HAZ = "DEV/DEV_HAZZARDSTRIPE01A"
LIGHT = "LIGHTS/FLUORESCENTWHITE001A"
WHITE = "LIGHTS/WHITE001"
GLASS = "GLASS/GLASSWINDOW007A"

# ---------------------------------------------------------------------------
# sounds (checked against hl2_sound_misc.vpk)
# ---------------------------------------------------------------------------
SND_CABIN = "ambient/atmosphere/cargo_hold1.wav"
SND_ENGINE = "ambient/machines/train_rumble.wav"
SND_STASIS = "ambient/levels/citadel/citadel_drone_loop1.wav"
SND_VOICES = "ambient/levels/citadel/citadel_ambient_voices1.wav"
SND_RIFT = "ambient/levels/labs/teleport_active_loop1.wav"
SND_RIFT_HIT = "ambient/levels/labs/teleport_preblast_suckin1.wav"
SND_TEAR = "ambient/explosions/explode_4.wav"
SND_HULL = "npc/strider/creak1.wav"
SND_BRIDGE = "ambient/levels/labs/teleport_mechanism_windup2.wav"
SND_STINGER = "ambient/wind/wind_hit1.wav"
SND_FALL = "ambient/materials/creaking.wav"

# ---------------------------------------------------------------------------
# models (checked against hl2_misc vpk; HL2 humans/combine are reused as the
# frozen stasis figures)
# ---------------------------------------------------------------------------
MDL_GMAN = "models/gman.mdl"
# group01 ships male_01..09 and female_01..04, 06, 07 (there is no female_05)
MDL_CREW = ["models/humans/group01/male_0%d.mdl" % i for i in range(1, 10)] + \
           ["models/humans/group01/female_0%d.mdl" % i
            for i in (1, 2, 3, 4, 6, 7)]
MDL_SOLDIER = "models/combine_soldier.mdl"
MDL_VORT = "models/vortigaunt_slave.mdl"
MDL_CHAIR = "models/props_interiors/furniture_chair01a.mdl"
MDL_CRATE1 = "models/props_junk/wood_crate001a.mdl"
MDL_CRATE2 = "models/props_junk/wood_crate002a.mdl"
MDL_CHUNK = ["models/props_debris/concrete_chunk%s.mdl" % s
             for s in ("01a", "01b", "01c", "02a", "05g", "07a")]
MDL_MONITOR = "models/props_lab/monitor01a.mdl"

# ---------------------------------------------------------------------------
# key heights
# ---------------------------------------------------------------------------
CABIN_Z = 0
VOID_Z = 256        # landing plate
HALL_Z = 320        # hall + plaza share a floor level
CHASM_Y1, CHASM_Y2 = 2448, 2704

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
    """Minimal VMF writer. Outputs are a list so one entity can fire the same
    output name several times (Hammer and the engine both allow that)."""

    def __init__(self):
        self.world_brushes = []
        self.entities = []
        self.world_kv = []

    # -- geometry ----------------------------------------------------------
    def world(self, mn, mx, mat=VOID, lightmap=64):
        self.world_brushes.append(box_solid(mn, mx, mat, lightmap))

    def detail(self, mn, mx, mat=CONC, lightmap=16):
        self.entity("func_detail", {}, [box_solid(mn, mx, mat, lightmap)])

    def brush(self, classname, kv, boxes, mat=CONC, lightmap=16, outputs=()):
        self.entity(classname, kv,
                    [box_solid(mn, mx, mat, lightmap) for mn, mx in boxes],
                    outputs)

    # -- entities ----------------------------------------------------------
    def entity(self, classname, kv, solids=None, outputs=()):
        kv = dict(kv)
        kv["classname"] = classname
        kv["id"] = str(uid())
        body = ["entity", "{"]
        order = ["classname", "targetname"]
        keys = [k for k in order if k in kv] + [k for k in kv if k not in order]
        for k in keys:
            body.append("\t%s %s" % (q(k), q(kv[k])))
        for name, value in outputs:
            body.append("\t%s %s" % (q(name), q(value)))
        for s in (solids or []):
            body.append(s)
        body.append("}")
        self.entities.append("\n".join(body))

    # -- output ------------------------------------------------------------
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
        for k, v in self.world_kv:
            head.append("\t%s %s" % (q(k), q(v)))
        head += self.world_brushes
        head.append("}")
        return "\n".join(head + self.entities) + "\n"


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def slab(v, x1, y1, x2, y2, top, thick, mat=FLOOR, light=16):
    """Horizontal plate with its walkable face at `top`."""
    v.detail((x1, y1, top - thick), (x2, y2, top), mat, light)


def wallx(v, x1, x2, y1, y2, z1, z2, mat=CONC, light=16):
    v.detail((x1, y1, z1), (x2, y2, z2), mat, light)


def light(v, x, y, z, bright=250, colour=(255, 244, 220), dist=700):
    r, g, b = colour
    v.entity("light", {
        "origin": "%d %d %d" % (x, y, z),
        "_light": "%d %d %d %d" % (r, g, b, bright),
        "_distance": "%d" % dist,
    })


def txt(v, name, message, channel=2, hold=5.0, colour=(255, 232, 150),
        x="0.5", y="0.78"):
    r, g, b = colour
    v.entity("game_text", {
        "targetname": name,
        "message": message,
        "x": x, "y": y,
        "channel": str(channel),
        "color": "%d %d %d" % (r, g, b),
        "color2": "%d %d %d" % (r, g, b),
        "effect": "0", "fxtime": "0",
        "fadein": "0.4", "fadeout": "0.6",
        "holdtime": str(hold),
        "spawnflags": "0",
    })


def snd(v, name, sound, volume=7, radius=1200, spawnflags=0, pitch=100):
    v.entity("ambient_generic", {
        "targetname": name,
        "message": sound,
        "health": str(volume),
        "radius": str(radius),
        "spawnflags": str(spawnflags),   # 0 = loop + play on spawn
        "pitch": str(pitch),
    })


def sprite(v, name, origin, colour=(140, 190, 255), scale=2, start_on=False):
    r, g, b = colour
    v.entity("env_sprite", {
        "targetname": name,
        "model": "sprites/blueglow1.vmt",
        "origin": origin,
        "scale": str(scale),
        "rendercolor": "%d %d %d" % (r, g, b),
        "rendermode": "5",      # additive
        "framerate": "0",
        "GlowProxySize": "6.0",
        "spawnflags": "1" if start_on else "0",
    })


def prop(v, model, origin, angles="0 0 0", cls="prop_static", **extra):
    kv = {"origin": origin, "angles": angles, "model": model}
    kv.update(extra)
    v.entity(cls, kv)


def statue(v, model, origin, angles="0 0 0"):
    """A person stopped mid-motion.  NPC models are not $staticprop-compiled,
    so this is a prop_dynamic held at playback rate 0 instead of a prop_static."""
    prop(v, model, origin, angles, cls="prop_dynamic",
         solid="2", playbackrate="0", RandomAnimation="0", DefaultAnim="")


def trig(v, name, mn, mx, kind="trigger_once", wait=6, outputs=(), flags=1):
    kv = {"targetname": name, "spawnflags": str(flags)}
    if kind == "trigger_multiple":
        kv["wait"] = str(wait)
    v.brush(kind, kv, [(mn, mx)], TRIGGER, outputs=outputs)


def trig1(v, name, mn, mx, action, kind="trigger_once"):
    """One volume, one action.

    The vbsp in this install keeps only the LAST value of a duplicated key, so
    an entity can have at most one connection per output name - a beat with N
    actions needs N trigger volumes (they overlap, offset a few units along the
    player's path).  This is the same constraint the arsenal test map works
    around.
    """
    trig(v, name, mn, mx, kind=kind, outputs=[("OnStartTouch", action)])


def beat(v, prefix, mn, mx, actions, kind="trigger_once"):
    """'actions' is a list of "target,input,param,delay" strings; one stacked
    trigger per action, each nudged 6 units further along Y."""
    x1, y1, z1 = mn
    x2, y2, z2 = mx
    for i, action in enumerate(actions):
        trig1(v, "%s_%d" % (prefix, i + 1),
              (x1, y1 + i, z1), (x2, y2 + i, z2), action, kind=kind)


def shake(v, name, amplitude=6, duration=2, radius=800, frequency=120):
    v.entity("env_shake", {
        "targetname": name,
        "amplitude": str(amplitude),
        "duration": str(duration),
        "radius": str(radius),
        "frequency": str(frequency),
        "spawnflags": "0",
    })


def fade(v, name, duration=1.2, hold=0.6, colour=(255, 255, 255), outputs=()):
    r, g, b = colour
    v.entity("env_fade", {
        "targetname": name,
        "duration": str(duration),
        "holdtime": str(hold),
        "rendercolor": "%d %d %d" % (r, g, b),
        "renderamt": "255",
        "spawnflags": "0",
    }, outputs=outputs)


def teleport_dest(v, name, origin, angles="0 90 0"):
    """point_teleport teleports its target to its own origin.  !player is the
    engine's name for the local player, so this works from any trigger."""
    v.entity("point_teleport", {
        "targetname": name,
        "target": "!player",
        "origin": origin,
        "angles": angles,
    })


# ---------------------------------------------------------------------------
# ZONE A - the Osprey cabin (Opposing Force ending, replay start)
# ---------------------------------------------------------------------------
CABIN = dict(x1=-128, x2=128, y1=-592, y2=-144, z1=0, z2=112)


def build_cabin(v):
    x1, x2, y1, y2, z1, z2 = (CABIN["x1"], CABIN["x2"], CABIN["y1"],
                              CABIN["y2"], CABIN["z1"], CABIN["z2"])
    slab(v, x1, y1, x2, y2, z1, 32, FLOOR)
    v.detail((x1, y1, z2), (x2, y2, z2 + 32), CEIL)

    # shell walls
    wallx(v, x1, x1 + 32, y1, y2, z1, z2)             # port side
    wallx(v, x1, x2, y1, y1 + 32, z1, z2, METAL2)     # aft bulkhead
    wallx(v, x1, x2, y2 - 32, y2, z1, z2, METAL2)     # fwd bulkhead

    # starboard wall, opened for the window at y -380..-240, z 48..96
    wallx(v, x2 - 32, x2, y1, -380, z1, z2)
    wallx(v, x2 - 32, x2, -240, y2, z1, z2)
    wallx(v, x2 - 32, x2, -380, -240, z1, 48)
    wallx(v, x2 - 32, x2, -380, -240, 96, z2)
    v.detail((x2 - 32, -380, 48), (x2 - 28, -240, 96), GLASS)
    # what is left of Black Mesa, burning, right outside the glass
    v.detail((x2, -380, 48), (x2 + 24, -240, 96), LIGHT)
    light(v, x2 + 60, -310, 72, 400, (255, 150, 80), 500)

    # jump seats: two banks, three benches a side
    for bx1, bx2, back_x1, back_x2 in ((x1 + 32, -48, x1 + 32, x1 + 40),
                                       (48, x2 - 32, x2 - 40, x2 - 32)):
        for by in (-552, -496, -440):
            v.detail((bx1, by, z1), (bx2, by + 48, z1 + 40), DEVM)
            v.detail((back_x1, by, z1 + 40), (back_x2, by + 48, z1 + 96), DEVM)
    # stowage bins over the window
    v.detail((x1 + 32, -560, 40), (x1 + 44, -400, 52), METAL)

    # fwd bulkhead hatch + cockpit slit light (the cockpit is not a way out)
    v.detail((-44, y2 - 36, z1), (44, y2 - 32, z1 + 80), METAL)
    v.detail((-44, y2 - 40, 60), (44, y2 - 36, 72), LIGHT)
    light(v, 0, y2 - 90, 80, 180, (200, 215, 235), 260)

    # cabin light strips and pools
    v.detail((-24, -560, 104), (24, -200, 112), LIGHT)
    light(v, 0, -520, 96, 180, (255, 236, 200), 340)
    light(v, 0, -400, 96, 170, (255, 232, 190), 320)
    light(v, 0, -260, 96, 150, (255, 226, 180), 300)

    # -- start, G-Man, intro beats
    v.entity("info_player_start", {"origin": "0 -500 0", "angles": "0 90 0"})
    v.entity("npc_gman", {"targetname": "gman", "origin": "0 -300 0",
                          "angles": "0 270 0"})

    snd(v, "snd_cabin", SND_CABIN, 7, 500)
    snd(v, "snd_engine", SND_ENGINE, 5, 700)
    shake(v, "shake_cabin", 5, 3.5, 600, 90)
    snd(v, "snd_tear", SND_TEAR, 10, 1400)
    snd(v, "snd_stasis", SND_STASIS, 7, 1800)
    snd(v, "snd_voices", SND_VOICES, 4, 1400)

    txt(v, "txt_gman_1", "G-MAN: Your service record is... remarkably "
                         "intact, Corporal.")
    txt(v, "txt_gman_2", "G-MAN: I'm afraid I have to revise our itinerary.")
    txt(v, "txt_stasis_1", "G-MAN: Do try not to touch anything. Some of it "
                           "is still deciding what it is.")

    fade(v, "fade_tear", 1.2, 0.7, (255, 255, 255),
         outputs=[("OnBeginFade", "tp_stasis,Teleport,,1.5")])
    teleport_dest(v, "tp_stasis", "0 96 256", "0 90 0")

    # spawn beat
    trig1(v, "trg_intro", (-96, -556, 0), (96, -470, 90),
          "txt_gman_1,Display,,0")
    # the aircraft loses the argument with the rift
    beat(v, "trg_tear", (-96, -352, 0), (96, -250, 96), [
        "snd_tear,PlaySound,,0",
        "shake_cabin,StartShake,,0.05",
        "txt_gman_2,Display,,0.5",
        "gman,Kill,,1.3",
        "fade_tear,Fade,,1.0",
    ])


# ---------------------------------------------------------------------------
# ZONE B - thrown into the stasis void, then debris hops
# ---------------------------------------------------------------------------
def build_void(v):
    # the piece of Osprey floor Adrian lands on
    slab(v, -208, -32, 208, 320, VOID_Z, 32, METAL)
    # torn railings and a few still-bolted seats: this was the same aircraft
    for rx in (-200, -60, 60, 200):
        v.detail((rx - 4, 312, VOID_Z), (rx + 4, 320, VOID_Z + 48), METAL2)
    v.detail((-200, 312, VOID_Z + 40), (200, 320, VOID_Z + 48), METAL2)
    v.detail((-208, 60, VOID_Z + 40), (-200, 320, VOID_Z + 48), METAL2)
    v.detail((200, 60, VOID_Z + 40), (208, 320, VOID_Z + 48), METAL2)
    prop(v, MDL_CHAIR, "-120 200 256", "0 200 0", cls="prop_physics")
    prop(v, MDL_CHAIR, "130 150 256", "0 340 0", cls="prop_physics")
    v.detail((-44, 250, VOID_Z), (-40, 254, VOID_Z + 260), METAL2)  # cable

    # hop 1..3 toward the hall
    slab(v, -112, 416, 112, 560, 288, 32, CONC)
    slab(v, -256, 624, -64, 752, 320, 32, CONC)
    slab(v, -96, 816, 160, 1000, 320, 32, CONC)   # meets the hall doorway

    # dead slabs hanging overhead / far out: depth cues in a black space
    for (bx1, by1, bx2, by2, bz) in ((-760, 120, -420, 380, 660),
                                     (430, -180, 760, 90, 780),
                                     (-320, 520, -120, 700, 900),
                                     (200, 640, 420, 820, 620)):
        slab(v, bx1, by1, bx2, by2, bz, 32, CONC)
        slab(v, bx1 + 20, by1 + 20, bx2 - 20, by2 - 20, bz + 2, 4, DEV)

    # rubble on the plates
    rnd = random.Random(7)
    for (px, py, pz) in ((-150, 40, VOID_Z), (150, 280, VOID_Z),
                         (60, 470, 288), (-180, 700, 320), (100, 900, 320)):
        prop(v, rnd.choice(MDL_CHUNK), "%d %d %d" % (px, py, pz),
             "0 %d 0" % rnd.randrange(0, 360), cls="prop_physics")

    light(v, 0, 140, 520, 230, (176, 204, 255), 700)
    light(v, -520, 260, 420, 120, (120, 150, 255), 900)
    light(v, 520, 700, 560, 120, (255, 150, 90), 900)
    light(v, 0, 860, 520, 200, (200, 220, 255), 600)

    snd(v, "snd_fall", SND_FALL, 6, 900)

    teleport_dest(v, "tp_void", "0 130 256", "0 90 0")
    txt(v, "txt_fall", "The stasis does not let go that easily.")
    # arriving in the void is what plays G-Man's next line
    trig1(v, "trg_land", (-208, -32, 256), (208, 320, 380),
          "txt_stasis_1,Display,,0.6")
    # falling out of the debris field drops you back on the landing plate
    trig1(v, "trg_void_fall_tp", (-900, -100, -700), (900, 1010, 140),
          "tp_void,Teleport,,0.05", kind="trigger_multiple")
    trig1(v, "trg_void_fall_txt", (-900, -100, -700), (900, 1010, 140),
          "txt_fall,Display,,0.25", kind="trigger_multiple")


# ---------------------------------------------------------------------------
# ZONE C - the hall of frozen moments
# ---------------------------------------------------------------------------
def build_hall(v):
    # floor, split by the chasm the puzzle later bridges
    slab(v, -768, 1000, 768, CHASM_Y1, HALL_Z, 32, FLOOR)
    slab(v, -96, CHASM_Y2, 96, 2760, HALL_Z, 32, FLOOR)
    # ledges either side of the chasm so the gap reads as a hole in a floor
    slab(v, -768, CHASM_Y1, -96, CHASM_Y1 + 40, HALL_Z, 32, CONC)
    slab(v, 96, CHASM_Y1, 768, CHASM_Y1 + 40, HALL_Z, 32, CONC)

    WALL_TOP = 904
    # outer walls, with the entry (south) and exit (north) doorways
    wallx(v, -768, -96, 1000, 1064, HALL_Z, WALL_TOP)
    wallx(v, 96, 768, 1000, 1064, HALL_Z, WALL_TOP)
    wallx(v, -768, -96, CHASM_Y2, 2768, HALL_Z, WALL_TOP)
    wallx(v, 96, 768, CHASM_Y2, 2768, HALL_Z, WALL_TOP)
    wallx(v, -96, 96, CHASM_Y2, 2768, 560, WALL_TOP)      # exit header
    wallx(v, -768, -704, 1000, 2768, HALL_Z, WALL_TOP)    # west
    wallx(v, 704, 768, 1000, 2768, HALL_Z, WALL_TOP)      # east

    # the maze proper: three rooms, two forced turns, one pillar wall
    wallx(v, -768, 256, 1560, 1656, HALL_Z, WALL_TOP)     # A
    wallx(v, 256, 352, 1656, 1900, HALL_Z, WALL_TOP)      # D (walked around)
    wallx(v, -256, 768, 2050, 2146, HALL_Z, WALL_TOP)     # C
    wallx(v, -768, -420, 1240, 1336, HALL_Z, WALL_TOP)    # E (dead-end bay)

    # ---- frozen figures --------------------------------------------------
    rnd = random.Random(11)
    frozen = []
    for i in range(5):                                    # queues along walls
        frozen.append((-676, 1100 + i * 90, 0))
        frozen.append((676, 1120 + i * 90, 0))
    frozen += [(-360, 1180, 0), (-300, 1240, 0), (-430, 1300, 0),
               (430, 1180, 0), (360, 1260, 0), (480, 1320, 0),
               (500, 1720, 0), (560, 1780, 0), (-100, 1750, 0),
               (-300, 1900, 0), (-520, 1980, 0), (200, 2000, 0),
               (-450, 2200, 0), (-250, 2280, 0), (150, 2220, 0),
               (400, 2300, 0), (600, 2380, 0), (-600, 2400, 0)]
    for (px, py, _) in frozen:
        statue(v, rnd.choice(MDL_CREW), "%d %d %d" % (px, py, HALL_Z),
               "0 %d 0" % rnd.randrange(0, 360))
    # the ones nobody explains
    statue(v, MDL_VORT, "-160 2300 320", "0 45 0")

    # fake danger: a soldier who has been lunging for a very long time
    v.detail((-768, 1380, 320), (-700, 1560, 720), DEVM)   # recess it stands in
    statue(v, MDL_SOLDIER, "-656 1440 320", "0 350 0")
    statue(v, MDL_CREW[3], "-712 1500 320", "0 100 0")     # cowering scientist
    light(v, -748, 1460, 430, 420, (255, 250, 240), 420)   # hard backlight
    shake(v, "shake_fake", 4, 1.6, 420, 140)
    snd(v, "snd_stinger", SND_STINGER, 8, 700)
    txt(v, "txt_fake", "...it hasn't moved. It has been about to move for a "
                       "very long time.")
    beat(v, "trg_fake", (-768, 1336, 320), (-420, 1560, 480), [
        "snd_stinger,PlaySound,,0",
        "shake_fake,StartShake,,0.1",
        "txt_fake,Display,,1.4",
    ])

    # ---- stasis anchors (the puzzle) -------------------------------------
    # Three plinths, one per aisle.  A button gets a single connection, so each
    # one feeds its own counter; that counter plays its own line and bumps the
    # shared total; the total releases the bridge.
    v.brush("func_button", {"targetname": "btn_anchor_1", "spawnflags": "1",
                            "wait": "-1", "sounds": "14"},
            [((-648, 1476, 332), (-632, 1524, 380))], HAZ,
            outputs=[("OnPressed", "ctr_a1,Add,1,0")])
    v.detail((-720, 1452, 320), (-632, 1548, 332), CONC)

    v.brush("func_button", {"targetname": "btn_anchor_2", "spawnflags": "1",
                            "wait": "-1", "sounds": "14"},
            [((584, 1766, 332), (600, 1814, 380))], HAZ,
            outputs=[("OnPressed", "ctr_a2,Add,1,0")])
    v.detail((600, 1744, 320), (688, 1836, 332), CONC)

    v.brush("func_button", {"targetname": "btn_anchor_3", "spawnflags": "1",
                            "wait": "-1", "sounds": "14"},
            [((-600, 2296, 332), (-584, 2344, 380))], HAZ,
            outputs=[("OnPressed", "ctr_a3,Add,1,0")])
    v.detail((-688, 2274, 320), (-600, 2366, 332), CONC)

    for i, (sx, sy) in enumerate(((-690, 1500), (652, 1790), (-652, 2320)), 1):
        sprite(v, "fx_anchor_%d" % i, "%d %d 410" % (sx, sy),
               (140, 200, 255), 2, start_on=True)
        light(v, sx - 30, sy, 400, 160, (150, 200, 255), 340)
        v.entity("math_counter", {"targetname": "ctr_a%d" % i,
                                  "startvalue": "0", "min": "0", "max": "1"},
                 outputs=[("OnHitMax", "txt_anchor_%d,Display,,0" % i),
                          ("OutValue", "ctr_total,Add,1,0")])

    txt(v, "txt_anchor_1", "Stasis anchor released. (1 of 3)")
    txt(v, "txt_anchor_2", "Stasis anchor released. (2 of 3)")
    txt(v, "txt_anchor_3", "Stasis anchor released. (3 of 3)")

    v.entity("math_counter", {"targetname": "ctr_total", "startvalue": "0",
                              "min": "0", "max": "3"},
             outputs=[("OutValue", "snd_bridge,PlaySound,,0"),
                      ("OnHitMax", "br_bridge,Enable,,0")])
    snd(v, "snd_bridge", SND_BRIDGE, 8, 900, spawnflags=48)

    # the bridge itself: three plates released out of stasis, in one entity
    v.brush("func_brush", {"targetname": "br_bridge", "StartDisabled": "1",
                           "Solidity": "0", "spawnflags": "0"},
            [((-96, 2448, 296), (96, 2536, 320)),
             ((-96, 2536, 296), (96, 2624, 320)),
             ((-96, 2624, 296), (96, 2704, 320))], METAL)

    # ---- supply cache (lambda crates + the one thing you actually need) ---
    v.detail((-224, 2900, 320), (-16, 2940, 470), CONC)
    v.detail((-208, 2894, 330), (-32, 2900, 354), HAZ)
    v.detail((-208, 2900, 430), (-32, 2904, 462), LIGHT)
    prop(v, MDL_CRATE2, "-140 2850 320", "0 20 0", cls="prop_physics")
    prop(v, MDL_CRATE1, "-60 2870 320", "0 200 0", cls="prop_physics")
    v.entity("item_healthkit", {"origin": "-190 2830 324", "angles": "0 0 0"})
    v.entity("item_battery", {"origin": "-100 2830 324", "angles": "0 0 0"})
    light(v, -120, 2900, 430, 240, (255, 236, 190), 420)

    # ---- hall lighting: light marks the true route, dark means dead end --
    for (lx, ly, br, di) in ((0, 1200, 260, 900), (500, 1600, 240, 700),
                             (520, 1860, 240, 700), (-60, 1960, 240, 800),
                             (-520, 2100, 240, 700), (-300, 2260, 240, 800),
                             (300, 2380, 200, 700), (0, 2570, 220, 700)):
        light(v, lx, ly, 760, br, (255, 232, 186), di)
    light(v, -560, 1150, 700, 90, (150, 170, 210), 500)   # dead-end gloom

    txt(v, "txt_hall", "Nobody here is breathing. Nobody here is gone, "
                       "either.")
    trig1(v, "trg_hall", (-96, 1000, 320), (96, 1080, 460),
          "txt_hall,Display,,0.4")

    # the chasm keeps what it catches
    teleport_dest(v, "tp_hall", "0 1100 320", "0 90 0")
    txt(v, "txt_fall_hall", "The void puts you back. It is not being kind.")
    trig1(v, "trg_hall_fall_tp", (-900, 2380, -700), (900, 2760, 140),
          "tp_hall,Teleport,,0.05", kind="trigger_multiple")
    trig1(v, "trg_hall_fall_txt", (-900, 2380, -700), (900, 2760, 140),
          "txt_fall_hall,Display,,0.25", kind="trigger_multiple")


# ---------------------------------------------------------------------------
# ZONE D - the plaza, the Borealis, and the tear
# ---------------------------------------------------------------------------
def build_plaza(v):
    # runs north past the pier the hull punches through, up to the tear itself
    slab(v, -1024, 2760, 1024, 4740, HALL_Z, 32, FLOOR)
    # a piece of Black Mesa came along for the ride
    v.detail((-256, 3300, 320), (256, 3600, 352), CONC)
    v.detail((-256, 3300, 352), (-192, 3600, 560), CONC)
    v.detail((192, 3300, 352), (256, 3600, 500), CONC)
    v.detail((-160, 3400, 320), (160, 3520, 384), DEVM)
    for rx in (-120, -40, 60, 140):
        v.detail((rx, 3450, 384), (rx + 6, 3456, 470), METAL2)   # rebar
    prop(v, MDL_MONITOR, "-70 3480 384", "0 130 0", cls="prop_dynamic",
         solid="2")

    # ---- the Borealis, prow-first through the far side of the room ------
    v.detail((200, 3350, 320), (1600, 4050, 1500), RUST)
    v.detail((180, 3400, 320), (1600, 4000, 1200), METAL)
    prows = ((300, 4050, 1500, 4170, 1350),
             (420, 4170, 1380, 4290, 1200),
             (540, 4290, 1260, 4410, 1050),
             (660, 4410, 1140, 4530, 900),
             (780, 4530, 1020, 4650, 780),
             (860, 4650, 940, 4770, 660))
    for (x1, y1, x2, y2, z2) in prows:
        v.detail((x1, y1, 320), (x2, y2, z2), RUST)
        v.detail((x1 + 12, y1 + 12, 320), (x2 - 12, y2 - 12, z2 - 40), METAL)
    # ice and frozen spray stuck to the hull
    for (ix, iy, iz, sx, sy, sz) in ((260, 3900, 320, 380, 3960, 380),
                                     (700, 4350, 320, 760, 4400, 400),
                                     (900, 3000, 320, 980, 3060, 356),
                                     (-260, 3820, 320, -180, 3880, 380)):
        v.detail((ix, iy, iz), (sx, sy, sz), GLASS)
    light(v, 900, 3700, 1200, 220, (255, 176, 120), 1400)
    snd(v, "snd_hull", SND_HULL, 7, 1600, spawnflags=48)

    # ---- the tear: a vertical slot of nothing-bright --------------------
    v.detail((-800, 4560, 1600), (320, 4624, 1700), METAL2)
    v.brush("func_brush", {"targetname": "rift", "Solidity": "1",
                           "spawnflags": "0"},
            [((-800, 4576, 320), (320, 4608, 1600))], WHITE)
    for gx in (-620, -300, 20):
        sprite(v, "fx_rift_%d" % (gx + 1000), "%d 4592 900" % gx,
               (190, 215, 255), 5, start_on=True)
    light(v, -240, 4520, 700, 400, (190, 215, 255), 1200)
    light(v, -240, 4570, 1250, 300, (220, 235, 255), 900)
    snd(v, "snd_rift", SND_RIFT, 8, 2000)
    shake(v, "shake_rift", 3, 8, 1200, 60)

    # ---- alternate worlds hanging out in the dark -----------------------
    worlds = ((-2600, -1600, SKY, (255, 140, 60)),
              (-300, 700, DEV, (120, 175, 255)),
              (1600, 2600, CONC, (140, 255, 150)))
    for i, (wx1, wx2, mat, col) in enumerate(worlds, 1):
        v.detail((wx1, 6600, 400), (wx2, 6640, 1700), mat)
        v.detail((wx1 - 60, 6580, 340), (wx2 + 60, 6660, 400), METAL2)
        v.detail((wx1 - 60, 6580, 1700), (wx2 + 60, 6660, 1760), METAL2)
        v.detail((wx1 - 60, 6580, 400), (wx1, 6660, 1700), METAL2)
        v.detail((wx2, 6580, 400), (wx2 + 60, 6660, 1700), METAL2)
        light(v, (wx1 + wx2) // 2, 6400, 900, 320, col, 2600)

    # ---- beats ----------------------------------------------------------
    txt(v, "txt_cache", "G-MAN: I took the liberty of leaving you a few "
                        "things. Do be careful with them.")
    txt(v, "txt_plaza", "G-MAN: Ah. There is the appointment I was worried "
                        "about.")
    txt(v, "txt_end", "G-MAN: Whatever you see out there, Corporal - do not "
                      "wave.")
    txt(v, "txt_chapter", "CHAPTER 1 - A SCHEDULE, REVISED")

    trig1(v, "trg_cache", (-260, 2790, 320), (40, 2960, 460),
          "txt_cache,Display,,0.4")
    beat(v, "trg_plaza", (-500, 2960, 320), (500, 3140, 480), [
        "txt_plaza,Display,,0.2",
        "shake_rift,StartShake,,0.4",
        "snd_rift_hit,PlaySound,,0.4",
        "snd_hull,PlaySound,,2.0",
    ])
    snd(v, "snd_rift_hit", SND_RIFT_HIT, 9, 1500, spawnflags=48)

    fade(v, "fade_end", 2.0, 3.0, (255, 255, 255),
         outputs=[("OnBeginFade", "txt_chapter,Display,,3.2")])
    # point_servercommand is here so a later map can be hooked up: give it
    #   ("OnStartTouch", "srv_end,Command,changelevel hls_ad_ch1_2,2.6")
    # on one of the trg_end volumes once that map exists.
    v.entity("point_servercommand", {"targetname": "srv_end"})
    beat(v, "trg_end", (-800, 4480, 320), (320, 4650, 640), [
        "fade_end,Fade,,0",
        "txt_end,Display,,0.3",
        "snd_rift,StopSound,,1.0",
        "shake_rift,StopShake,,0",
    ])

    # falling off the plaza
    teleport_dest(v, "tp_plaza", "0 2830 320", "0 90 0")
    txt(v, "txt_fall_plaza", "Not that way. Not yet.")
    trig1(v, "trg_plaza_fall_tp", (-1600, 2620, -700), (1800, 4900, 140),
          "tp_plaza,Teleport,,0.05", kind="trigger_multiple")
    trig1(v, "trg_plaza_fall_txt", (-1600, 2620, -700), (1800, 4900, 140),
          "txt_fall_plaza,Display,,0.25", kind="trigger_multiple")

    # last-resort catcher under the whole map
    trig1(v, "trg_sump", (-3500, -1500, -760), (3500, 6700, -400),
          "tp_plaza,Teleport,,0.05", kind="trigger_multiple")

    v.entity("env_cubemap", {"origin": "0 3200 500", "cubemapsize": "0"})
    v.entity("env_cubemap", {"origin": "0 1800 400", "cubemapsize": "0"})


# ---------------------------------------------------------------------------
# sealed outer shell: everything inside is func_detail, so the map has a
# single vis leaf and can never leak
# ---------------------------------------------------------------------------
SHELL = dict(x1=-4000, x2=4000, y1=-2000, y2=7200, z1=-800, z2=2400, t=400)


def build_shell(v):
    s = SHELL
    x1, x2, y1, y2 = s["x1"], s["x2"], s["y1"], s["y2"]
    z1, z2, t = s["z1"], s["z2"], s["t"]
    v.world((x1, y1, z1 - t), (x2, y2, z1))      # floor
    v.world((x1, y1, z2), (x2, y2, z2 + t))      # ceiling
    v.world((x1, y1, z1), (x2, y1 + t, z2))      # south
    v.world((x1, y2 - t, z1), (x2, y2, z2))      # north
    v.world((x1, y1, z1), (x1 + t, y2, z2))      # west
    v.world((x2 - t, y1, z1), (x2, y2, z2))      # east


# ---------------------------------------------------------------------------
def build():
    v = Vmf()
    v.world_kv = [
        ("skyname", "sky_borealis01"),
        ("maxpropscreenwidth", "-1"),
        ("detailvbsp", "detail.vbsp"),
        ("detailmaterial", "detail/detailsprites"),
    ]
    build_shell(v)
    build_cabin(v)
    build_void(v)
    build_hall(v)
    build_plaza(v)
    return v


def emit():
    return build().build()


if __name__ == "__main__":
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        f.write(emit())
    print("wrote", OUT)
