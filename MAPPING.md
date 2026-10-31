# Mapping: HLShattered on SDK 2013 Hammer++ (Linux)

Written 2026-10-28. Everything here was measured on this machine.

## Where the maps are

```
~/.steam/steam/steamapps/sourcemods/HLShattered/maps/     <- your .vmf and .bsp live here
```

That is the folder to open, and it is now in Hammer's file-dialog **Favorites**
as `HLShattered maps` (plus `SourceMods`, `HLShattered`, `HLShattered materials`).

The reason it was hard to find: the Linux Hammer Launcher only knows HL2, EP1,
EP2 and SourceTest, and those configs point `MapDir` at the SDK's own
`sourcesdk_content/*/mapsrc` folders, which are **empty**. Hammer therefore
opened its file dialog somewhere with no maps in it.

## Opening Hammer

```bash
cd ~/.steam/steam/steamapps/sourcemods/HLShattered
tools/hammer.sh                  # Hammer++ with the mod active
tools/hammer.sh maps/sl_dev_room.vmf
```

The script:
* makes sure a `HLShattered` entry exists in
  `binwin/hammerplusplus/hammerplusplus_gameconfig.txt` (the launcher GUI can
  rewrite that file and does not know about the mod),
* marks it the active config (that is what the `"Previous" "1"` flag does), so
  Hammer comes up on the mod instead of HL2/EP2,
* starts Hammer++ in the Wine prefix the launcher created
  (`~/.config/linuxhammerlauncher/prefix`, the one with DXVK + d3dx9).

The config is:

| Key | Value |
|---|---|
| GameDir | `...\sourcemods\HLShattered` |
| GameExeDir | `...\Source SDK Base 2013 Singleplayer` |
| MapDir / BSPDir | `...\sourcemods\HLShattered\maps` |
| FGD | `binwin\portal.fgd` (includes `halflife2.fgd` -> `base.fgd`, adds `prop_portal`, `prop_energy_ball`, ...) |
| BSP / Vis / Light / MDL | `binwin\vbsp.exe`, `vvis.exe`, `vrad.exe`, `studiomdl.exe` |

**Use `debian-installation` in paths, never `.steam/steam`.** The Source tools
(vbsp in particular) fail with "Unable to find gameinfo.txt" when the game dir
is reached through the `.steam/steam` symlink. The real path works; that is why
every path in the config is spelled out.

## Compiling

In Hammer: F9, "Run Map". Out of Hammer:

```bash
tools/run_map.sh maps/my_map.vmf          # vbsp + vvis + vrad, then launch the map
tools/run_map.sh maps/my_map -nolan       # compile only
```

Both paths were verified on `maps/sl_dev_room.vmf`: vbsp, vvis and vrad all
complete and write `maps/sl_dev_room.bsp`, no leaks.

## Playing what you built

Hammer's own "Run Map" cannot start the game here: Hammer runs in its own Wine
prefix, while HLShattered runs under Steam/Proton (`sl_crash.txt` shows
`z:\...\bin\client.dll`). `binwin/hls_rungame.bat` bridges that — it takes the
`-game`/`+map` arguments Hammer passes and hands them to the native Steam
client (`start /unix steam -applaunch 243730 ...`). Argument forwarding was
tested; the final Steam hand-off has not been, because the game has to be
closed for it to be meaningful.

The always-works alternative: launch the mod in Steam, then `map my_map` in the
console. `tools/run_map.sh` without `-nolan` does the same thing for you.

## The two errors you were seeing

**"playerstart is not found"** — the map has no `info_player_start`. All three
existing maps have one, so this comes from a *new* map: Hammer's File > New
gives you an empty world with no entities. Start from `maps/sl_dev_room.vmf`
instead (or copy its `info_player_start`): a sealed 1024x1024x384 dev-textured
room with a player start, two lights, an `env_cubemap` and two props for scale.
Regenerate it with `python3 tools/build_sl_dev_room.py`.

**"can't load models/error.mdl"** — `error.mdl` is the engine's fallback model,
shown when a map references a model path that does not exist. The message means
the *fallback* was missing too: HLShattered had no `models/error.mdl` of its own
and does not always resolve it out of the mounted hl2 VPKs. It is now extracted
into the mod (`models/error.mdl`, `.vvd`, `.dx80/.dx90/.sw.vtx` from
`hl2_misc_dir.vpk`), so a bad model path now shows the error model in place
instead of that message.

If it still appears, the model path in the entity is genuinely wrong — check it
against the `.mdl` on disk, not against what the model browser lists.

## Known blocker: Hammer++ cannot render its viewports under Wine 9.0

Not a config problem, and not a mod problem. Hammer++ 8873 starts, loads the
mod's map (its title bar shows
`Z:\...\HLShattered\maps\sl_dev_room.vmf`), but its panels/viewports come up
blank. The cause is always the same line in DXVK's log:

```
err:  Presenter: Failed to create surface: VK_ERROR_INCOMPATIBLE_DRIVER
```

DXVK cannot create the Vulkan (X11) surfaces Hammer's multiple viewport
swapchains need. This Wine is Ubuntu's `wine 9.0` (wine32 + wine64, Mesa 25.2,
RADV on a 5700 XT). Measured, per DXVK build, launching on `sl_dev_room.vmf`:

| DXVK | Result |
|---|---|
| 2.3 (launcher default) | first swapchain OK, surface *re*creation fails, GDI fallback, then `STATUS_BREAKPOINT` minidump and exit |
| 2.7.1 | surface creation fails outright -> `terminate called after throwing an instance of 'dxvk::DxvkError'` |
| 2.2 | process stays up, no window is ever created (0 swapchains) |
| **1.10.3 (installed)** | window, menus and the map load; 11 swapchains created, **31 failed surfaces** -> empty panels |

Also ruled out along the way: removing `discord_game_sdk.dll`, removing CEF
(`libcef.dll`/`chromehtml.dll`), using `halflife2.fgd` instead of `portal.fgd`,
the EP2 config instead of the mod's, Proton 8.0 instead of system Wine
(exits before D3D init), and Wine's own wined3d (`DllOverrides=d3d9=builtin`;
the 32-bit builtin exists but exits immediately). Vanilla `hammer.exe` stays
up — it only ever drew its game-config dialog, which is plain VGUI.

So the mod, the FGD, the config and the paths are all fine; what fails is
32-bit D3D9 swapchain surface creation in this Wine. The fix has to be a
newer Wine (Wine 10, Wine-GE or Proton-GE — anything with a winevulkan that
can make these surfaces on Mesa 25), which is a separate download/install.
Until then the compiler and map files work from the command line, which is
what `tools/run_map.sh` does.

DXVK state right now: **1.10.3** in
`~/.config/linuxhammerlauncher/prefix/drive_c/windows/{system32,syswow64}`,
with the DLLs the launcher shipped backed up in `/tmp/dxvk_backup_163657`
(temporary — `winetricks dxvk` re-installs the launcher's own build).

## Notes for the next map

* The vbsp in this install keeps only the **last** value of a duplicated key, so
  an entity can hold one connection per output name — split across entities
  instead of stacking two outputs. (Already bit the prototype; see
  `prototype_v1_blockout.md`.)
* `maps/prototype_v1.vmf` and `maps/sl_arsenal_test.vmf` are generated by
  `tools/build_prototype_v1.py` / `tools/build_sl_arsenal_test.py`. Editing them
  in Hammer is fine, but re-running the script overwrites the edits.
* `tools/build_sl_dev_room.py` writes `maps/sl_dev_room.vmf` the same way.

## When a map "freezes on load" with no error

Measured 2026-10-29 on `maps/hls_stasis_blockout_v3.vmf`. The compile was clean
(vbsp, vvis and vrad all finished, no leak, no limit warnings) and the map had no
entity errors, but the loading window never went away. It was not a hang: the map
killed `hl2.exe` during server entity spawn, and the window is the ghost of the
defunct process. `console.log` stops at `Set Gravity 600.0` and nothing is
written afterwards, so there is no engine error to read.

The fault is a **stack overflow** (`EXCEPTION_STACK_OVERFLOW`, 0xC00000FD) from
infinite recursion in one brush entity. It is invisible in the engine log and the
mod's own crash handler cannot report it (it has no stack left to run on).
To see it, run the map under Proton with Wine's exception tracing on:

```bash
WINEDEBUG=+seh ~/.steam/debian-installation/steamapps/common/"Proton 9.0 (Beta)"/proton run \
  'Z:\…\Source SDK Base 2013 Singleplayer\hl2.exe' -steam \
  -game 'Z:\…\sourcemods\HLShattered' +map my_map -dev -condebug -windowed -novid \
  | grep c00000fd
```

Bisecting found the culprit: **one `func_illusionary` brush** (VMF id `2639`, a
`EFFECTS/COMBINESHIELD/COMSHIELDWALL` slab at `-4939..-4665 × -1150..-1132 ×
-374..-301`). The class is fine (one instance alone loads) and so is the brush
shape (moving that same brush elsewhere loads), and its BSP model looks normal
(214 models, 6 valid faces, sane areas) — so this is an engine-side defect in
this build, not something vbsp flags.

`maps/hls_stasis_blockout_v3_fixed.vmf` keeps the shard, rebuilt as **five
grid-aligned boxes** instead of one slanted brush: 64×24×32 (the last 24×24×24),
snapped to an 8-unit grid and stepped to follow the original ~12° slope, in the
same `Rifts` visgroup and `COMSHIELDWALL` material. It is one `func_illusionary`
with five solids, which compiles to model 213 / 29 faces and loads. A rebuilt
brush has to keep the same plane orientation as the rest of the map or vbsp
drops it ("bmodel N has no head node"): in this VMF the interior of a brush is
where `(p1-p0)×(p2-p0)·x >= d`, so a box wound the other way compiles to nothing.

Don't re-add the original slanted brush as-is. If a future export misbehaves the
same way, bisect it the same way: it only takes `vbsp.exe` per test (a vbsp-only
BSP still spawns server-side), so each probe is seconds, and the pass condition is
`Game started` in `console.log`.

## "The skybox doesn't hide anything" (measured 2026-10-29)

Short version: the sky brushes are not see-through, and the fix is fog plus (if
wanted) a backing behind each rift, not more sky.

What the BSP actually says about `hls_stasis_blockout_v3_fixed`:

* 90 `TOOLS/TOOLSSKYBOX` solids, **all `worldspawn`** (so they all seal), 215 sky
  faces. Every sky face has its normal pointing into open space with a solid
  brush behind it, so none is inside-out (`leaf contents` check on both sides of
  each face).
* Chasing 867 rays that hit a sky face and continuing past it: 486 hit nothing,
  365 hit `TOOLS/TOOLSBLACK`, 16 hit another sky panel. There is no room behind a
  sky wall, so nothing can "show through" it.
* There is **no `sky_camera`**, i.e. no 3D skybox, and no prop fade distances
  (`fademindist`/`fademaxdist` are absent), so the 2D skin is all that draws.

What the rifts open onto, from the frame centres:

| frame | one side | the other side |
|---|---|---|
| `rift_edge_0` @4160 | 2486 `DEV/GRAYGRID` | 3658 `COMSHIELDWALL` |
| `rift_edge_4160` @0 | 7878 `DEV/GRAYGRID` | 218 `COMSHIELDWALL` |
| `rift_edge_8320` @-4160 | 3718 `DEV/GRAYGRID` | 4038 `COMSHIELDWALL` |
| `universe_01..08_edge` | 3142 / 1659 / 3078 / 6 / 3142 / 3206 / 191 / 70 | 582 `TOOLSSKYBOX` |

So the tears are holes between the halls: you see 2.5k–7.9k units down the level
through them, and the sky alcove behind each `universe_*` tear is 582–646 deep.
That is the "I can see inside the rift": nothing is wrong with the sky, the
aperture is a window onto the rest of the map.

Fog was doing nothing — `fogstart 768 / fogend 6000` leaves everything inside
6,000 units crisp, and sightlines from standing positions run to 7,144 (measured
over 418 spots at eye height, 84 above the floor: 1,386 under 400u, 1,605 at
400–1200, 1,169 at 1200–2500, 856 past 2500, none escaping into the void).
`fog_main` (`env_fog_controller`, id 127) is now `fogstart 1200 / fogend 3200`:
nothing under 1,200 units is touched, so the near field stays crisp, and every
view of 3,200+ units is fog colour — 100% of the measured long sights, including
the 7,878 through the middle tear. The 2,486 one comes out 64% fogged. Tune those
two numbers to taste; nothing else changed.

One real trap for new geometry: 32 of the sky/black panels are **single-sided**
(one sky or black face, five `TOOLS/TOOLSNODRAW`). Nodraw faces are not written
to the BSP at all, so such a panel is invisible from five of six sides. These
particular ones happen to have their backs buried in neighbouring black brushes,
so vbsp culls the faces and nothing shows — but a new sky panel standing in open
space must be textured on every side, or you can walk round it and see through.

### The rifts themselves

Each of the three eastern tears (`rift_edge_0/4160/8320` at x 4160, 0, -4160) has a
`func_illusionary` membrane (`rift_membrane_*`, one 256×256 `COMSHIELDWALL`
solid). They were `rendermode 5` (additive) at `renderamt 70`, i.e. about a
quarter-brightness additive sheet — you looked straight through them into the
hall 2.5k–7.9k units away, which is why the tear read as a window onto the level.
They are now `rendermode 1` (color), `renderamt 235`, `rendercolor 190 205 230`:
an almost-opaque pale veil you still walk through, because `func_illusionary` has
no collision. To go back to the glowy see-through look, return those three keys
to `5 / 70 / 255 255 255`.

What remains after that is *near* popping, which is ordinary vis: the aperture is
the leaf boundary, so everything past it enters and leaves the PVS as you cross.
Fog can't hide that (it is inside 2,000 units). The two ways out are a `func_areaportal`
in each tear throat, or making the throat narrower so the visible cone through it
stays inside one cluster.

## The leak that made every "no leak" check a lie (2026-10-29)

`hls_stasis_blockout_v3_fixed` had been **leaking** for several builds. A leaking
map makes vbsp stop before `BuildVisLeafs`, so it writes no `.prt`. vvis then
does not fail loudly: it reads whatever `.prt` is already on disk, which was from
an older geometry, and reports success:

```
LoadPortals: couldn't read ...v3_fixed.prt        <- only sign something is wrong
```

A silent success looks exactly like this in the log — 373 clusters, `visdatasize
32887`, every time, byte for byte, no matter what you changed. If the numbers
never move, vis is stale. The give-away is in vbsp's own output: a clean run
prints `writing ...prt...Building visibility clusters...`; a leaked run prints
`**** leaked ****` and no `.prt` line at all.

The leaked entity was a `func_illusionary` shard at `(-4804 -1140 -336)`, i.e. one
of the rift shards sitting in the wall band. A `func_illusionary` does not seal,
so a shard that straddles the wall tunnels the void straight into the map. The
shipped VMF had picked this up somewhere; rebuilding it from
`maps/hls_stasis_blockout_v3.vmf` with only the four intended edits (rebuilt
shard, membrane veil, fog, areaportals) compiles clean, so the base file was fine
and the accumulated copy was not. Keep it that way: when a map stops having vis,
rebuild from the known-good base instead of patching the broken copy.

Current numbers, verified after the rebuild: vbsp clean and writes an 82 KB
`.prt`; vvis **385 clusters / 987 portals**, `visdatasize 35345`; vrad 13,597
triangles; 353 entities.

### Areaportals

Three `func_areaportalwindow` brushes sit in the eastern gateways — the 256×256
openings (`y -128..128`, `z 0..256`) in the 64-thick walls at `x = 4160 / 0 /
-4160`. Each fills the opening exactly (4 units thick, 9 units past the wall
centre so it does not overlap the membrane) and drives the matching
`rift_membrane_*` as its window:

```
FadeStartDist 512    FadeEndDist 896    TranslucencyLimit 0.06
```

Beyond 896 units the membrane is opaque and the far area is culled, so nothing
loads or unloads through the tear while you look at it from the hall. Inside 896
the membrane fades out and the portal opens, so you walk through and see the next
section. An areaportal must seal its opening on all four sides or vbsp rejects
it; these are sized to the measured hole, not to the shard frame (the frame is
decoration and is smaller than the opening).
