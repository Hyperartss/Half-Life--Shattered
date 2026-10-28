# Viewmodel animation setup

Everything below is already generated — these are the steps to open it, animate it,
and get it back into the game.

Weapons on offer:

| Weapon | Import this | Bones | Sequences |
|---|---|---|---|
| Desert Eagle | `Blender/v_deagle/v_deagle_anims.qc` | 31 | idle01, fire, draw, reload, holster, idletolow, lowtoidle, lowidle |
| Wrench | `Blender/v_wrench/v_wrench_anims.qc` | 13 | idle01, draw, holster, hitcenter1-3, hitkill1, misscenter1-2 |
| AR2 organic | `Blender/v_ar2_organic/v_ar2_organic_anims.qc` | 10 | 14 IR_* / fire / shake / vent poses |
| 357 base rig | `Blender/v_357/v_357_anims.qc` | 31 | the 8 pistol sequences |
| Portal gun | `Blender/v_portalgun/v_portalgun_anims.qc` | 45 | idle, fire1, fizzle, draw, holster, idletolow, lowtoidle, lowidle, pickup, release |

Each folder holds the QC plus `anims/`, one SMD per sequence and `ref.smd`
(the bind pose with the weapon's real mesh in it).

---

## 1. Open Blender

`~/.local/bin/blender` (Steam's Blender 5.0). **Blender Source Tools is already
enabled** — if the import menu ever disappears, Edit > Preferences > Add-ons >
search "Source Engine" and tick *Blender Source Tools*.

## 2. Import

**File > Import > Source Engine (.smd, .vta, .dmx, .qc)** → pick the QC from the
table above.

You get:

* an armature named `<weapon>_anims.qc_skeleton`
* a mesh named `ref` — the actual gun and hands, with the real materials
* one Action holding all the sequences as **slots**

The mesh covers the bones, so select the armature → Object Data Properties →
Viewport Display → tick **In Front** to see them.

## 3. Pick a sequence

Select the armature, open the **Action Editor** (Shift+F12 gives you a Dope
Sheet, then change the header dropdown to *Action Editor*). The action is
`<weapon>_anims.qc_skeleton`; the **slot selector next to the action name** is
where you switch sequences.

Every frame is keyed (that's how the SMDs come out of the game), so these are
baked animations, not sparse poses. Practical consequences:

* Move a bone at frame 40 and only frame 40 changes.
* To reshape a stretch, grab a column of keys in the Dope Sheet and
  rotate/scale them, or delete keys and let Source interpolate between the ones
  you keep (it lerps Euler angles at the QC's `fps 30`).
* Press `I` to key the bones you touched.

## 4. IK handles and the first-person view

The Scripting tab doesn't list your files by itself — you have to open the
script into it. Fastest way is the Python Console (one of the panels already in
that tab), paste this line and press Enter:

```python
exec(open("/home/hyper/.steam/debian-installation/steamapps/sourcemods/HLShattered/tools/viewmodel_ik_rig.py").read())
```

Or: Text Editor → **Open** (folder icon in its header) → navigate to
`HLShattered/tools/viewmodel_ik_rig.py` → **Run Script** (Alt+P).

Then press **N** in the viewport for the **Viewmodel** tab:

* **Drag the `IK_` handle** — it's the orange sphere on each wrist. Grab it with
  **G** and move it; the arm follows while you drag, and the wrist lands exactly
  on the handle. Nothing else to arm: a depsgraph handler plus a timer watch the
  handles, so plain **G** works.
* The panel shows **wrist to handle** live. `0.00` means the arm is on it; a red
  value means the target is out of reach (the arm stops at full extension) or
  live sync is off.
* **Key while dragging** — leave it on, or your pose won't survive the export.
* **Solve to handles** — pull the arm onto the handle without dragging (useful
  if you moved the handle while live sync was off).
* **Live sync** — toggles the watch, e.g. turn it off while you work on keys so
  the rig leaves the pose alone.
* **Go to viewmodel camera** — same as NumPad 0.

### Why Auto IK / an IK constraint can't be used here

Blender Source Tools imports SMD bones as 0.2-unit stubs whose axes are
**perpendicular** to the limb — measured at exactly 90.0° on every bone of this
skeleton. A bone constraint or Blender's solver bends a bone's own Y axis, so
with perpendicular axes it drives the limb sideways; **Auto IK** has the same
problem, which is why dragging a bone only ever moves that one bone.

Making the axes point along the limb would mean rewriting every bone's rest
rotation, and the model has to keep HL2's `v_357` skeleton orientation because
its animations come from `$includemodel`. Lengthening the tails is harmless (bone
length isn't part of the rest matrix, so the export doesn't change), but that
alone doesn't fix the axes.

So the rig solves the two-bone IK itself: rotate the upper arm to place the
elbow, rotate the forearm to place the wrist, using the real joint positions.
Only bone rotations are written, which is exactly what studiomdl reads back.

`Viewmodel_Camera` sits at the eye with a 90° horizontal FOV — the same as the
world in `cfg/config.cfg` (`fov_desired 90`), so NumPad 0 matches the player's
view. Note the engine draws the weapon itself a bit narrower (viewmodel_fov 54);
set `VIEWMODEL_FOV = 54.0` at the top of the script and re-run if you want that
exact framing instead.

Handles exist for the deagle (left arm) and the wrench (right arm). The organic
AR2 has no arm chain — its arms are rigid and only `Base` is skinned — so it
gets none. The portal gun is gun-only: the Sketchfab model's hands were removed
and the gun is bound rigidly to `ValveBiped.Base`, so it has no arms to pose.

## 5. Export the animations

1. Select **only the armature**. Selecting the mesh too makes it rewrite
   `ref.smd`.
2. **Properties > Scene > Source Engine Export** → set **Export Path** to
   `.../HLShattered/Blender/<weapon>/`, Format **SMD**.
3. **File > Export > Source Tools Export**:
   * the entry named `..._skeleton (reload)` exports just the slot you're on
   * the `All action slots (N)` entry exports every sequence
4. Files land in `Blender/<weapon>/anims/`, named after the slots, which is
   exactly where the QC expects them.

Which slots get exported is set in **Properties > Scene > Source Engine
Exportables > Armature Properties** (Action Selection: *Current* vs *Slot Filter*).

## 6. Compile

Two options.

**Test build** — the generated QC compiles to `models/sl_animtest/`, so it can
never overwrite a shipping model:

```
wine "$HOME/.steam/debian-installation/steamapps/common/Half-Life 2/bin/studiomdl.exe" \
  -nop4 -game "$HOME/.steam/debian-installation/steamapps/sourcemods/HLShattered" \
  "$HOME/.steam/debian-installation/steamapps/sourcemods/HLShattered/Blender/v_deagle/v_deagle_anims.qc"
```

**Real build** — add sequence lines to your own QC (it already has the mesh,
muzzle attachment and surface properties):

```
$sequence "fire" "../../Blender/v_deagle/anims/fire.smd" fps 30 ACT_VM_PRIMARYATTACK 1
```

(studiomdl resolves SMD paths relative to the QC, so that `../../` climbs out of
`modelsrc/v_deagle/` — checked against this studiomdl.) Then compile
`modelsrc/v_deagle/v_deagle.qc` with the same command.

Right now the deagle, wrench and organic AR2 inherit their animations from the
stock base weapon (`$includemodel`), so the 8 sequences in the deagle are
really the .357's. Adding sequence lines gives the deagle its own without
touching stock HL2.

The portal gun is the worked example of the second route. Its QC
(`modelsrc/v_portalgun/v_portalgun.qc`) lists Portal 1's ten sequences from
`Blender/v_portalgun/anims/`, and it compiles to the shipping
`weapons/v_portalgun.mdl` so the mod's copy replaces the Portal VPK one. The
mesh comes from `modelsrc/v_portalgun/v_portalgun_ref.smd`, which
`tools/build_portalgun.py` rebuilds from the Sketchfab FBX: it drops the hands,
scales the gun 10x and binds it 100% to `ValveBiped.Base` on the stock rig.
Because of that build step, the `ref.smd` in `Blender/v_portalgun/anims/` is
that gun-only mesh too — re-running the exporter would put the stock gun and
hands back.

## 7. Things that will bite

* **Don't animate the root bone's rotation or position.** studiomdl bakes +90°
  of yaw into the root of every sequence, so a root rotation shows up 90° off
  in game. Animate the arm and weapon bones; everything else round-trips
  exactly.
* **Don't re-run `tools/export_viewmodel_anims.py` after editing** — it
  re-decodes from the compiled `.mdl` and overwrites your SMDs. Re-run it with
  `--out` pointing somewhere else if you need a fresh copy.
* **New sequence = new QC line.** Export the slot, add a matching `$sequence`
  line with the activity name, compile.
* The small `bone_*` triangles in `ref.smd` are stand-ins for bones the mesh
  doesn't use (fingers, muzzle, cylinder, the inherited spine bones). They're
  what keeps those bones alive through a compile; they're invisible inside the
  model.

## 8. If you ever need to regenerate

```
~/.local/bin/blender -b --python-exit-code 1 --python tools/export_viewmodel_anims.py -- v_deagle v_wrench v_ar2_organic models/weapons/v_357.mdl --verify
```

`--verify` recompiles each QC with studiomdl and compares every bone on every
frame against the source animation, so a broken export is reported instead of
discovered in game.

The portal gun's mesh is rebuilt from the source FBX rather than exported from
a compiled model:

```
~/.local/bin/blender -b --python-exit-code 1 --python tools/build_portalgun.py -- \
  "/media/hyper/Storage HDD/Asset Library/Models/Sketchfab/Items/Portal Gun 3/Portal Gun 3.fbx" \
  Blender/v_portalgun/anims/ref.smd modelsrc/v_portalgun/v_portalgun_ref.smd
```

`tools/preview_viewmodel.py` renders any of these ref/sequence SMDs from the
player's eye, which is handy for checking placement without launching the game:

```
~/.local/bin/blender -b --python-exit-code 1 --python tools/preview_viewmodel.py -- \
  modelsrc/v_portalgun/v_portalgun_ref.smd Blender/v_portalgun/anims/idle.smd /tmp/idle.png
```
