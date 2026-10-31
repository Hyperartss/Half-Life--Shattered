"""SL Viewmodel: animate Shattered Life's first-person weapons in Blender.

N panel > Viewmodel tab, in four numbered steps:

  1  Weapon      pick a weapon from the mod and load it (rig, arms, gun)
  2  Animations  the weapon's animations as a numbered list: click one to
                 edit it; add, copy, rename, delete; set its activity
  3  Pose        IK hands, finger curl, gun parts (J drags a hand)
  4  Save/test   export the animations (and mesh), compile a test model or
                 the real one, all from the panel

Needs Blender Source Tools (for the import) and, to compile, Half-Life 2's
studiomdl.exe run through Wine.
"""
import json
import os
import re
import shutil
import subprocess

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty

from . import rig, smd_io

DEFAULT_MOD = os.path.expanduser("~/.steam/debian-installation/steamapps/sourcemods/HLShattered")
DEFAULT_STUDIOMDL = os.path.expanduser("~/.steam/debian-installation/steamapps/common/Half-Life 2/bin/studiomdl.exe")

ACTIVITIES = [
    "ACT_VM_IDLE", "ACT_VM_IDLE_EMPTY", "ACT_VM_DRAW", "ACT_VM_HOLSTER", "ACT_VM_PRIMARYATTACK",
    "ACT_VM_SECONDARYATTACK", "ACT_VM_RELOAD", "ACT_VM_DRYFIRE", "ACT_VM_RECOIL1", "ACT_VM_RECOIL2",
    "ACT_VM_RECOIL3", "ACT_VM_HITCENTER", "ACT_VM_HITKILL", "ACT_VM_MISSCENTER", "ACT_VM_FIDGET",
    "ACT_VM_IDLE_LOWERED", "ACT_VM_IDLE_TO_LOWERED", "ACT_VM_LOWERED_TO_IDLE", "ACT_VM_PULLBACK",
    "ACT_VM_THROW", "ACT_VM_PICKUP", "ACT_VM_RELEASE", "ACT_VM_FIZZLE",
]
META_KEY = "slvm_meta"


# --------------------------------------------------------------------------
# settings
# --------------------------------------------------------------------------
class SLVM_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    mod_dir: StringProperty(name="Mod folder", subtype="DIR_PATH", default=DEFAULT_MOD)
    studiomdl: StringProperty(name="studiomdl.exe", subtype="FILE_PATH", default=DEFAULT_STUDIOMDL)
    wine: StringProperty(name="Wine command", default="wine",
                         description="Runs studiomdl.exe; leave empty on Windows")

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "mod_dir")
        col.prop(self, "studiomdl")
        col.prop(self, "wine")


def prefs():
    return bpy.context.preferences.addons[__package__].preferences


def mod_dir():
    return bpy.path.abspath(prefs().mod_dir).rstrip("/")


_WEAPON_ITEMS = []


def weapon_items(self, context):
    """Every Blender/<weapon>/<weapon>_anims.qc in the mod."""
    items = []
    base = os.path.join(mod_dir(), "Blender")
    if os.path.isdir(base):
        for name in sorted(os.listdir(base)):
            if name.startswith("_"):
                continue
            # only real weapons: a reference decode like v_pistol or v_357 has
            # no shipping QC in modelsrc/
            if os.path.exists(os.path.join(base, name, name + "_anims.qc")) and \
                    os.path.exists(os.path.join(mod_dir(), "modelsrc", name, name + ".qc")):
                items.append((name, name, "Blender/%s/%s_anims.qc" % (name, name)))
    if not items:
        items = [("NONE", "(no weapons found)", "Set the mod folder in the add-on preferences")]
    _WEAPON_ITEMS[:] = items  # Blender needs the strings kept alive
    return _WEAPON_ITEMS


_ACTIVITY_ITEMS = []
_LOADING = [False]


def activity_items(self, context):
    names = list(ACTIVITIES)
    for info in read_meta(current_armature(context)).values():
        act = info.get("activity")
        if act and act not in names:
            names.append(act)
    _ACTIVITY_ITEMS[:] = [("NONE", "(no activity)", "Only played by name")] + [(a, a, "") for a in names]
    return _ACTIVITY_ITEMS


def _settings_changed(self, context):
    if _LOADING[0]:
        return
    armature = current_armature(context)
    if armature is None:
        return
    slot = current_slot(armature)
    if slot is None:
        return
    meta = read_meta(armature)
    info = meta.setdefault(slot.name_display, {})
    info["activity"] = "" if self.activity == "NONE" else self.activity
    info["weight"] = self.weight
    info["fps"] = self.fps
    info["loop"] = self.loop
    write_meta(armature, meta)


def _anim_index_changed(self, context):
    select_animation(context, self.anim_index)


class SLVM_Settings(bpy.types.PropertyGroup):
    weapon: EnumProperty(name="Weapon", items=weapon_items)
    anim_index: IntProperty(name="Animation", default=0, update=_anim_index_changed)
    activity: EnumProperty(name="Activity", items=activity_items, update=_settings_changed,
                           description="What the game plays it for (fire, reload, idle...)")
    weight: IntProperty(name="Weight", default=1, min=0, update=_settings_changed,
                        description="Chance against other animations with the same activity")
    fps: FloatProperty(name="FPS", default=30.0, min=1.0, update=_settings_changed)
    loop: BoolProperty(name="Loop", default=False, update=_settings_changed)
    ship_mesh: BoolProperty(name="Also update the shipping mesh", default=True,
                            description="Write modelsrc/<weapon>/<weapon>_ref.smd too")


# --------------------------------------------------------------------------
# helpers: armature, slots, metadata
# --------------------------------------------------------------------------
def current_armature(context=None):
    context = context or bpy.context
    for obj in context.scene.objects:
        if obj.type == "ARMATURE" and obj.get("slvm_weapon"):
            return obj
    obj = context.active_object
    if obj is not None and obj.type == "ARMATURE":
        return obj
    return next((o for o in context.scene.objects if o.type == "ARMATURE"), None)


def weapon_of(armature):
    return armature.get("slvm_weapon") if armature else None


def action_of(armature):
    ad = armature.animation_data if armature else None
    return ad.action if ad else None


def slots_of(armature):
    action = action_of(armature)
    return list(action.slots) if action else []


def current_slot(armature):
    ad = armature.animation_data if armature else None
    return ad.action_slot if ad else None


def channelbag(action, slot, ensure=False):
    if not action.layers:
        if not ensure:
            return None
        action.layers.new("Layer")
    layer = action.layers[0]
    if not layer.strips:
        if not ensure:
            return None
        layer.strips.new(type="KEYFRAME")
    strip = layer.strips[0]
    return strip.channelbag(slot, ensure=ensure)


def key_range(action, slot):
    cb = channelbag(action, slot)
    lo, hi = None, None
    if cb is not None:
        for fc in cb.fcurves:
            if fc.keyframe_points:
                a, b = fc.keyframe_points[0].co.x, fc.keyframe_points[-1].co.x
                lo = a if lo is None else min(lo, a)
                hi = b if hi is None else max(hi, b)
    if lo is None:
        return 0, 0
    return int(round(lo)), int(round(hi))


def read_meta(armature):
    action = action_of(armature)
    if action is None:
        return {}
    try:
        return json.loads(action.get(META_KEY, "{}"))
    except ValueError:
        return {}


def write_meta(armature, meta):
    action = action_of(armature)
    if action is not None:
        action[META_KEY] = json.dumps(meta)


def anim_range(armature, slot):
    lo, hi = key_range(action_of(armature), slot)
    end = read_meta(armature).get(slot.name_display, {}).get("end")
    if end is not None:
        hi = max(hi, int(end))
    return lo, hi


def clean_name(name):
    name = re.sub(r"[^A-Za-z0-9_]+", "_", name.strip()) or "anim"
    return name


def select_animation(context, index):
    armature = current_armature(context)
    slots = slots_of(armature)
    if not slots:
        return
    index = max(0, min(index, len(slots) - 1))
    slot = slots[index]
    armature.animation_data.action_slot = slot
    lo, hi = anim_range(armature, slot)
    scene = context.scene
    scene.frame_start, scene.frame_end = lo, max(hi, lo)
    scene.frame_set(lo)
    settings = scene.slvm
    info = read_meta(armature).get(slot.name_display, {})
    _LOADING[0] = True
    try:
        settings.activity = info.get("activity") or "NONE"
        settings.weight = int(info.get("weight", 1))
        settings.fps = float(info.get("fps", 30.0))
        settings.loop = bool(info.get("loop", False))
    finally:
        _LOADING[0] = False
    context.view_layer.update()
    rig.snap_handles_to_hands()


def sequences_in_order(armature):
    meta = read_meta(armature)
    out = []
    for slot in slots_of(armature):
        info = dict(meta.get(slot.name_display, {}))
        info.setdefault("fps", 30.0)
        out.append((slot.name_display, info))
    return out


def anims_dir(weapon):
    return os.path.join(mod_dir(), "Blender", weapon, "anims")


def keep_original(path):
    """First time a file is overwritten, keep the decoded original."""
    if not os.path.exists(path):
        return
    keep_dir = os.path.join(os.path.dirname(path), "_original")
    keep = os.path.join(keep_dir, os.path.basename(path))
    if not os.path.exists(keep):
        os.makedirs(keep_dir, exist_ok=True)
        shutil.copy2(path, keep)


def after_import(context, armature, weapon):
    """Tag the rig, read the QC's activities, build handles, show animation 1."""
    armature["slvm_weapon"] = weapon
    qc = os.path.join(mod_dir(), "Blender", weapon, weapon + "_anims.qc")
    seqs = smd_io.parse_sequences(qc)
    meta = read_meta(armature)
    for slot in slots_of(armature):
        info = seqs.get(slot.name_display)
        if info and slot.name_display not in meta:
            meta[slot.name_display] = {k: info[k] for k in ("fps", "activity", "weight", "loop")}
    write_meta(armature, meta)
    armature.show_in_front = True
    for obj in context.selected_objects:
        obj.select_set(False)
    armature.select_set(True)
    context.view_layer.objects.active = armature
    rig.build(context.scene, quiet=True)
    rig.start_watch()
    context.scene.slvm.anim_index = 0
    select_animation(context, 0)


# --------------------------------------------------------------------------
# step 1: load
# --------------------------------------------------------------------------
class SLVM_OT_load(bpy.types.Operator):
    """Clear the scene and load the chosen weapon with all its animations"""

    bl_idname = "slvm.load"
    bl_label = "Load weapon"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        if any(o.type in {"ARMATURE", "MESH"} for o in context.scene.objects):
            return context.window_manager.invoke_confirm(self, event, title="Load weapon",
                                                         message="This clears the scene. Save first if you need it.")
        return self.execute(context)

    def execute(self, context):
        weapon = context.scene.slvm.weapon
        if weapon == "NONE":
            self.report({"ERROR"}, "No weapons found: set the mod folder in the add-on preferences")
            return {"CANCELLED"}
        qc = os.path.join(mod_dir(), "Blender", weapon, weapon + "_anims.qc")
        if not hasattr(bpy.ops.import_scene, "smd"):
            self.report({"ERROR"}, "Enable Blender Source Tools (Edit > Preferences > Add-ons)")
            return {"CANCELLED"}
        rig.stop_watch()
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for obj in list(context.scene.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        for action in list(bpy.data.actions):
            if action.users == 0 or action.use_fake_user:
                action.use_fake_user = False
                if action.users == 0:
                    bpy.data.actions.remove(action)
        before = set(bpy.data.objects)
        bpy.ops.import_scene.smd(filepath=qc)
        armature = next((o for o in bpy.data.objects if o not in before and o.type == "ARMATURE"), None)
        if armature is None:
            self.report({"ERROR"}, "The import made no armature; see the console")
            return {"CANCELLED"}
        after_import(context, armature, weapon)
        rig.first_person_camera(context.scene)
        self.report({"INFO"}, "%s: %d animations" % (weapon, len(slots_of(armature))))
        return {"FINISHED"}


# --------------------------------------------------------------------------
# step 2: animations
# --------------------------------------------------------------------------
class SLVM_UL_animations(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        armature = current_armature(context)
        meta = read_meta(armature)
        info = meta.get(item.name_display, {})
        lo, hi = anim_range(armature, item)
        row = layout.row(align=True)
        row.label(text="%d." % (index + 1))
        row.label(text=item.name_display, icon="ACTION")
        act = info.get("activity", "")
        row.label(text=act.replace("ACT_VM_", "") if act else "-")
        row.label(text="%d fr" % (hi - lo + 1))


def _slot_index(armature, slot):
    for i, s in enumerate(slots_of(armature)):
        if s == slot:
            return i
    return 0


class SLVM_OT_anim_step(bpy.types.Operator):
    """Go to the previous / next animation"""

    bl_idname = "slvm.anim_step"
    bl_label = "Previous / next animation"

    step: IntProperty(default=1)

    def execute(self, context):
        armature = current_armature(context)
        n = len(slots_of(armature))
        if n:
            context.scene.slvm.anim_index = (context.scene.slvm.anim_index + self.step) % n
        return {"FINISHED"}


class SLVM_OT_anim_new(bpy.types.Operator):
    """Make a new animation"""

    bl_idname = "slvm.anim_new"
    bl_label = "New animation"
    bl_options = {"REGISTER", "UNDO"}

    name: StringProperty(name="Name", default="anim")
    start: EnumProperty(name="Start from", items=(
        ("COPY", "A copy of the current animation", "Every key of the selected animation"),
        ("POSE", "Its first frame only", "One key; set the length below"),
    ), default="COPY")
    length: IntProperty(name="Length (frames)", default=30, min=1)

    def invoke(self, context, event):
        armature = current_armature(context)
        slot = current_slot(armature)
        base = clean_name(slot.name_display if slot else "anim")
        names = {s.name_display for s in slots_of(armature)}
        n = 2
        while "%s_%d" % (base, n) in names:
            n += 1
        self.name = "%s_%d" % (base, n)
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "name")
        col.prop(self, "start")
        if self.start == "POSE":
            col.prop(self, "length")

    def execute(self, context):
        armature = current_armature(context)
        action = action_of(armature)
        src = current_slot(armature)
        if action is None or src is None:
            self.report({"ERROR"}, "Load a weapon first")
            return {"CANCELLED"}
        name = clean_name(self.name)
        if name in {s.name_display for s in action.slots}:
            self.report({"ERROR"}, "There is already an animation called %s" % name)
            return {"CANCELLED"}
        lo, hi = anim_range(armature, src)
        slot = action.slots.new(id_type="OBJECT", name=name)
        src_cb = channelbag(action, src)
        dst_cb = channelbag(action, slot, ensure=True)
        groups = {}
        if src_cb is not None:
            for fc in src_cb.fcurves:
                points = fc.keyframe_points
                if not len(points):
                    continue
                new = dst_cb.fcurves.new(fc.data_path, index=fc.array_index)
                if fc.group is not None:
                    g = groups.get(fc.group.name) or dst_cb.groups.new(fc.group.name)
                    groups[fc.group.name] = g
                    new.group = g
                if self.start == "COPY":
                    co = [0.0] * (2 * len(points))
                    points.foreach_get("co", co)
                    new.keyframe_points.add(len(points))
                    new.keyframe_points.foreach_set("co", co)
                    for a, b in zip(points, new.keyframe_points):
                        b.interpolation = a.interpolation
                else:
                    new.keyframe_points.add(1)
                    new.keyframe_points[0].co = (lo, fc.evaluate(lo))
                new.update()
        meta = read_meta(armature)
        info = dict(meta.get(src.name_display, {"fps": 30.0}))
        info["activity"] = ""  # a new animation plays only once you give it one
        if self.start == "POSE":
            info["end"] = lo + self.length - 1
            info["loop"] = False
        meta[name] = info
        write_meta(armature, meta)
        context.scene.slvm.anim_index = _slot_index(armature, slot)
        self.report({"INFO"}, "Animation %d: %s" % (context.scene.slvm.anim_index + 1, name))
        return {"FINISHED"}


class SLVM_OT_anim_rename(bpy.types.Operator):
    """Rename the selected animation (the name is the sequence name in the game)"""

    bl_idname = "slvm.anim_rename"
    bl_label = "Rename animation"
    bl_options = {"REGISTER", "UNDO"}

    name: StringProperty(name="Name")

    def invoke(self, context, event):
        slot = current_slot(current_armature(context))
        if slot is None:
            return {"CANCELLED"}
        self.name = slot.name_display
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        armature = current_armature(context)
        slot = current_slot(armature)
        old, new = slot.name_display, clean_name(self.name)
        if new == old:
            return {"CANCELLED"}
        if new in {s.name_display for s in slots_of(armature)}:
            self.report({"ERROR"}, "There is already an animation called %s" % new)
            return {"CANCELLED"}
        slot.name_display = new
        meta = read_meta(armature)
        if old in meta:
            meta[new] = meta.pop(old)
        write_meta(armature, meta)
        return {"FINISHED"}


class SLVM_OT_anim_delete(bpy.types.Operator):
    """Delete the selected animation from this file (its exported .smd stays on disk)"""

    bl_idname = "slvm.anim_delete"
    bl_label = "Delete animation"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        slot = current_slot(current_armature(context))
        if slot is None:
            return {"CANCELLED"}
        return context.window_manager.invoke_confirm(self, event, title="Delete animation",
                                                     message="Delete %s?" % slot.name_display)

    def execute(self, context):
        armature = current_armature(context)
        action, slot = action_of(armature), current_slot(armature)
        if len(action.slots) <= 1:
            self.report({"ERROR"}, "Can't delete the last animation")
            return {"CANCELLED"}
        name = slot.name_display
        index = _slot_index(armature, slot)
        action.slots.remove(slot)
        meta = read_meta(armature)
        meta.pop(name, None)
        write_meta(armature, meta)
        context.scene.slvm.anim_index = max(0, index - 1)
        select_animation(context, context.scene.slvm.anim_index)
        return {"FINISHED"}


class SLVM_OT_anim_length(bpy.types.Operator):
    """Set how long the selected animation is"""

    bl_idname = "slvm.anim_length"
    bl_label = "Set length"
    bl_options = {"REGISTER", "UNDO"}

    frames: IntProperty(name="Frames", default=30, min=1)

    def invoke(self, context, event):
        armature = current_armature(context)
        lo, hi = anim_range(armature, current_slot(armature))
        self.frames = hi - lo + 1
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        armature = current_armature(context)
        slot = current_slot(armature)
        lo, _hi = key_range(action_of(armature), slot)
        meta = read_meta(armature)
        meta.setdefault(slot.name_display, {})["end"] = lo + self.frames - 1
        write_meta(armature, meta)
        context.scene.frame_start, context.scene.frame_end = lo, lo + self.frames - 1
        return {"FINISHED"}


# --------------------------------------------------------------------------
# step 4: export and compile
# --------------------------------------------------------------------------
def export_animations(context, armature, slots, log):
    weapon = weapon_of(armature)
    out_dir = anims_dir(weapon)
    os.makedirs(out_dir, exist_ok=True)
    ad = armature.animation_data
    keep_slot = ad.action_slot
    rig._DRAGGING[0] = True  # keep the live IK sync out of the frame scrubbing
    written = []
    try:
        for slot in slots:
            ad.action_slot = slot
            lo, hi = anim_range(armature, slot)
            path = os.path.join(out_dir, slot.name_display + ".smd")
            keep_original(path)
            n = smd_io.write_animation(armature, path, lo, hi)
            written.append((slot.name_display, n))
            log("%s: %d frames" % (slot.name_display, n))
    finally:
        ad.action_slot = keep_slot
        rig._DRAGGING[0] = False
        rig._LAST.clear()
    qc = os.path.join(mod_dir(), "Blender", weapon, weapon + "_anims.qc")
    keep_original(qc)
    smd_io.write_test_qc(qc, sequences_in_order(armature))
    return written


class SLVM_OT_export(bpy.types.Operator):
    """Write the animation(s) to Blender/<weapon>/anims as .smd files"""

    bl_idname = "slvm.export"
    bl_label = "Export animations"

    which: EnumProperty(items=(("CURRENT", "This animation", ""), ("ALL", "All animations", "")), default="CURRENT")

    def execute(self, context):
        armature = current_armature(context)
        if not weapon_of(armature):
            self.report({"ERROR"}, "Load a weapon with step 1 first")
            return {"CANCELLED"}
        slots = [current_slot(armature)] if self.which == "CURRENT" else slots_of(armature)
        written = export_animations(context, armature, slots, print)
        self.report({"INFO"}, "Exported %s" % ", ".join(n for n, _f in written))
        return {"FINISHED"}


class SLVM_OT_export_mesh(bpy.types.Operator):
    """Write the mesh and bind pose (ref.smd): needed after adding gun-part bones"""

    bl_idname = "slvm.export_mesh"
    bl_label = "Export mesh"

    def execute(self, context):
        armature = current_armature(context)
        weapon = weapon_of(armature)
        if not weapon:
            self.report({"ERROR"}, "Load a weapon with step 1 first")
            return {"CANCELLED"}
        meshes = [o for o in context.scene.objects if o.type == "MESH"
                  and any(m.type == "ARMATURE" and m.object == armature for m in o.modifiers)]
        ref = os.path.join(anims_dir(weapon), "ref.smd")
        keep_original(ref)
        smd_io.write_reference(armature, meshes, ref, markers=True)
        msg = "Wrote Blender/%s/anims/ref.smd" % weapon
        if context.scene.slvm.ship_mesh:
            ship = os.path.join(mod_dir(), "modelsrc", weapon, weapon + "_ref.smd")
            if os.path.isdir(os.path.dirname(ship)):
                keep_original(ship)
                smd_io.write_reference(armature, meshes, ship, markers=False)
                msg += " and modelsrc/%s/%s_ref.smd" % (weapon, weapon)
        self.report({"INFO"}, msg)
        return {"FINISHED"}


def run_studiomdl(qc):
    p = prefs()
    exe = bpy.path.abspath(p.studiomdl)
    if not os.path.exists(exe):
        return False, "studiomdl.exe not found at %s (set it in the add-on preferences)" % exe
    cmd = ([p.wine] if p.wine.strip() else []) + [exe, "-nop4", "-game", mod_dir(), qc]
    try:
        result = subprocess.run(cmd, cwd=os.path.dirname(qc), capture_output=True, text=True, timeout=900)
    except (OSError, subprocess.TimeoutExpired) as ex:
        return False, str(ex)
    text = (result.stdout or "") + (result.stderr or "")
    log = bpy.data.texts.get("studiomdl.log") or bpy.data.texts.new("studiomdl.log")
    log.clear()
    log.write("$ %s\n\n%s" % (" ".join(cmd), text))
    ok = result.returncode == 0 and not any(l.lstrip().upper().startswith("ERROR") for l in text.splitlines())
    if ok:
        return True, "Compiled %s" % os.path.basename(qc)
    errors = [l for l in text.splitlines() if "error" in l.lower()]
    return False, (errors[-1] if errors else "studiomdl failed") + "  (full log: Text Editor > studiomdl.log)"


class SLVM_OT_compile(bpy.types.Operator):
    """Export every animation and compile: a test model, or the one the game uses"""

    bl_idname = "slvm.compile"
    bl_label = "Compile"

    target: EnumProperty(items=(
        ("TEST", "Test model", "models/sl_animtest/<weapon>.mdl; the game's model is untouched"),
        ("GAME", "Game model", "models/weapons/<weapon>.mdl, using your animations instead of the stock ones"),
    ), default="TEST")

    def invoke(self, context, event):
        if self.target == "GAME":
            return context.window_manager.invoke_confirm(
                self, event, title="Compile the game model",
                message="The game model will use these animations instead of the stock ones. Continue?")
        return self.execute(context)

    def execute(self, context):
        armature = current_armature(context)
        weapon = weapon_of(armature)
        if not weapon:
            self.report({"ERROR"}, "Load a weapon with step 1 first")
            return {"CANCELLED"}
        exe = bpy.path.abspath(prefs().studiomdl)
        if not os.path.exists(exe):
            self.report({"ERROR"}, "studiomdl.exe not found at %s (set it in the add-on preferences)" % exe)
            return {"CANCELLED"}
        export_animations(context, armature, slots_of(armature), print)
        if self.target == "TEST":
            qc = os.path.join(mod_dir(), "Blender", weapon, weapon + "_anims.qc")
        else:
            qc = os.path.join(mod_dir(), "modelsrc", weapon, weapon + ".qc")
            if not os.path.exists(qc):
                self.report({"ERROR"}, "No shipping QC at modelsrc/%s/%s.qc" % (weapon, weapon))
                return {"CANCELLED"}
            qci_name = weapon + "_anims.qci"
            smd_io.write_shipping_qci(os.path.join(os.path.dirname(qc), qci_name), weapon, sequences_in_order(armature))
            keep_original(qc)
            smd_io.use_qci_in_shipping_qc(qc, qci_name)
        ok, msg = run_studiomdl(qc)
        self.report({"INFO"} if ok else {"ERROR"}, msg)
        return {"FINISHED"} if ok else {"CANCELLED"}


class SLVM_OT_show_log(bpy.types.Operator):
    """Open the last studiomdl output in a Text Editor window"""

    bl_idname = "slvm.show_log"
    bl_label = "Show compile log"

    def execute(self, context):
        log = bpy.data.texts.get("studiomdl.log")
        if log is None:
            self.report({"INFO"}, "Nothing compiled yet")
            return {"CANCELLED"}
        bpy.ops.wm.window_new()
        area = context.window_manager.windows[-1].screen.areas[0]
        area.type = "TEXT_EDITOR"
        area.spaces.active.text = log
        return {"FINISHED"}


# --------------------------------------------------------------------------
# panels
# --------------------------------------------------------------------------
class _Panel:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Viewmodel"


class SLVM_PT_weapon(_Panel, bpy.types.Panel):
    bl_label = "1  Weapon"
    bl_order = 1

    def draw(self, context):
        layout = self.layout
        s = context.scene.slvm
        layout.prop(s, "weapon", text="")
        layout.operator(SLVM_OT_load.bl_idname, icon="IMPORT")
        armature = current_armature(context)
        if weapon_of(armature):
            layout.label(text="Loaded: %s, %d bones" % (weapon_of(armature), len(armature.data.bones)), icon="CHECKMARK")


class SLVM_PT_animations(_Panel, bpy.types.Panel):
    bl_label = "2  Animations"
    bl_order = 2

    def draw(self, context):
        layout = self.layout
        armature = current_armature(context)
        action = action_of(armature)
        if action is None:
            layout.label(text="Load a weapon first (step 1)")
            return
        s = context.scene.slvm
        row = layout.row()
        row.template_list("SLVM_UL_animations", "", action, "slots", s, "anim_index", rows=8)
        col = row.column(align=True)
        col.operator(SLVM_OT_anim_new.bl_idname, text="", icon="ADD")
        col.operator(SLVM_OT_anim_delete.bl_idname, text="", icon="REMOVE")
        col.separator()
        col.operator(SLVM_OT_anim_rename.bl_idname, text="", icon="GREASEPENCIL")
        col.separator()
        col.operator(SLVM_OT_anim_step.bl_idname, text="", icon="TRIA_UP").step = -1
        col.operator(SLVM_OT_anim_step.bl_idname, text="", icon="TRIA_DOWN").step = 1

        slot = current_slot(armature)
        if slot is None:
            return
        box = layout.box()
        lo, hi = anim_range(armature, slot)
        box.label(text="%d.  %s   (frames %d-%d)" % (_slot_index(armature, slot) + 1, slot.name_display, lo, hi), icon="ACTION")
        box.prop(s, "activity")
        row = box.row(align=True)
        row.prop(s, "weight")
        row.prop(s, "fps")
        row.prop(s, "loop", toggle=True)
        row = box.row(align=True)
        row.operator("screen.animation_play", text="Play", icon="PLAY")
        row.operator(SLVM_OT_anim_length.bl_idname, icon="TIME")
        row.operator("view3d.view_camera", text="Eye view", icon="CAMERA_DATA")


class SLVM_PT_save(_Panel, bpy.types.Panel):
    bl_label = "4  Save and test"
    bl_order = 4

    def draw(self, context):
        layout = self.layout
        s = context.scene.slvm
        col = layout.column(align=True)
        col.label(text="Export to Blender/<weapon>/anims:")
        row = col.row(align=True)
        row.operator(SLVM_OT_export.bl_idname, text="This animation", icon="EXPORT").which = "CURRENT"
        row.operator(SLVM_OT_export.bl_idname, text="All", icon="EXPORT").which = "ALL"
        col.separator()
        col.operator(SLVM_OT_export_mesh.bl_idname, text="Export mesh (after new gun parts)", icon="MESH_DATA")
        col.prop(s, "ship_mesh")
        col.separator()
        col.label(text="Compile (exports everything first):")
        row = col.row(align=True)
        row.operator(SLVM_OT_compile.bl_idname, text="Test model", icon="PLAY").target = "TEST"
        row.operator(SLVM_OT_compile.bl_idname, text="Game model", icon="FILE_TICK").target = "GAME"
        col.operator(SLVM_OT_show_log.bl_idname, icon="TEXT")


CLASSES = (
    SLVM_Preferences,
    SLVM_Settings,
    SLVM_OT_load,
    SLVM_UL_animations,
    SLVM_OT_anim_step,
    SLVM_OT_anim_new,
    SLVM_OT_anim_rename,
    SLVM_OT_anim_delete,
    SLVM_OT_anim_length,
    SLVM_OT_export,
    SLVM_OT_export_mesh,
    SLVM_OT_compile,
    SLVM_OT_show_log,
    SLVM_PT_weapon,
    SLVM_PT_animations,
    SLVM_PT_save,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.slvm = PointerProperty(type=SLVM_Settings)
    rig.register_ui()


def unregister():
    rig.unregister_ui()
    del bpy.types.Scene.slvm
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
