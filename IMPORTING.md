# Getting models and textures into Hammer

Hammer's model and material browsers only list files the game's search paths can
see. Portal props therefore show up only while Portal is mounted, and a
downloaded custom model is invisible until its `.mdl`, `.vvd`, `.vtx` and
`materials/` files land in this mod. `tools/import_assets.py` copies them (and
everything they depend on) into the mod for you.

```bash
tools/import_assets.py sources                       # what is mounted, what is missing
tools/import_assets.py list portal lab_desk         # find an asset
tools/import_assets.py import portal models/props/lab_desk01/lab_desk01.mdl
tools/import_assets.py check                         # anything broken in the mod?
```

That import copies 8 files (278 KB): the model, its `.vvd`, three `.vtx`
variants, its `.phy`, and the material plus texture Hammer needs to draw it.

Nothing needs installing: it is one file, Python 3 standard library only, and it
reads the same `gameinfo.txt` Hammer does.

## Where the assets come from

`sources` prints these, resolved from `gameinfo.txt` plus the Steam install next
to the mod:

| Source | What it is |
|---|---|
| `mod` | this mod (`models/`, `materials/`, ...) |
| `hl2`, `ep2`, `episodic`, `platform` | the SDK Base 2013 content the mod mounts |
| `portal` | Portal 1, currently from the external library at `/media/.../Portal/portal` |
| `custom/*` | import packs, once they exist |

Any path works in place of a name:

```bash
tools/import_assets.py import ~/Downloads/coolgun.zip            # everything in the pack
tools/import_assets.py import ~/Downloads/coolgun/ coolgun        # loose folder
tools/import_assets.py import "/media/.../Portal/portal" cube     # a .vpk or a game folder
tools/import_assets.py import ~/Downloads/pack/models/weapons/v_gun.mdl
```

`sources` also reports mounts that `gameinfo.txt` names but that are not
installed, because Hammer cannot see those either.

## What gets imported with your file

The tool walks the dependency graph instead of copying one file:

| You ask for | You also get |
|---|---|
| `.mdl` | `.vvd`, every `.vtx` variant, `.phy`, the `.ani` the header names, every `$includemodel` model and its files |
| `.mdl` | the `.vmt` for every texture slot in the model, resolved through the model's `$cdmaterials` folders |
| `.vmt` | `$basetexture`, `$bumpmap`, `$envmapmask`, `$detail`, ... textures, plus `patch`/`include` parents |
| `.vtf` | the `.vmt` that uses it -- or a generated one (see below) |
| a folder or glob | all of it, file by file |

A bare `.vtf` with no `.vmt` anywhere would never appear in Hammer's material
browser, so one is generated: `VertexLitGeneric` under `models/`,
`LightmappedGeneric` elsewhere, or `--shader NAME`. An existing `.vmt` is never
replaced.

Dependencies are searched in the import source first, then in the other mounted
sources. Anything that cannot be found is listed as *missing* instead of copied
silently -- that is exactly what would render as an error model or pink texture
in Hammer.

## Where files land

By default the layout is the mod's own: `models/...` and `materials/...` at the
repo root, which is where the existing weapons live and what Hammer already
reads.

`--pack NAME` puts the same tree under `custom/NAME/` instead. `gameinfo.txt`
already has a `game+mod |gameinfo_path|custom/*` search path, so the pack is
mounted without editing anything, and removing it is one command:

```bash
tools/import_assets.py import --pack myprops portal 'models/props/*.mdl'
tools/import_assets.py unimport --pack myprops
```

Every import writes a `.import.json` next to the files it created; `unimport`
deletes exactly those files and nothing else.

Existing files are kept unless you pass `--force`, so a second import never
silently overwrites something you edited. `--dry-run` prints the whole plan
(size included) without writing.

## Checking what Hammer will load

```bash
tools/import_assets.py check                  # every model + material in the mod
tools/import_assets.py check models/weapons   # just one folder
```

It reports models with no `.vvd`/`.vtx`, materials the model asks for that do
not exist, VMT textures that are missing, and broken `patch` includes. Exit
status is 1 when something is wrong, so it can gate a build. Animation-only
models (no bodygroups) are not expected to have a mesh and are not reported.

## Baking content in so the mod needs no mounts

Every import above still leaves the source game *mounted*: the files live in
the mod, but Hammer and the game also read the game's own VPKs. `bake` copies a
whole source into the mod so it no longer has to be mounted, which is what a
single downloadable release needs.

```bash
tools/import_assets.py audit "<content dir>"   # can this engine load it at all?
tools/import_assets.py bake portal             # all of Portal 1's assets
tools/import_assets.py bake "<content dir>" 'models/props/*'   # just some props
tools/import_assets.py bake "<content dir>" --pack bm --dry-run
tools/import_assets.py release                 # what still comes from a mount
```

A *content dir* is a game folder, not a single VPK, when the game is split:
`Portal 2/portal2`, `Black Mesa/bms`. Its `*_dir.vpk` archives are picked up
automatically, so `bake`/`audit` see the whole game.

`bake` takes `models/ materials/ particles/` by default (`--only` adds
`sound/`), follows the same dependency graph as `import`, and reports the
formats it had to copy. Paths already in the mod are kept unless `--force`, so
a second bake never clobbers something you edited.

## What this engine can actually load

Measured on the installed games; the limits come from this engine's own headers
(`src/Portal-Base/sp/src/public/studio.h` = 48, `vtf/vtf.h` = 7.4) and its
Portal 1 particle loader (pcf 1).

| Game | Models | Textures | Particles | Verdict |
|---|---|---|---|---|
| Portal 1 | v44–v48 (200) | 7.1–7.4 (860) | pcf 1 (21) | **everything loads** |
| Black Mesa | v44/v48 (14,324), v49 (27) | 7.0–7.4 (10,625), 7.5 (1) | pcf 1 (137) | almost everything loads |
| Portal 2 | v49 (2,041) | 7.1–7.4 (816), 7.5 (2,641) | pcf 1 (20), pcf 2 (58) | **most of it does not** |

So Portal 1 and Black Mesa props/scenery are a straight copy. Portal 2 is not:
v49 models and 7.5 textures are a different on-disk format that this build
refuses, and its particles are DMX format 2. `audit` lists every offending file
by name, so nothing fails silently.

Whole-source bake sizes on this machine (models + materials + particles):

| Source | Files | Size |
|---|---|---|
| `portal` | 2,807 | 323 MB |
| Portal 2 | 16,548 | 2.7 GB |
| Black Mesa | 99,804 | 15.3 GB |

Black Mesa is that large because it ships 43,004 `.vtx` files for 14,352 models.
Bake what your maps use (`'models/props/*'`, a specific prop, a `maps/*.lst`
list) rather than the whole game.

## Releasing without mounts

```bash
tools/import_assets.py release                          # report only
tools/import_assets.py release --write dist/gameinfo.txt
```

`release` resolves every model and material in the mod **against the mod alone**
and groups whatever it cannot find by the game it came from, so it tells you
exactly which mounts are still load-bearing. `--write` only succeeds when that
list is empty; it then writes a `gameinfo.txt` with the external game mounts
removed (the mod's own paths and `platform` stay) to the path you give, leaving
the real `gameinfo.txt` untouched so editing keeps working.

**Licensing.** Baking copies Valve's and Crowbar Collective's art into your
release. Owning the games lets you do that locally, but shipping those files to
other people is not covered by the games' licences — a mod that ships Portal or
Black Mesa assets can be taken down. That is a decision for you, not something
the tool can check.

## Things worth knowing

* **Reopen the browser.** Hammer caches the model list while the dialog is open;
  close and reopen the model/material picker after importing.
* **Case.** Files are written lowercase, which is the Source convention and what
  the engine expects; lookups are case-insensitive, so a `.vmt` reference like
  `models/Weapons/V_hand/head.vmt` still resolves.
* **Engine limits.** This build reads studio models up to version 48, VTFs up to
  7.4 and Portal 1 particles (pcf 1). Newer files are imported but `check` and
  the import notes flag them; `audit` lists them for a whole source. 7.4 works
  because this SDK 2013 branch declares 7.4 — 7.5 (Portal 2) does not load.
* **Zips only.** `.rar` and `.7z` need extracting first -- the tool reads `.zip`,
  `.vpk` and plain folders, so it stays dependency-free.
* **It never edits `gameinfo.txt`.** Importing copies files; mounting a game is a
  separate change.
