"""Give an imported viewmodel a first-person camera and IK hand handles.

Run this inside Blender after importing one of the generated QCs
(Blender/<weapon>/<weapon>_anims.qc):

    Scripting workspace -> Python Console -> paste:
        exec(open("<mod>/tools/viewmodel_ik_rig.py").read())

Then, in the 3D viewport, press N and use the "Viewmodel" tab:

* Viewmodel_Camera is placed at the player's eye; NumPad 0 (View > Cameras >
  Active Camera) is the first person view.
* IK_<hand> empties sit on each wrist. Move one with G and the arm follows.
  Handles key the arm bones as they move, and snap back onto the wrist when the
  animation moves the arm instead.
* "Solve to handles" puts the wrists on the handles without dragging, and
  "Key this pose" keys the arm at the current frame. The panel also shows the
  live wrist-to-handle gap, so you can see whether the solver is keeping up.

Why not a Blender IK constraint (and why Auto IK cannot work here)?
Blender Source Tools imports SMD bones as 0.2-unit stubs whose axes are
*perpendicular* to the limb -- measured at exactly 90.0 degrees on every bone of
this skeleton. A bone constraint or Blender's solver orients the bone's own Y
axis, so with perpendicular axes it drives the limb in the wrong direction; the
built-in IK misses the target by many units. Longthening the tails is safe (bone
length is not part of the rest matrix, so the export is unchanged), but turning
the axes to face along the limb would rewrite every bone's rest rotation, and the
model has to keep HL2's v_357 skeleton orientation because its animations come
from $includemodel.

So the two bone IK is solved directly here: rotate the upper arm to place the
elbow, rotate the forearm to place the wrist, writing pose matrices in closed
form (no dependency graph evaluation in the middle, so an assigned action cannot
overwrite the solve). Only bone rotations are written, which is exactly what
studiomdl reads back.
"""
import math

import bpy
from mathutils import Matrix, Vector

# Horizontal field of view of the first person camera. 90 matches the world
# camera (fov_desired 90 in cfg/config.cfg); the engine's viewmodel pass draws
# the weapon narrower, at viewmodel_fov 54, so lower this if you want the
# exact in-game framing.
VIEWMODEL_FOV = 90.0

CAMERA_NAME = "Viewmodel_Camera"
COLLECTION_NAME = "Viewmodel_Rig"
HANDLE_PREFIX = "IK_"
ARMATURE_PROP = "viewmodel_armature"

# How often the timer looks at the handles, in seconds. The depsgraph handler
# also runs, so this only matters when nothing is redrawing.
WATCH_INTERVAL = 0.05


# --------------------------------------------------------------------------
# rig pieces
# --------------------------------------------------------------------------
def rig_collection(scene):
    collection = bpy.data.collections.get(COLLECTION_NAME)
    if collection is None:
        collection = bpy.data.collections.new(COLLECTION_NAME)
    if collection.name not in scene.collection.children:
        scene.collection.children.link(collection)
    return collection


def first_person_camera(scene):
    """Camera at the eye, aimed along the model's -Y axis with +Z up."""
    collection = rig_collection(scene)
    camera = bpy.data.objects.get(CAMERA_NAME)
    if camera is None:
        camera = bpy.data.objects.new(CAMERA_NAME, bpy.data.cameras.new(CAMERA_NAME))
    for existing in list(camera.users_collection):
        existing.objects.unlink(camera)
    collection.objects.link(camera)

    data = camera.data
    data.type = "PERSP"
    data.sensor_fit = "HORIZONTAL"
    data.angle = math.radians(VIEWMODEL_FOV)
    data.clip_start = 0.1
    data.clip_end = 4096.0

    # Model space is the engine's view space rotated -90 degrees about Z: the
    # weapon points down -Y here. So: right = -X, up = +Z, back = +Y.
    camera.matrix_world = Matrix(
        (
            (-1.0, 0.0, 0.0, 0.0),
            (0.0, 0.0, 1.0, 0.0),
            (0.0, 1.0, 0.0, 0.0),
            (0.0, 0.0, 0.0, 1.0),
        )
    )
    scene.camera = camera
    return camera


def arm_chains(armature):
    """(upper arm, forearm, hand) bone name triples, found by name."""
    for bone in armature.data.bones:
        if "control" in bone.name.lower():
            continue
        chain = [bone]
        parent = bone.parent
        while parent is not None and len(chain) < 3:
            chain.append(parent)
            parent = parent.parent
        if len(chain) == 3 and "forearm" in chain[1].name.lower():
            yield chain[2].name, chain[1].name, chain[0].name


def hand_handles(armature, collection):
    """One empty per arm chain, sitting on the wrist (hand bone head)."""
    handles = []
    for upper, forearm, hand in arm_chains(armature):
        empty = bpy.data.objects.get(HANDLE_PREFIX + hand)
        if empty is None:
            empty = bpy.data.objects.new(HANDLE_PREFIX + hand, None)
        for existing in list(empty.users_collection):
            existing.objects.unlink(empty)
        collection.objects.link(empty)
        empty.empty_display_type = "SPHERE"
        empty.empty_display_size = 2.0
        empty.hide_select = False
        empty.show_in_front = True
        empty.location = armature.matrix_world @ armature.pose.bones[hand].head

        # Record what this handle drives so the triggers work from the empty.
        empty[ARMATURE_PROP] = armature.name
        empty["viewmodel_upper"] = upper
        empty["viewmodel_forearm"] = forearm
        empty["viewmodel_hand"] = hand
        handles.append(empty)
    return handles


# --------------------------------------------------------------------------
# two bone IK
# --------------------------------------------------------------------------
def _basis_from_pose(bone, pose_matrix, parent_pose):
    """matrix_basis that puts `bone` at `pose_matrix` (armature space)."""
    rest = bone.bone.matrix_local
    if bone.parent is not None:
        rest = bone.parent.bone.matrix_local.inverted() @ rest
        parent_pose = parent_pose if parent_pose is not None else bone.parent.matrix
    else:
        parent_pose = Matrix.Identity(4)
    return (parent_pose @ rest).inverted() @ pose_matrix


def solve_chain(armature, upper, forearm, hand, target_world):
    """Two bone IK: put the wrist on target_world by rotating two bones.

    Joint positions come from the current pose, so the perpendicular bone stubs
    the importer leaves behind do not matter -- the limb vectors between joint
    heads are the real ones. Both rotations are computed before either is
    written, and written as matrix_basis, so no dependency graph evaluation
    happens in the middle and an assigned action cannot undo the solve.

    Returns the residual distance between the wrist and the target.
    """
    to_local = armature.matrix_world.inverted()
    target = to_local @ target_world

    pose = armature.pose.bones
    upper_bone, forearm_bone, hand_bone = pose[upper], pose[forearm], pose[hand]

    m_upper = upper_bone.matrix.copy()
    m_forearm = forearm_bone.matrix.copy()
    m_hand = hand_bone.matrix.copy()

    shoulder = m_upper.translation.copy()
    elbow = m_forearm.translation.copy()
    wrist = m_hand.translation.copy()

    a = (elbow - shoulder).length  # upper arm reach
    b = (wrist - elbow).length  # forearm reach
    if a < 1e-5 or b < 1e-5:
        return (wrist - target).length

    reach = a + b
    distance = (target - shoulder).length
    # stay just inside full extension, where the solver is well behaved
    distance = min(max(distance, abs(a - b) + 1e-3), reach - 1e-3)
    offset = target - shoulder
    if offset.length < 1e-6:
        return (wrist - target).length
    axis = offset.normalized()

    # Keep the elbow in the plane it is currently bending in.
    bend = (elbow - shoulder) - axis * ((elbow - shoulder).dot(axis))
    if bend.length < 1e-4:
        bend = axis.cross(Vector((0.0, 0.0, 1.0)))
        if bend.length < 1e-4:
            bend = axis.cross(Vector((0.0, 1.0, 0.0)))
    bend.normalize()

    along = (a * a - b * b + distance * distance) / (2.0 * distance)
    height = math.sqrt(max(a * a - along * along, 0.0))
    elbow_target = shoulder + axis * along + bend * height

    # upper arm: swing the shoulder->elbow vector onto the new elbow
    swing_upper = (elbow - shoulder).normalized().rotation_difference(
        (elbow_target - shoulder).normalized()
    )
    around_shoulder = (
        Matrix.Translation(shoulder) @ swing_upper.to_matrix().to_4x4() @ Matrix.Translation(-shoulder)
    )
    new_upper = around_shoulder @ m_upper
    new_forearm = around_shoulder @ m_forearm
    new_hand = around_shoulder @ m_hand

    # forearm: swing the elbow->wrist vector onto the target
    elbow_now = new_forearm.translation.copy()
    wrist_now = new_hand.translation.copy()
    swing_forearm = (wrist_now - elbow_now).normalized().rotation_difference(
        (target - elbow_now).normalized()
    )
    around_elbow = (
        Matrix.Translation(elbow_now) @ swing_forearm.to_matrix().to_4x4() @ Matrix.Translation(-elbow_now)
    )
    new_forearm = around_elbow @ new_forearm
    new_hand = around_elbow @ new_hand

    parent_pose = upper_bone.parent.matrix if upper_bone.parent is not None else None
    upper_bone.matrix_basis = _basis_from_pose(upper_bone, new_upper, parent_pose)
    forearm_bone.matrix_basis = _basis_from_pose(forearm_bone, new_forearm, new_upper)

    return (new_hand.translation - target).length


def wrist_position(armature, hand):
    return (armature.matrix_world @ armature.pose.bones[hand].head).copy()


def key_bones(armature, upper, forearm):
    """Key the driven bones, otherwise the pose is lost on the next export.

    Location is keyed as well as rotation: the imported pose carries a small
    location offset on the upper arm (Blender Source Tools writes it from the
    SMD joint offset), and dropping it pulls the wrist a fraction of a unit off
    the handle.

    The rotation channel follows the bone's mode: animated skeletons import in
    Euler XYZ, but keying the wrong channel would write curves the rig never
    evaluates.
    """
    frame = bpy.context.scene.frame_current
    for name in (upper, forearm):
        bone = armature.pose.bones[name]
        channel = "rotation_quaternion" if bone.rotation_mode == "QUATERNION" else "rotation_euler"
        bone.keyframe_insert(channel, frame=frame)
        bone.keyframe_insert("location", frame=frame)


# --------------------------------------------------------------------------
# handles
# --------------------------------------------------------------------------
def handle_position(empty):
    """World position of a handle.

    The handles are created unparented, so their location *is* the world
    position and reading it avoids the stale matrix_world you get between a
    change and the next dependency graph evaluation.
    """
    if empty.parent is None:
        return empty.location.copy()
    return empty.matrix_world.translation.copy()


def set_handle_position(empty, position):
    if empty.parent is None:
        empty.location = position
    else:
        empty.matrix_world.translation = position


def handle_of(empty):
    armature = bpy.data.objects.get(empty.get(ARMATURE_PROP, ""))
    if armature is None or armature.type != "ARMATURE":
        return None
    names = (empty.get("viewmodel_upper"), empty.get("viewmodel_forearm"), empty.get("viewmodel_hand"))
    if not all(names):
        return None
    return (armature,) + names


def handles():
    for obj in bpy.data.objects:
        if obj.get(ARMATURE_PROP):
            chain = handle_of(obj)
            if chain:
                yield obj, chain


# last seen (handle position, wrist position) per handle, to tell "the user
# dragged the handle" from "the animation moved the arm"
_LAST = {}
_BUSY = [False]


def sync_handles(autokey=None):
    """Bring every arm onto its handle. Shared by the buttons and the triggers."""
    if _BUSY[0]:
        return 0
    _BUSY[0] = True
    solved = 0
    try:
        if autokey is None:
            autokey = getattr(bpy.context.scene, "viewmodel_ik_autokey", True)
        for empty, (armature, upper, forearm, hand) in handles():
            if armature.mode not in {"OBJECT", "POSE"}:
                continue
            wrist = wrist_position(armature, hand)
            position = handle_position(empty)
            previous = _LAST.get(empty.name)
            _LAST[empty.name] = (position, wrist)
            if previous is None:
                continue
            if (position - previous[0]).length > 1e-4:
                # the user moved the handle: drive the arm
                solve_chain(armature, upper, forearm, hand, position)
                if autokey:
                    key_bones(armature, upper, forearm)
                _LAST[empty.name] = (position, position)
                solved += 1
            elif (wrist - position).length > 0.02 and (wrist - previous[1]).length > 1e-4:
                # the arm moved instead (new frame, edited keys): bring the
                # handle along rather than fighting the animation
                set_handle_position(empty, wrist)
                _LAST[empty.name] = (wrist, wrist)
    finally:
        _BUSY[0] = False
    return solved


def solve_to_handles():
    """Put every wrist on its handle, ignoring where it was before."""
    _LAST.clear()
    solved = 0
    autokey = getattr(bpy.context.scene, "viewmodel_ik_autokey", True)
    for empty, (armature, upper, forearm, hand) in handles():
        if armature.mode not in {"OBJECT", "POSE"}:
            continue
        target = handle_position(empty)
        solve_chain(armature, upper, forearm, hand, target)
        if autokey:
            key_bones(armature, upper, forearm)
        _LAST[empty.name] = (target, target)
        solved += 1
    return solved


def report():
    """(handle name, wrist, gap) for the panel readout."""
    rows = []
    for empty, (armature, _upper, _forearm, hand) in handles():
        wrist = wrist_position(armature, hand)
        rows.append((empty.name, wrist, (wrist - handle_position(empty)).length))
    return rows


# --------------------------------------------------------------------------
# triggers
# --------------------------------------------------------------------------
def _on_depsgraph_update(scene, depsgraph=None):
    # Fires on every redraw and every drag step, so the arm tracks the handle
    # while you move it; the timer below covers the gaps.
    if getattr(bpy.context, "mode", "OBJECT") in {"EDIT_ARMATURE", "EDIT_MESH"}:
        return
    sync_handles()


def _tick():
    if not bpy.context.scene:
        return None
    try:
        sync_handles()
    except Exception as ex:  # never let a timer exception remove the watch
        print("viewmodel IK: %s" % ex)
    return WATCH_INTERVAL


def start_watch():
    from bpy.app.handlers import depsgraph_update_post, persistent

    @persistent
    def _handler(scene, depsgraph=None):
        _on_depsgraph_update(scene, depsgraph)

    _handler.__name__ = "viewmodel_ik_sync"
    stop_watch()
    depsgraph_update_post.append(_handler)
    globals()["_HANDLER"] = _handler
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=WATCH_INTERVAL)
    _LAST.clear()


def stop_watch():
    from bpy.app.handlers import depsgraph_update_post

    for handler in list(depsgraph_update_post):
        if getattr(handler, "__name__", "") == "viewmodel_ik_sync":
            depsgraph_update_post.remove(handler)
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    _LAST.clear()


# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------
class VIEWMODEL_OT_solve_now(bpy.types.Operator):
    """Put the wrists on their IK handles"""

    bl_idname = "viewmodel.solve_now"
    bl_label = "Solve to handles"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        count = solve_to_handles()
        if not count:
            self.report({"WARNING"}, "No IK handles in this file")
        context.view_layer.update()
        return {"FINISHED"}


class VIEWMODEL_OT_key_pose(bpy.types.Operator):
    """Keyframe the arm bones at the current frame"""

    bl_idname = "viewmodel.key_pose"
    bl_label = "Key this pose"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        for _empty, (armature, upper, forearm, _hand) in handles():
            key_bones(armature, upper, forearm)
        return {"FINISHED"}


class VIEWMODEL_OT_watch(bpy.types.Operator):
    """Turn the live handle sync on or off"""

    bl_idname = "viewmodel.watch"
    bl_label = "Toggle live sync"
    bl_options = {"REGISTER"}

    def execute(self, context):
        running = any(
            getattr(h, "__name__", "") == "viewmodel_ik_sync"
            for h in bpy.app.handlers.depsgraph_update_post
        )
        context.scene.viewmodel_ik_watching = not running
        if running:
            stop_watch()
        else:
            start_watch()
        return {"FINISHED"}


class VIEWMODEL_PT_panel(bpy.types.Panel):
    bl_label = "Viewmodel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Viewmodel"

    @classmethod
    def poll(cls, context):
        return context.scene is not None

    def draw(self, context):
        layout = self.layout
        found = list(handles())
        layout.label(text="Drag an IK_ handle: the arm follows.", icon="EMPTY_DATA")
        layout.operator(VIEWMODEL_OT_solve_now.bl_idname, icon="CON_ROTLIKE")
        layout.operator(VIEWMODEL_OT_key_pose.bl_idname, icon="KEYTYPE_KEYFRAME_VEC")
        layout.prop(context.scene, "viewmodel_ik_autokey")
        layout.operator(VIEWMODEL_OT_watch.bl_idname, icon="FILE_REFRESH")
        layout.operator("view3d.view_camera", text="Go to viewmodel camera", icon="CAMERA_DATA")
        if not found:
            layout.label(text="No handles - run the rig script again", icon="ERROR")
            return
        column = layout.column(align=True)
        for empty, (armature, upper, _forearm, hand) in found:
            wrist = wrist_position(armature, hand)
            gap = (wrist - handle_position(empty)).length
            column.label(text="%s  ->  %s" % (empty.name, upper))
            column.label(
                text="wrist to handle: %0.2f" % gap,
                icon="CHECKMARK" if gap < 0.05 else "ERROR",
            )


# --------------------------------------------------------------------------
def main():
    scene = bpy.context.scene
    camera = first_person_camera(scene)
    print("Viewmodel camera: %s, %.0f deg horizontal" % (camera.name, VIEWMODEL_FOV))

    selected = [o for o in bpy.context.selected_objects if o.type == "ARMATURE"]
    if not selected:
        active = bpy.context.view_layer.objects.active
        if active is not None and active.type == "ARMATURE":
            selected = [active]
    if not selected:
        selected = [o for o in scene.objects if o.type == "ARMATURE"]
    if not selected:
        print("! no armature in the scene - import a _anims.qc first")
        return 1

    collection = rig_collection(scene)
    total = 0
    for armature in selected:
        created = hand_handles(armature, collection)
        for empty in created:
            print("  %-28s drives %s / %s" % (empty.name, empty["viewmodel_upper"], empty["viewmodel_forearm"]))
        total += len(created)
        if not created:
            print("! %s: no upper-arm/forearm/hand chain found" % armature.name)

    if not hasattr(bpy.types.Scene, "viewmodel_ik_autokey"):
        bpy.types.Scene.viewmodel_ik_autokey = bpy.props.BoolProperty(
            name="Key while dragging",
            description="Keyframe the arm bones as the handle moves",
            default=True,
        )
    if not hasattr(bpy.types.Scene, "viewmodel_ik_watching"):
        bpy.types.Scene.viewmodel_ik_watching = bpy.props.BoolProperty(
            name="Live sync",
            description="Follow the handles as they move",
            default=True,
        )

    # Blender keeps classes registered for the whole session, so a second run of
    # this script has to replace the previous ones instead of adding duplicates.
    for name in ("VIEWMODEL_OT_solve_now", "VIEWMODEL_OT_key_pose", "VIEWMODEL_OT_watch", "VIEWMODEL_PT_panel"):
        old = getattr(bpy.types, name, None)
        if old is not None:
            try:
                bpy.utils.unregister_class(old)
            except Exception:
                pass
    for cls in (VIEWMODEL_OT_solve_now, VIEWMODEL_OT_key_pose, VIEWMODEL_OT_watch, VIEWMODEL_PT_panel):
        bpy.utils.register_class(cls)

    bpy.context.view_layer.update()
    scene.viewmodel_ik_watching = True
    start_watch()

    print("%d IK handle(s) ready: drag a handle to pose the arm." % total)
    print("N panel > Viewmodel tab has Solve / Key / camera buttons.")
    return 0


if __name__ == "__main__":
    main()
