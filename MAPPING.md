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

## Known blocker: Hammer++ crashes under Wine

Not fixed, and it is not a config problem. Hammer++ 8873 opens, paints its
windows, then dies 15-40 s in with:

```
err:  Presenter: Failed to create Vulkan surface: VK_ERROR_INCOMPATIBLE_DRIVER
terminate called after throwing an instance of 'dxvk::DxvkError'
```

`hammer_dll`/`hammerplusplus` write a minidump per launch
(`binwin/hammerplusplus_*_error.mdmp`, `STATUS_BREAKPOINT` via
`kernelbase!DebugBreak`). Tried, all with the same result:

* DXVK 2.3 (what the launcher installs) -> surface *re*creation fails, GDI
  fallback, crash; DXVK 2.7.1 -> surface creation fails outright. Both are now
  in place as 2.7.1 with a backup of the old DLLs in `/tmp/dxvk_backup_163657`
  (that directory is temporary; the launcher's winetricks can reinstall).
* Wine's built-in D3D (wined3d) instead of DXVK: the builtin 32-bit `d3d9.dll`
  is not present in this WoW64 Wine 9.0 install, so that path cannot even load.
* Removing `discord_game_sdk.dll`, removing CEF (`libcef`/`chromehtml`),
  `halflife2.fgd` instead of `portal.fgd`, EP2 config instead of the mod's,
  Proton 8.0 instead of system Wine: all still crash.
* Vanilla `hammer.exe` stays up (its game-config dialog works), so this is
  Hammer++'s custom 3D viewport hitting the broken Vulkan surface path, not
  something in the mod or the config.

Working around it needs a Wine that can create a Vulkan surface for a 32-bit
D3D9 window on this machine (newer Wine/Proton-GE, or a DXVK build that copes
with Mesa 25 + this winevulkan). Until then the compiler and the map files are
usable from the command line exactly as described above.

## Notes for the next map

* The vbsp in this install keeps only the **last** value of a duplicated key, so
  an entity can hold one connection per output name — split across entities
  instead of stacking two outputs. (Already bit the prototype; see
  `prototype_v1_blockout.md`.)
* `maps/prototype_v1.vmf` and `maps/sl_arsenal_test.vmf` are generated by
  `tools/build_prototype_v1.py` / `tools/build_sl_arsenal_test.py`. Editing them
  in Hammer is fine, but re-running the script overwrites the edits.
* `tools/build_sl_dev_room.py` writes `maps/sl_dev_room.vmf` the same way.
