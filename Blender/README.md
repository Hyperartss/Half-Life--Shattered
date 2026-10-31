# Viewmodel animation setup

Everything below is already generated — these are the steps to open it, animate it,
and get it back into the game.

Weapons on offer:

| Weapon | Import this | Bones | Sequences |
|---|---|---|---|
| Desert Eagle | `Blender/v_deagle/v_deagle_anims.qc` | 48 | HL2 **pistol** set: idle01(empty), fire, fire1-3, fireempty, draw(empty), reload, holster(empty), idletolow, lowtoidle, lowidle |
| Wrench | `Blender/v_wrench/v_wrench_anims.qc` | 39 | idle01, draw, holster, hitcenter1-3, hitkill1, misscenter1-2 |
| AR2 organic | `Blender/v_ar2_organic/v_ar2_organic_anims.qc` | 37 | 14 IR_* / fire / shake / vent poses |
| 357 base rig | `Blender/v_357/v_357_anims.qc` | 31 | the 8 pistol sequences |
| Portal gun | `Blender/v_portalgun/v_portalgun_anims.qc` | 45 | idle, fire1, fizzle, draw, holster, idletolow, lowtoidle, lowidle, pickup, release |

Each folder holds the QC plus `anims/`, one SMD per sequence and `ref.smd`
(the bind pose with the weapon's real mesh in it).

---

## 0. The easy way: the SL Viewmodel add-on

`tools/blender_addon/sl_viewmodel-1.0.0.zip` puts the whole workflow below in
one place. Install it once: **Edit > Preferences > Get Extensions > ▾ (top
right) > Install from Disk...** and pick the zip. If Steam's Blender is in a
different place than the defaults, set the mod folder and `studiomdl.exe` in
the add-on's preferences (**Add-ons > SL Viewmodel**).

Then in the 3D viewport press **N** and open the **Viewmodel** tab:

1. **Weapon**: pick deagle / wrench / organic rifle / portal gun, *Load
   weapon*. It clears the scene, imports the QC, builds the IK handles and
   camera, and shows animation 1.
2. **Animations**: every animation as a numbered list with its activity and
   length. Click one to edit it (the timeline jumps to its frames). **+** makes
   a new one (a copy of the selected one, or just its first frame and a length
   you choose), **-** deletes, the pencil renames, the arrows step through
   them. Set what the game plays it for (*Activity*: fire, reload, idle...),
   *Weight*, *FPS* and *Loop* below the list.
3. **Pose**: the hands, fingers and gun parts panel described in section 4.
4. **Save and test**: *Export* this animation or all of them into
   `Blender/<weapon>/anims/` (the first time a file is overwritten the
   decoded original is kept in `anims/_original/`). *Export mesh* after
   adding gun-part bones. *Test model* exports everything and compiles
   `models/sl_animtest/<weapon>.mdl`; *Game model* compiles the real
   `models/weapons/<weapon>.mdl` with your animations: it writes
   `modelsrc/<weapon>/<weapon>_anims.qci` and swaps the shipping QC's
   `$includemodel` for it (both at once would make the game pick stock or
   yours at random). *Show compile log* opens studiomdl's output.

The add-on's source is next to the zip in `tools/blender_addon/sl_viewmodel/`.
The manual steps below still work and explain what each button does.

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

## 4. The rig: both hands, fingers, gun

### What each weapon has (since 2026-10-28)

`tools/fit_shephard_arms.py` fitted Adrian Shephard's own arm rig (from the GMod
player model in the Asset Library) back onto the frozen arms in every viewmodel,
using the UVs the arms still share with the player model:

| Weapon | Left hand | Right hand | Animate the gun with |
|---|---|---|---|
| AR2 organic | new full arm + fingers (`ValveBiped.Bip01_L_*`) | new full arm + fingers (`ValveBiped.Bip01_R_*`) | **`Gun`** (new, under `Base`; rifle and both arms ride on it) |
| Deagle | HL2 pistol's left arm + fingers | HL2 pistol's right arm + thumb/index, **new** middle and `Finger3` | `ValveBiped.base` (see *Gun bones*) |
| Wrench | **new arm + fingers**, grafted from the deagle's left arm and parked just below the screen | existing arm + **new fingers** | `Wrench` (see *Gun bones*) |

The new bones ride along with their parents in every existing sequence, so the
stock animations deform **exactly** as before (checked vertex by vertex, every
frame of every sequence, decoded and shipping meshes). The originals are in
`Blender/_backup_before_arms/` and `modelsrc/<weapon>/<weapon>_ref.before_arms.smd`.

The portal gun is gun-only: the Sketchfab model's hands were removed and the gun
is bound rigidly to `ValveBiped.Base`, so it has no arms to pose.

Finger names follow the player model: `Finger0x` thumb, `Finger1x` index,
`Finger2x` middle (the low-poly hand's other fingers are on it too), `Finger3`
a small stub.

### Run the rig script

The Scripting tab doesn't list your files by itself. Paste this into its Python
Console and press Enter:

```python
exec(open("/home/hyper/.steam/debian-installation/steamapps/sourcemods/HLShattered/tools/viewmodel_ik_rig.py").read())
```

(or Text Editor → Open → `tools/viewmodel_ik_rig.py` → Run Script.)
Then **N** in the viewport → **Viewmodel** tab.

### Hands

* Every arm has an `IK_<hand>` sphere on its wrist. **Moving** it moves
  the arm; **rotating** it turns the hand, and whatever the hand holds (the
  wrench, the deagle).
* **J** with the mouse over the viewport grabs the handle nearest the mouse.
  While dragging: **R** turns instead of moves, **G** moves again, **X/Y/Z**
  lock an axis, **Shift** is fine control. **Left click / Enter** keeps the
  pose and keys it (one Ctrl+Z step), **right click / Esc** puts it back.
  Each hand's box in the panel has the same drag button.
* Plain **G / R** on a selected handle works too (live sync follows it), and
  **Solve to handles** pulls the arms onto the handles if they ever disagree.
  **Handles to hands** does the opposite without touching the pose.
* The box shows **wrist to handle** for each hand: `0.00` is on target, a red
  value means out of reach (the arm stops at full stretch).
* **Elbow targets** adds a cone (`POLE_<hand>`) per two-bone arm; the elbow
  points at it. The X button removes them.
* One-bone arms (an `Arm` -> `Hand` pair, as the .357 rig had) aim at the
  handle and slide a little along their length (up to 8 units). None of the
  current weapons has one any more.
* The deagle's right arm sits almost fully stretched in the pistol's poses,
  so its handle can't push the gun much further forward than the stock pose.

### Gun bones (since 2026-10-28)

Every gun hangs off its own bone instead of sharing the hand's, and its moving
parts have bones of their own. New part bones line up with the model: local
Y runs along the barrel, Z is up, X is side to side.

| Weapon | Gun bone | Parts |
|---|---|---|
| Deagle | `ValveBiped.base` (frame, grip) | `ValveBiped.square` slide, `ValveBiped.hammer`, `ValveBiped.clip` magazine (hangs off the hand, as in HL2's reload), `Deagle_Barrel`, `Deagle_Trigger`, `Deagle_SlideStop` |
| Wrench | `Wrench` (pivot at the grip) | `Wrench_HookJaw` (slides along Z), `Wrench_Nut` (spins about Z) |
| Organic rifle | `Gun` | none: the rifle is one welded mesh, so parts can only be cut by hand (*Part from selection* below) and will tear at the cut |

The pistol animations already move `square`, `hammer` and `clip`, so the
deagle's slide racks and its magazine comes out in `reload` with no work.
The split is `tools/split_gun_parts.py`; it keeps the stock animations
identical (checked frame by frame) and is safe to re-run.

### The deagle is on HL2's pistol rig (since 2026-10-28)

`tools/build_deagle_on_pistol.py` rebuilt the deagle on the skeleton of HL2's
`v_pistol` (decoded into `Blender/v_pistol/`), so it uses the pistol's 15
sequences instead of the .357's. Shephard's arms were moved bone by bone onto
the pistol's arm pose (both models use Valve's ValveBiped bone axes), and the
deagle is lined up with the USP: same barrel line, hammer pivot on the USP's
hammer pivot, so it points where the USP points. The shipping QC now uses
`$includemodel "weapons/v_pistol.mdl"`, and the muzzle attachment is on the
deagle's real barrel tip. The .357 version is in `Blender/_backup_deagle_357/`
and `modelsrc/v_deagle/v_deagle_ref.357.smd`.

### Fingers

* **Curl / Open** bend all fingers of that hand 10° around their knuckles,
  **Thumb + / -** the thumb. Each press keys them; Open exactly undoes Curl.
* For one finger: select its bone in Pose Mode, **R**, then **I** to key.

### Gun parts

* The panel lists every gun bone with its vertex count. Click a name to
  select it in Pose Mode, then **R / G** and **I**.
* `no mesh` means the bone moves nothing (the organic rifle's
  `Bolt`/`Claw`/`Vent` came with a skeleton whose mesh is rigid). To make a part move: select the mesh, **Tab** into
  Edit Mode, hover the part and press **L** (select linked), then
  **Part from selection** in the panel: name it, keep the suggested parent
  (`Gun` on the organic rifle, `ValveBiped.base` on the deagle), OK. That makes a bone
  at the part's centre, turned like its parent, holding just those vertices.
  **Bind selection to bone** puts vertices on a bone that already exists.
* After making parts, export the **mesh as well as the armature** once (see
  section 5), otherwise `ref.smd` doesn't know about the new bone.

### Why the root is locked, and why there's no Blender IK constraint

Root bones are locked (`Base`, `ValveBiped.Bip01`, ...): studiomdl adds 90° of
yaw to the root, so a root edit lands rotated in game. Animate the gun bone in
the table above instead.

Blender Source Tools imports SMD bones as short stubs whose axes are at 90° to
the limb, so a Blender IK constraint or Auto IK, which bends a bone's own Y
axis, swings the limb sideways. The rig solves the arms itself from the joint
positions and writes plain rotations, which is exactly what studiomdl reads.

`Viewmodel_Camera` sits at the eye with a 90° horizontal FOV (NumPad 0). The
engine draws the weapon at viewmodel_fov 54: set `VIEWMODEL_FOV = 54.0` at the
top of the script and re-run for that exact framing.

## 5. Export the animations

1. Select **only the armature**. Selecting the mesh too makes it rewrite
   `ref.smd` -- which is what you want once after making gun parts. The
   shipping model needs the new part bones too: either copy the exported
   mesh over `modelsrc/<weapon>/<weapon>_ref.smd`, or point the shipping
   QC's `$model` line at `../../Blender/<weapon>/anims/ref.smd`.
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
stock base weapon (`$includemodel`), so the 15 sequences in the deagle are
really HL2's pistol's. Adding sequence lines gives the deagle its own without
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

The portal gun's QC also carries all 17 `$attachment` points, on
`ValveBiped.Base`. The client's portal gun effect
(`C_WeaponPortalgun::StartEffects`) looks up `Body_light`, `Inside_effects`,
`Beam_point1-5` and `Arm{1,2,3}_attach{1,2,3}` **by name on the viewmodel**, and a
failed lookup leaves the effect drawn at a stale position — a stray particle that
trails the gun when the viewmodel swings. Each name drives a sprite: `Body_light`
is the body glow (`grav_light`/`bluelight`/`orangelight`, all three at the one
point), `Arm*_attach1/2` the prong glows (`glow04_noz`) and `Arm*_attach3` the
prong flares (`grav_flare`).

Their **positions** are not the stock Portal ones. This gun is a different shape
with its own three prongs, so the stock numbers left the body light hanging 2.2
units off the shell and the three prong flares about 4 units in front of the
gun — three lights floating in the air beside it. The QC instead snaps each name
onto this mesh: `Body_light` on top of the body, one prong's root/mid/tip per
`Arm`, `Inside_effects` on the barrel face, the beam points just behind it on the
barrel axis and `muzzle` at the barrel exit. Every sprite point sits 0.06-0.25
units proud of the surface.

If the mesh is ever rebuilt, re-place them: the points are Base-local Source
units (`Z` forward, `Y` up) and each should stay within a few tenths of a unit
of the surface it belongs to. `tools/build_portalgun.py` prints the gun's bounds, and
`blender -b --python tools/preview_viewmodel.py -- <ref> <anim> out.png` renders
the result from the player's eye.

## 6b. Portal brightness and colour

`materials/models/portals/portalstaticoverlay_1.vmt` (blue) and `_2.vmt`
(orange) override Portal's own rim materials. The ring is a `PortalRefract`
material at `$Stage 2`, so its look is just the colour ramp texture times
`$PortalColorScale`, and the shader exposes nothing else (no tint or saturation
knob). Two changes, both in those two files:

* **Brightness** — `$PortalColorScale` drops from `4.0` to `1.4` (blue) and
  `1.25` (orange), the values Portal's own non-HDR fallback branch uses, so the
  rim keeps its colour instead of clipping to white.
* **Saturation** — `$PortalColorTexture` points at `portal-blue-color-muted` /
  `portal-orange-color-muted`, desaturated copies of the stock 256x1 colour
  ramps (60% of the original chroma, mixed toward Rec.709 luma: blue ends at
  `(59,104,142)`, orange at `(189,141,88)`). Same BGR888, 9 mips and
  `CLAMP_S|CLAMP_T|PWL_CORRECTED|NO_MIP|NO_LOD` as the originals, so only the
  colours differ.

Delete the two `.vmt` files to get stock Portal rim colour back. The portal
*hole* (`portal_refract_1/2`, `portal_*_dynamicmesh`) is a different material and
is untouched, so only the ring is muted.

## 7. Things that will bite

* **Don't animate the root bone's rotation or position** (the rig locks it).
  studiomdl bakes +90° of yaw into the root of every sequence, so a root
  rotation shows up 90° off in game. Animate the arm, finger and gun bones.
* **The shipping QCs still use `$includemodel`.** That keeps working with the
  new bones (they sit in their bind pose under the stock animations, which
  is where the fitted arms already were). The organic rifle's muzzle
  attachment now rides `Gun` instead of `Base` -- same place, but it follows
  gun animation.
* **Don't re-run `tools/fit_shephard_arms.py` on purpose to "update"** -- it
  skips weapons that already have the finger bones. To redo one, restore its
  files from the backups first.
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

The deagle, wrench and organic rifle folders are no longer plain decodes: they
were rebuilt by `tools/fit_shephard_arms.py`, `tools/split_gun_parts.py` and
(deagle) `tools/build_deagle_on_pistol.py`. Regenerating them with the decoder
throws that work away; decode into `--out` somewhere else instead.

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
