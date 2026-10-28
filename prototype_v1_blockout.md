# prototype v1 — the G-Man stasis area (blockout)

The map file is `maps/prototype_v1.vmf`: Source map names cannot contain
spaces, so "prototype v1" is spelled `prototype_v1` on disk.

Generated blockout, not an art pass. Everything is boxes on dev/concrete/metal
textures with real, playable distances. Change the numbers in
`tools/build_prototype_v1.py` and re-run it when you want a layout change to
survive; editing the VMF directly in Hammer++ is fine too, but the next run of
the script overwrites it.

Built already: `maps/prototype_v1.bsp` (vbsp/vvis/vrad all clean, no leaks).
Load it with `map prototype_v1`.

## The four beats

```
            N  (+Y)  the tear
            ^    [rift y4576]  <- walk in, chapter card, map ends
            |    alternate worlds hanging at y6600
            |    Borealis prow  y4050..4770
        PLAZA    x -1024..1024, y 2760..4740, floor z320
            |    supply cache + crates on the way in
        [bridge over chasm y2448..2704]  <- 3 stasis anchors release it
        FROZEN HALL  x -768..768, y 1000..2768
            |    maze: 3 rooms, 2 forced turns, dead-end bay = fake danger
            |    landing plate z256 -> 3 debris hops
            |    THROWN OUT HERE (white fade + teleport)
        OSPREY CABIN  x -128..128, y -592..-144, floor z0
S  (spawn at 0,-500,0, facing +Y)
```

**0:00 — the Osprey cabin.** Picks up exactly where Opposing Force ends: Adrian
standing in the transport, seats either side, Black Mesa burning through the
starboard window, G-Man in the aisle. Walking forward plays his first line, then
the rift hits: screen shake, explosion, G-Man is gone, white-out, and you are
teleported into the void.

**0:40 — the stasis void.** A torn plate of the same Osprey floor, with its
seats still bolted on, hanging in black. Three debris hops lead to the hall.
Falling does not kill you — it puts you back on the plate ("the stasis does not
let go that easily"). Distant slabs hang overhead for depth.

**1:20 — the hall of frozen moments.** A maze of people stopped mid-motion:
queues along the walls, clusters mid-aisle, a Vortigaunt that is not explained.
The bay off the west side is the fake-danger beat (Episode One style): a Combine
soldier lit from behind, lunging, wind hit, screen shake — and then nothing, ever.
The 3 stasis anchors (one per aisle; the bay one is behind the soldier) release
the bridge over the chasm, and a supply cache sits past it: two lambda crates,
health, battery.

**2:40 — plaza and rift.** A chunk of Black Mesa came along for the ride. The
Borealis is wedged through the far side, prow-first into the tear, ice still on
the hull. Walk into the rift and the map ends on a white fade and the chapter
card. Three alternate worlds hang in the dark behind it.

## The one rule this toolchain has

The vbsp in this install keeps only the **last** value of a duplicated key, so
an entity can hold exactly **one connection per output name**. Verified by
compiling a two-output test entity: only the second connection survived. That is
why:

- every scripted action gets its own trigger volume (`trg_tear_1..5`,
  `trg_fake_1..3`, `trg_plaza_1..4`, `trg_end_1..4`), stacked a few units apart
  along the player's path with per-action delays doing the timing;
- the anchors use a button -> own counter -> shared counter chain, since a
  counter can fire both `OnHitMax` and `OutValue`;
- the bridge is one `func_brush` holding three solids, so one `Enable` releases
  all three plates;
- follow-on steps ride free outputs where they exist (`env_fade` `OnBeginFade`
  drives the teleport and the chapter card).

If you rewrite any of this in Hammer with two outputs on one entity, the second
one will silently disappear on compile. Split it across two entities instead.

## Entities worth knowing

| Name | What it does |
|---|---|
| `info_player_start` | (0, -500, 0), facing +Y |
| `gman` | `npc_gman` in the cabin; `Kill`ed on the tear (`trg_tear_4`) |
| `fade_tear` | white out; `OnBeginFade` + 1.5s -> `tp_stasis.Teleport` |
| `tp_stasis`, `tp_void`, `tp_hall`, `tp_plaza` | `point_teleport`, target `!player` |
| `trg_void_fall_tp` / `_txt`, `trg_hall_fall_*`, `trg_plaza_fall_*`, `trg_sump` | fall catchers, top z140 |
| `btn_anchor_1..3` -> `ctr_a1..3` -> `ctr_total` -> `br_bridge` | the puzzle |
| `trg_end_1..4` + `fade_end` | ending; `srv_end` is a `point_servercommand` waiting for a `changelevel` to the next map |

G-Man's lines are `game_text` (channel 2), not VO. The cabin loop, stasis drone,
rift loop and hull creak are real HL2 sounds picked from the install, so they
will play.

## Placeholders to replace

- **Frozen figures** are `prop_dynamic` with `playbackrate 0` (NPC models are not
  `$staticprop`-compiled, so `prop_static` refuses them). If they still breathe,
  drive `SetPlaybackRate 0` from a logic entity, or swap to posed ragdolls.
- **G-Man** is a bare `npc_gman`. If he T-poses, swap to `prop_dynamic` on
  `models/gman.mdl` and pose him with a `scripted_sequence`.
- **Alternate worlds** are three lit panels (one is a `toolsskybox` showing
  `sky_borealis01`). Swap for real 3D-skybox / portal-window geometry.
- **The Borealis** is stepped boxes. The stepped prow is deliberate: it reads as
  a hull at blockout scale and gives you a silhouette to carve.
- No cubemap build, no detail sprites pass, no ambient occlusion.

## Rebuild

```bash
python3 tools/build_prototype_v1.py
B="<...>/common/Half-Life 2/bin"
wine "$B/vbsp.exe" -game . maps/prototype_v1.vmf
wine "$B/vvis.exe" -game . maps/prototype_v1
wine "$B/vrad.exe" -game . maps/prototype_v1
```

Open `maps/prototype_v1.vmf` in Hammer++; it is plain format-100 VMF. The outer
shell is world brushes (nodraw-black, lightmap 64) and everything playable is
`func_detail`, so the map is a single vis leaf — fast compiles, no leaks, no vis
tuning to worry about while blocking out.
