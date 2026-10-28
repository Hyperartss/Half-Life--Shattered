# Handoff: viewmodel animation pipeline (Source / Blender)

Written 2026-10-28. If you are picking this up cold, read this file top to bottom,
then `Blender/README.md` (the user-facing tutorial). Everything below was measured
on this machine, not inferred.

---

## 0. The task in one paragraph

The user is making custom weapons for the Half-Life 2 mod **HLShattered** and wants to
author new first-person (viewmodel) animations for them in Blender. Stock viewmodels
inherit their animation from the base HL2 weapon via `$includemodel`, so there was
nothing editable to start from. Two tools were built: a **decoder** that turns a
compiled `.mdl` (plus everything it pulls in through `$includemodel`) into editable
SMDs + a QC, and a **Blender rig script** that adds a first-person camera and working
two-bone IK hand handles so poses can be dragged into place. Both are done and
verified end to end; the remaining work is usability, listed in §6.

`git status` shows `tools/` and `Blender/` as untracked — **nothing has been
committed**. The other modified files in the repo (`console.log`, `cfg/config.cfg`,
`gameinfo.txt`, `maps/…`, `sl_crash.txt`, …) are the game's own runtime writes, not
agent edits. Do not stage them.

---

## 1. Environment

| Thing | Value |
|---|---|
| Mod dir (repo root) | `/home/hyper/.steam/debian-installation/steamapps/sourcemods/HLShattered` |
| Blender | `~/.local/bin/blender` → **5.0.1** |
| Add-ons | `~/.config/blender/5.0/scripts/addons/`: `io_scene_valvesource` (Blender Source Tools), `sourceio` |
| Compiler | `~/…/common/Half-Life 2/bin/studiomdl.exe`, run with `wine` |
| Blender's Python | `~/…/common/Blender/5.0/python/bin/python3.11` (has numpy; needed by the decoder) |
| Branch | `main`, 5 commits, all work here uncommitted |

Blender Source Tools is required in the UI; **SourceIO is imported by the decoder**
for its `.mdl` reader (`load_sourceio()` finds it by path, so the decoder runs under
plain Python too as long as that addon is on disk).

---

## 2. What exists

```
tools/export_viewmodel_anims.py   1116 lines  decoder: .mdl -> SMDs + QC  (the worker)
tools/viewmodel_ik_rig.py          560 lines  Blender UI: camera + IK hand handles
tools/preview_smd.py               198 lines  headless SMD renderer (fallback when BST import is flaky)
tools/build_sl_arsenal_test.py     608 lines  unrelated: generates maps/sl_arsenal_test.vmf
Blender/README.md                  180 lines  user-facing tutorial (how to import / animate / export / compile)
Blender/p2_check/v_portalgun/                 leftover --out check run; safe to delete
Blender/<weapon>/<weapon>_anims.qc            generated QC (compiles to models/sl_animtest/)
Blender/<weapon>/anims/*.smd                  one per sequence + ref.smd (bind pose + real mesh)
```

Generated so far, `Blender/`:

| Model | Bones | Sequences |
|---|---|---|
| `v_deagle` | 31 | 8 (idle01, fire, draw, reload, holster, idletolow, lowtoidle, lowidle) |
| `v_wrench` | 13 | 9 (idle01, draw, holster, hitcenter1-3, hitkill1, misscenter1-2) |
| `v_ar2_organic` | 10 | 14 (IR_* poses, fire, shake, vent) |
| `v_357` | 31 | 8 (the pistol set — this is what the deagle currently inherits) |
| `v_portalgun` | — | 10 |

---

## 3. The decoder (`tools/export_viewmodel_anims.py`)

Reads the compiled model + all `$includemodel` dependencies, writes
`anims/<sequence>.smd`, `anims/ref.smd` and `<model>_anims.qc`.

Three conventions were reverse-engineered from the shipped artifacts and are
**load-bearing** — get them wrong and the animation is silently skewed:

1. **SMD rotation numbers are radians**, not degrees. This studiomdl and the
   hand-written SMDs in `modelsrc/` both use radians. `--degrees` exists for other
   toolchains.
2. **studiomdl bakes a +90° yaw into the root bone** of every sequence (SMD space →
   studio space). It is *not* in the reference pose, so the root's animated
   translation/rotation must have it removed on export or it lands twice.
   `--no-root-compensation` disables this. Source of truth: `bone_setup.cpp`.
3. **Animations store absolute bone orientations:**
   `angle = anim_value * bone_rotscale + bone_base_angle`.

`ref.smd` carries the model's **real mesh** (positions, normals, UVs, weights from
`.vvd`/`.vtx`), so an import shows the gun and hands on the rig instead of a floating
skeleton. Bones no triangle references get one small `bone_*` marker triangle at the
bind pose, otherwise studiomdl drops them.

`--verify` recompiles the QC with studiomdl and re-decodes the output, comparing every
bone on every frame against the source animation. Use it after any change to the
decoder.

**Hazard:** re-running the decoder overwrites the user's edited SMDs. Point `--out`
somewhere else.

---

## 4. The rig (`tools/viewmodel_ik_rig.py`)

Run from Blender's Python Console after importing a `_anims.qc`:

```python
exec(open("<mod>/tools/viewmodel_ik_rig.py").read())
```

Adds `Viewmodel_Camera` (eye position, 90° horizontal FOV, looks down model −Y) and one
`IK_<hand>` empty per arm chain, plus an N-panel tab.

### 4.1 Why there is no Blender IK constraint and no Auto IK

This is the single most important finding. **Every bone's axis is at exactly 90.0° to
the limb it drives** — Blender Source Tools imports SMD bones as 0.2-unit stubs whose
axes are perpendicular, because they carry orientation, not length. A constraint or
Auto IK bends the bone's own Y axis, so with perpendicular axes it swings the limb
sideways. Dragging a bone in pose mode moves that one bone and nothing else.

Two things were tested to be sure there was no way around it:

* **Lengthening the tails is safe.** Bone length is not part of the rest matrix;
  resizing every bone left the exported rest rotations identical to within **3e-6**
  (float noise). So the tails could be lengthened — it just doesn't fix the axes.
* **Reorienting the axes is not safe.** It rewrites every bone's rest rotation, and the
  model must keep HL2's `v_357` skeleton orientation because its sequences come from
  `$includemodel`. Rigs that did this would break every inherited animation.

Consequence: adding an `IK` constraint, or telling the user to enable Auto IK, will
regress this. Don't.

### 4.2 The solver

`solve_chain()` does closed-form two-bone IK in armature space:

* Joint positions come from the **current pose** (`pose.bones[x].matrix.translation`),
  so the perpendicular stubs are irrelevant — the vectors between joint heads are the
  real limb.
* Law of cosines places the elbow, keeping it in the plane it is currently bending in
  (no pole target; see §6.3).
* Both rotations are computed **before either is written**, then applied as
  `matrix_basis` via `_basis_from_pose()`. No `view_layer.update()` in the middle —
  that is what lets the solve survive an assigned action re-evaluating over it.
* Distance is clamped just inside full extension, so unreachable targets stop the arm
  instead of stretching or spinning.

Keying (`key_bones()`):

* Keys **location as well as rotation**. The imported pose carries a ~1.1-unit location
  offset on the upper arm (BST writes it from the SMD joint offset); keying rotation
  alone dropped the pose by a measurable **0.12 units**.
* Keys whichever rotation channel the bone is actually in
  (`rotation_quaternion` vs `rotation_euler`). Animated skeletons import in Euler XYZ.

### 4.3 The trigger (the part that was broken)

The original design used a modal grab and a timer, and it silently did nothing. Three
real bugs were found by reading the interaction path rather than the math:

1. Handle position read from a **stale `matrix_world`** (lags until the next depsgraph
   evaluation). Handles are created **unparented**, so `handle_position()` reads
   `empty.location` directly.
2. The follow branch recorded that stale value as its baseline, so a moved handle was
   seen as already there and never solved.
3. Rotation-only keying (above).

Trigger is now a **`depsgraph_update_post` handler (persistent) plus a 0.05 s timer**,
both calling `sync_handles()`, which compares each handle against `_LAST`
`(handle position, wrist position)` per handle to tell "the user dragged the handle"
from "the animation moved the arm". `_BUSY` guards re-entry. `stop_watch()` removes
both by handler `__name__`, so re-running the script is safe.

UI: `VIEWMODEL_PT_panel` in the N-panel *Viewmodel* tab — live **wrist to handle** gap
readout, Solve to handles, Key this pose, Key while dragging, Live sync toggle, Go to
viewmodel camera. Classes are unregistered before re-registration so a second run
doesn't duplicate them.

Handles exist for `v_deagle` (left arm, `Bip01_L_*`) and `v_wrench` (right arm,
`ValveBiped.Bip01_R_*`). `v_ar2_organic` gets none: its arms are rigid and only `Base`
is skinned, so there is nothing to bend. Handles are empties, so BST never exports them
(extra bones in an SMD are unknown-bone warnings).

---

## 5. Verified state (re-run these before trusting anything)

```bash
# 1. solver, headless, on the deagle rig  -> expect exact 0.0000 / clamp on the far target
#    (see §8 for the probe script)

# 2. decode + verify one model
~/.local/bin/blender -b --python-exit-code 1 --python tools/export_viewmodel_anims.py -- v_deagle --verify

# 3. all five
~/.local/bin/blender -b --python-exit-code 1 --python tools/export_viewmodel_anims.py -- \
    v_deagle v_wrench v_ar2_organic models/weapons/v_357.mdl --verify
```

Measured 2026-10-28 (`solve_chain` on `v_deagle` at frame 0, wrist start
`(-5.275, -14.022, -11.309)`). Output of the §8 probe verbatim:

```
[3, -1, 0.5] 0.0 3.162979879718208e-06
[60, 0, 0] 29.236640756742215 29.236642421338072
```

| Target offset | Solve residual | Measured wrist→target after evaluation |
|---|---|---|
| `+3.0, -1.0, +0.5` | 0.0 | **3.2e-6** (float noise) |
| `-2.0, +0.5, +1.5` (basis reset first) | 0.0 | **0.0000** |
| `0.0, 0.0, -2.0` (basis reset first) | 0.0 | **0.0000** |
| `+60.0, 0, 0` (unreachable) | 29.2366 | **29.2366** (clamps at full extension) |

The clamp distance depends on the pose the solve starts from — the elbow stays in its
current bend plane, so a run that follows a previous solve reaches ~29.24 where a fresh
one reached ~29.49. Both are "arm at full extension", which is the intended behaviour;
don't treat the exact clamp figure as a constant.

Also previously established, all by re-reading the artifacts rather than eyeballing:

* Export fidelity: `fire.smd`'s hand **composed** world position (SMD bone lines are
  parent-relative — comparing raw translations shows nothing) moved by exactly the
  `3.0 / −1.0 / 0.5` dragged in Blender.
* Compile fidelity: that SMD compiled clean with studiomdl and the MDL's hand sits at
  the same point after the engine's +90° root yaw.
* Frame-change behaviour, drag→key→reframe gap 0.00, handle riding along when the
  animation moves the arm, handle rebuild and single-registration on a second run.
* Camera orientation: at frame 0 of `idle01`, 9,933 / 9,954 vertices sit in front of
  `Viewmodel_Camera` at 0.1–30 units; the muzzle lands 10.7° right / 7.3° down.

---

## 6. Open issues, priority order

**6.1 The trigger has never fired from a real mouse drag. (highest risk)**
All trigger verification was done headless by *simulating the depsgraph update the
handler receives*. Blender timers are known not to tick reliably during a viewport
transform, and a persistent handler may not fire mid-drag in all editor states. If the
user reports the gap readout staying at 0.00 with the arm not following, stop tuning
the current design and replace it with a **modal operator**: a button that calls
`bpy.ops.transform.translate('INVOKE_DEFAULT')` on the selected handle with a modal
handler that runs `solve_chain` on `MOUSEMOVE` and keys on `LEFTMOUSE` (confirm) /
`ESC` (cancel). That path is what `bpy` guarantees fires.

**6.2 Keyframes written from a handler bypass undo and clobber the current frame.**
`keyframe_insert` inside a depsgraph handler is not part of the undo stack, and every
drag step overwrites whatever keys exist at the current frame. Consider: only key on
drag *end* (mouse release), or wrap in `bpy.ops.ed.undo_push`.

**6.3 No elbow/pole control.** The elbow stays in the plane it was already bending in.
Fine for arms on a viewmodel; would need a pole empty for anything more expressive.

**6.4 Re-running the script rebases handles onto the current pose.** `hand_handles()`
sets each handle from the current wrist, so re-running on a posed frame is harmless but
discards the previous handle positions. Documented; could be fixed by keeping existing
handle locations when the object already exists.

**6.5 Root-bone authoring rule.** Never animate the root bone's rotation or position:
studiomdl's baked +90° yaw makes a root rotation show up 90° off in game. Arms and
weapon bones round-trip exactly. Documented in the README; worth a UI guard.

**6.6 Doc drift.** `Blender/README.md`'s weapon table predates `v_portalgun` (which is
generated and sitting in `Blender/v_portalgun/`). Add the row. `Blender/p2_check/` is a
leftover check run and can go.

**6.7 Scope limits.** Two-bone arms only — no fingers, no spine, no torso; the deagle's
17 finger/muzzle bones are carried but not driven.

---

## 7. Gotchas that already cost time

* **`pose.bones[x].head` / `.matrix` are stale** until a depsgraph evaluation. Any test
  that reads them straight after writing a `matrix_basis` measures the old pose.
* **SMD bone lines are parent-relative.** Comparing raw `x y z` across two files shows
  "no change" when the limb clearly moved. Compose the chain down to the bone you care
  about.
* **`matrix_basis` vs quaternion keys.** Writing `rotation_quaternion` keys on a bone
  in Euler mode writes channels nothing evaluates; the pose vanishes on the next frame.
* **Action slots (Blender 4.4+/5.x).** The imported sequences are *slots* of one action.
  Exported slot selection lives in **Properties > Scene > Source Engine Exportables >
  Armature Properties** (Action Selection: Current / Slot Filter) — not the Object tab.
  `State.useActionSlots` gates the API shape in the add-on.
* **Animations live in `*_anims.qc`.** Importing the bare model QC gives you a pose with
  no action.
* **`$sequence "../../Blender/<weapon>/anims/x.smd"` does compile** (studiomdl resolves
  relative to the QC), verified against this studiomdl.
* **BST import in background mode is flaky** on this build; `tools/preview_smd.py`
  renders an SMD without it if the importer misbehaves.

---

## 8. Reproduction recipes

Solver probe (headless, ~15 s):

```bash
cd /tmp && cat > ikprobe.py <<'PY'
import bpy, addon_utils
from mathutils import Vector
MOD = "/home/hyper/.steam/debian-installation/steamapps/sourcemods/HLShattered"
bpy.ops.wm.read_factory_settings(use_empty=True)
addon_utils.enable("io_scene_valvesource")
bpy.ops.import_scene.smd(filepath=MOD + "/Blender/v_deagle/v_deagle_anims.qc")
bpy.context.scene.frame_set(0); bpy.context.view_layer.update()
ns = {"__name__": "not_main"}
exec(open(MOD + "/tools/viewmodel_ik_rig.py").read(), ns)
arm = [o for o in bpy.data.objects if o.type == 'ARMATURE'][0]
upper, forearm, hand = list(ns["arm_chains"](arm))[0]
def wrist():
    bpy.context.view_layer.update()
    return (arm.matrix_world @ arm.pose.bones[hand].head).copy()
start = wrist()
for off in ([3, -1, 0.5], [60, 0, 0]):
    target = start + Vector(off)
    print(off, ns["solve_chain"](arm, upper, forearm, hand, target), (wrist() - target).length)
PY
~/.local/bin/blender -b --factory-startup --python-exit-code 1 --python /tmp/ikprobe.py
```

Compile a generated QC to the throwaway target (`models/sl_animtest/`, never a shipping
model):

```bash
wine "~/.../common/Half-Life 2/bin/studiomdl.exe" -nop4 \
  -game "~/.../sourcemods/HLShattered" \
  "~/.../sourcemods/HLShattered/Blender/v_deagle/v_deagle_anims.qc"
```

Read a pose out of a compiled MDL (for before/after comparisons) using SourceIO's
`mdl_file` reader the same way `export_viewmodel_anims.py` does.

---

## 9. What "done" looks like for the next stretch

1. A drag with the mouse in a real GUI moves the arm, with the panel gap reading 0.00
   while held and after release (§6.1).
2. The confirmed pose survives: frame change, Ctrl+Z, save/reopen, export, compile, and
   shows up in game as the new sequence.
3. `--verify` passes for all five models after any decoder change.
