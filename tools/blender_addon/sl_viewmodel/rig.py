"""Viewmodel rig: first-person camera, IK hands, fingers and gun parts.

Run this inside Blender after importing one of the generated QCs
(Blender/<weapon>/<weapon>_anims.qc):

    Scripting workspace -> Python Console -> paste:
        exec(open("<mod>/tools/viewmodel_ik_rig.py").read())

Then press N in the 3D viewport and open the "Viewmodel" tab.

Hands
  * One IK_<hand> handle per arm. Move it and the arm follows; ROTATE it and
    the hand (and whatever it holds) turns with it.
  * J over the viewport: grab the IK handle nearest the mouse and drag it.
    While dragging, R switches to turning the hand, G back to moving, X/Y/Z
    lock to an axis, Shift is fine control. Left click / Enter keeps the pose
    and keys it (one undo step), right click / Esc puts everything back.
  * Plain G/R on a selected handle also works (a dependency graph handler
    follows it), as does "Solve to handles".
  * "Elbow targets" adds a POLE_<hand> empty per two-bone arm; the elbow
    points at it.
  * Two-bone arms (upper arm, forearm, hand) are solved exactly. One-bone
    arms -- the deagle's right arm is a single `Arm` bone, elbow to wrist --
    aim at the handle and slide along their length to reach it.

Fingers
  * "Curl" / "Open" bend every finger of that hand around its knuckles,
    "Thumb" does the thumb; each press keys the fingers. Single finger
    bones are ordinary bones: select in pose mode and press R.

Gun parts
  * Every bone that is not an arm, finger or root is listed with a button that
    selects it in pose mode -- rotate/move it with R/G and key with I. A bone
    with no mesh on it moves nothing; give it a part:
  * "Part from selection": in Edit Mode on the mesh, select a part (L picks
    linked geometry), then this makes a new bone at its centre, parented to
    the bone the part is on now, and moves the selected vertices onto it.
  * "Bind selection" moves the selected vertices onto an existing bone.

Root bones are locked (studiomdl adds a 90 degree yaw to the root, so a
root edit lands rotated in game). Animate the weapon bone instead -- `Gun`
on the organic rifle, `Hand` on the deagle, the right hand on the wrench.

Why there is no Blender IK constraint: Blender Source Tools imports SMD bones
as short stubs whose axes are perpendicular to the limb (measured at 90.0
degrees on every stock bone), so a constraint or Auto IK, which bends a bone's
own Y axis, swings the limb sideways. The solve here only uses joint positions
and writes rotations, which is exactly what studiomdl reads back.
"""
import math

import bpy
import bmesh
from mathutils import Matrix, Quaternion, Vector

# Horizontal field of view of the first person camera. 90 matches the world
# camera (fov_desired 90); the engine draws the viewmodel at viewmodel_fov
# 54, so set 54 for the exact in-game framing.
VIEWMODEL_FOV = 90.0

CAMERA_NAME = "Viewmodel_Camera"
COLLECTION_NAME = "Viewmodel_Rig"
HANDLE_PREFIX = "IK_"
POLE_PREFIX = "POLE_"
ARMATURE_PROP = "viewmodel_armature"

# Arms made of a single bone from shoulder (or elbow) to wrist, as (arm, hand).
ONE_BONE_ARMS = (("Arm", "Hand"),)
# How far a one-bone arm may slide along itself to reach a handle.
MAX_SLIDE = 8.0

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
    camera.matrix_world = Matrix(((-1.0, 0.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0)))
    scene.camera = camera
    return camera


def is_finger(name):
    return "finger" in name.lower()


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


def chains(armature):
    """Every arm on this armature: ("two", upper, forearm, hand) or ("one", arm, hand)."""
    out = []
    used = set()
    for upper, forearm, hand in arm_chains(armature):
        out.append(("two", upper, forearm, hand))
        used.update((upper, forearm, hand))
    bones = armature.data.bones
    for arm, hand in ONE_BONE_ARMS:
        if arm in bones and hand in bones and bones[hand].parent == bones[arm] and arm not in used:
            out.append(("one", arm, hand))
    return out


class Chain:
    def __init__(self, armature, spec, orient=True):
        self.armature = armature
        self.kind = spec[0]
        self.bones = spec[1:]
        self.hand = spec[-1]
        self.orient = orient

    @property
    def keyed(self):
        return self.bones


def hand_world(armature, hand):
    m = armature.matrix_world @ armature.pose.bones[hand].matrix
    return m.translation.copy(), m.to_quaternion()


def make_handle(armature, chain, collection):
    name = HANDLE_PREFIX + chain.hand
    empty = bpy.data.objects.get(name)
    # keep where an existing handle of this rig was left (re-running the
    # script used to throw that away); older handles carry no rotation
    keep = empty is not None and empty.get(ARMATURE_PROP) == armature.name and bool(empty.get("viewmodel_kind"))
    if empty is None:
        empty = bpy.data.objects.new(name, None)
    for existing in list(empty.users_collection):
        existing.objects.unlink(empty)
    collection.objects.link(empty)
    empty.parent = None
    empty.empty_display_type = "SPHERE"
    empty.empty_display_size = 1.5
    empty.show_in_front = True
    empty.hide_select = False
    empty.rotation_mode = "QUATERNION"
    if not keep:
        # a new handle sits on the wrist, turned like the hand
        position, rotation = hand_world(armature, chain.hand)
        empty.location = position
        empty.rotation_quaternion = rotation
    empty[ARMATURE_PROP] = armature.name
    empty["viewmodel_kind"] = chain.kind
    empty["viewmodel_bones"] = "|".join(chain.bones)
    if "viewmodel_orient" not in empty:
        empty["viewmodel_orient"] = True
    return empty


def make_pole(armature, handle, collection):
    """Empty in front of the elbow; the elbow will point at it."""
    chain = chain_of(handle)
    if chain is None or chain.kind != "two":
        return None
    upper, forearm, hand = chain.bones
    pose = armature.pose.bones
    mw = armature.matrix_world
    shoulder = mw @ pose[upper].head
    elbow = mw @ pose[forearm].head
    wrist = mw @ pose[hand].head
    axis = (wrist - shoulder).normalized()
    bend = (elbow - shoulder) - axis * (elbow - shoulder).dot(axis)
    if bend.length < 1e-4:
        bend = Vector((0.0, 0.0, -1.0))
    name = POLE_PREFIX + hand
    pole = bpy.data.objects.get(name) or bpy.data.objects.new(name, None)
    for existing in list(pole.users_collection):
        existing.objects.unlink(pole)
    collection.objects.link(pole)
    pole.parent = None
    pole.empty_display_type = "CONE"
    pole.empty_display_size = 1.0
    pole.show_in_front = True
    pole.location = elbow + bend.normalized() * 8.0
    pole["viewmodel_pole_for"] = handle.name
    handle["viewmodel_pole"] = pole.name
    return pole


# --------------------------------------------------------------------------
# solving
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


def _around(point, rotation):
    return Matrix.Translation(point) @ rotation.to_matrix().to_4x4() @ Matrix.Translation(-point)


def _oriented(matrix, rotation):
    if rotation is None:
        return matrix
    return Matrix.Translation(matrix.translation) @ rotation.to_4x4()


def solve(chain, target_world, rotation_world=None, pole_world=None):
    """Put the wrist on target_world (and the hand at rotation_world).

    Joint positions come from the current pose, so the importer's
    perpendicular bone stubs don't matter. Every new pose matrix is computed
    before any is written, and written as matrix_basis, so no dependency
    graph evaluation happens in between.

    Returns (residual, wrist world position, hand world rotation).
    """
    armature = chain.armature
    mw = armature.matrix_world
    to_local = mw.inverted()
    target = to_local @ target_world
    rotation = None
    if rotation_world is not None and chain.orient:
        rotation = (to_local.to_3x3() @ rotation_world.to_matrix()).normalized()
    pose = armature.pose.bones

    if chain.kind == "two":
        upper, forearm, hand = (pose[n] for n in chain.bones)
        m_upper, m_forearm, m_hand = upper.matrix.copy(), forearm.matrix.copy(), hand.matrix.copy()
        shoulder, elbow, wrist = m_upper.translation.copy(), m_forearm.translation.copy(), m_hand.translation.copy()
        a = (elbow - shoulder).length
        b = (wrist - elbow).length
        offset = target - shoulder
        if a < 1e-5 or b < 1e-5 or offset.length < 1e-6:
            return (wrist - target).length, mw @ wrist, (mw @ m_hand).to_quaternion()
        distance = min(max(offset.length, abs(a - b) + 1e-3), a + b - 1e-3)
        axis = offset.normalized()
        if pole_world is not None:
            bend = (to_local @ pole_world) - shoulder
        else:
            bend = elbow - shoulder  # keep the plane it is bending in now
        bend = bend - axis * bend.dot(axis)
        if bend.length < 1e-4:
            bend = axis.cross(Vector((0.0, 0.0, 1.0)))
            if bend.length < 1e-4:
                bend = axis.cross(Vector((0.0, 1.0, 0.0)))
        bend.normalize()
        along = (a * a - b * b + distance * distance) / (2.0 * distance)
        height = math.sqrt(max(a * a - along * along, 0.0))
        elbow_target = shoulder + axis * along + bend * height

        swing = _around(shoulder, (elbow - shoulder).normalized().rotation_difference((elbow_target - shoulder).normalized()))
        new_upper, new_forearm, new_hand = swing @ m_upper, swing @ m_forearm, swing @ m_hand
        elbow_now, wrist_now = new_forearm.translation.copy(), new_hand.translation.copy()
        swing = _around(elbow_now, (wrist_now - elbow_now).normalized().rotation_difference((target - elbow_now).normalized()))
        new_forearm, new_hand = swing @ new_forearm, swing @ new_hand
        new_hand = _oriented(new_hand, rotation)

        parent_pose = upper.parent.matrix if upper.parent is not None else None
        upper.matrix_basis = _basis_from_pose(upper, new_upper, parent_pose)
        forearm.matrix_basis = _basis_from_pose(forearm, new_forearm, new_upper)
        hand.matrix_basis = _basis_from_pose(hand, new_hand, new_forearm)
    else:
        arm, hand = (pose[n] for n in chain.bones)
        m_arm, m_hand = arm.matrix.copy(), hand.matrix.copy()
        start, wrist = m_arm.translation.copy(), m_hand.translation.copy()
        length = (wrist - start).length
        offset = target - start
        if length < 1e-5 or offset.length < 1e-6:
            return (wrist - target).length, mw @ wrist, (mw @ m_hand).to_quaternion()
        direction = offset.normalized()
        slide = max(-MAX_SLIDE, min(MAX_SLIDE, offset.length - length))
        new_start = start + direction * slide
        aim = (wrist - start).normalized().rotation_difference(direction)
        move = Matrix.Translation(new_start) @ aim.to_matrix().to_4x4() @ Matrix.Translation(-start)
        new_arm, new_hand = move @ m_arm, move @ m_hand
        new_hand = _oriented(new_hand, rotation)
        parent_pose = arm.parent.matrix if arm.parent is not None else None
        arm.matrix_basis = _basis_from_pose(arm, new_arm, parent_pose)
        hand.matrix_basis = _basis_from_pose(hand, new_hand, new_arm)

    return (new_hand.translation - target).length, mw @ new_hand.translation, (mw @ new_hand).to_quaternion()


def key_bones(armature, names, frame=None):
    """Key location and rotation (in whichever channel each bone uses)."""
    frame = bpy.context.scene.frame_current if frame is None else frame
    for name in names:
        bone = armature.pose.bones[name]
        channel = "rotation_quaternion" if bone.rotation_mode == "QUATERNION" else "rotation_euler"
        bone.keyframe_insert(channel, frame=frame)
        bone.keyframe_insert("location", frame=frame)


# --------------------------------------------------------------------------
# handles
# --------------------------------------------------------------------------
def chain_of(empty):
    armature = bpy.data.objects.get(empty.get(ARMATURE_PROP, ""))
    if armature is None or armature.type != "ARMATURE":
        return None
    kind = empty.get("viewmodel_kind")
    bones = tuple(empty.get("viewmodel_bones", "").split("|"))
    if kind not in ("one", "two") or not all(b in armature.pose.bones for b in bones):
        return None
    return Chain(armature, (kind,) + bones, bool(empty.get("viewmodel_orient", True)))


def handles():
    for obj in bpy.data.objects:
        if obj.get(ARMATURE_PROP) and obj.get("viewmodel_kind"):
            chain = chain_of(obj)
            if chain:
                yield obj, chain


def pole_of(empty):
    pole = bpy.data.objects.get(empty.get("viewmodel_pole", ""))
    if pole is None or not empty.get("viewmodel_use_pole", True):
        return None
    return pole


def handle_state(empty):
    """World position and rotation of a handle (handles are unparented, so
    location/rotation are world values and never stale)."""
    if empty.parent is None:
        return empty.location.copy(), empty.rotation_quaternion.copy().normalized()
    m = empty.matrix_world
    return m.translation.copy(), m.to_quaternion()


def set_handle_state(empty, position, rotation):
    empty.location = position
    empty.rotation_quaternion = rotation


def pole_position(empty):
    pole = pole_of(empty)
    return pole.location.copy() if pole is not None else None


def solve_handle(empty, chain, autokey):
    position, rotation = handle_state(empty)
    residual, wrist, hand_rotation = solve(chain, position, rotation, pole_position(empty))
    if autokey:
        key_bones(chain.armature, chain.keyed)
    return residual, wrist, hand_rotation


def _angle(q1, q2):
    return q1.rotation_difference(q2).angle


# last seen (handle position, handle rotation, wrist, hand rotation, pole)
_LAST = {}
_BUSY = [False]
_DRAGGING = [False]


def sync_handles(autokey=None, fresh=True):
    """Bring every arm onto its handle. Shared by the buttons and the triggers.

    fresh=False (the timer) only reacts to a handle that moved: pose matrices
    read from a timer can be one evaluation behind, so a timer must never
    decide that "the arm moved".
    """
    if _BUSY[0] or _DRAGGING[0]:
        return 0
    _BUSY[0] = True
    solved = 0
    try:
        if autokey is None:
            autokey = getattr(bpy.context.scene, "viewmodel_ik_autokey", True)
        for empty, chain in handles():
            if chain.armature.mode not in {"OBJECT", "POSE"}:
                continue
            position, rotation = handle_state(empty)
            pole = pole_position(empty)
            wrist, hand_rotation = hand_world(chain.armature, chain.hand)
            previous = _LAST.get(empty.name)
            if previous is None:
                _LAST[empty.name] = (position, rotation, wrist, hand_rotation, pole)
                continue
            moved = (position - previous[0]).length > 1e-4 or _angle(rotation, previous[1]) > 1e-4
            if pole is not None and previous[4] is not None and (pole - previous[4]).length > 1e-4:
                moved = True
            if moved:
                _residual, wrist, hand_rotation = solve_handle(empty, chain, autokey)
                _LAST[empty.name] = (position, rotation, wrist, hand_rotation, pole)
                solved += 1
            elif fresh and ((wrist - previous[2]).length > 1e-4 or _angle(hand_rotation, previous[3]) > 1e-4):
                # the animation moved the arm (frame change, edited keys):
                # bring the handle along instead of fighting it
                set_handle_state(empty, wrist, hand_rotation if chain.orient else rotation)
                _LAST[empty.name] = (wrist, hand_rotation if chain.orient else rotation, wrist, hand_rotation, pole)
            else:
                _LAST[empty.name] = (position, rotation, previous[2], previous[3], pole)
    finally:
        _BUSY[0] = False
    return solved


def snap_handles_to_hands():
    for empty, chain in handles():
        wrist, rotation = hand_world(chain.armature, chain.hand)
        set_handle_state(empty, wrist, rotation)
    _LAST.clear()


def solve_to_handles(autokey=None):
    _LAST.clear()
    if autokey is None:
        autokey = getattr(bpy.context.scene, "viewmodel_ik_autokey", True)
    solved = 0
    for empty, chain in handles():
        if chain.armature.mode not in {"OBJECT", "POSE"}:
            continue
        solve_handle(empty, chain, autokey)
        solved += 1
    return solved


# --------------------------------------------------------------------------
# fingers
# --------------------------------------------------------------------------
def finger_chains(armature, hand):
    """Lists of finger bones (base to tip) under a hand."""
    out = []
    for child in armature.data.bones[hand].children:
        if not is_finger(child.name):
            continue
        chain = [child.name]
        while True:
            kids = [c for c in armature.data.bones[chain[-1]].children if is_finger(c.name)]
            if not kids:
                break
            chain.append(kids[0].name)
        out.append(chain)
    return out


def is_thumb(chain):
    # Valve's naming: Finger0x is the thumb
    return chain[0].endswith("Finger0")


def _bend_axis(armature, chain):
    """Axis the finger is already curling about (armature space), or None."""
    heads = [armature.pose.bones[n].head.copy() for n in chain]
    tails = []
    for n in chain:
        b = armature.data.bones[n]
        if b.children:
            tails.append(armature.pose.bones[b.children[0].name].head.copy())
    points = heads + tails[-1:]
    axis = Vector()
    for i in range(len(points) - 2):
        d1 = points[i + 1] - points[i]
        d2 = points[i + 2] - points[i + 1]
        c = d1.cross(d2)
        if c.length > 1e-6 and d1.length > 1e-6 and d2.length > 1e-6:
            axis += c / (d1.length * d2.length)
    return axis.normalized() if axis.length > 0.05 else None


def curl_axes(armature, hand):
    """Curl axis per finger chain: its own bend, or the hand's average."""
    chains_ = finger_chains(armature, hand)
    axes = {}
    fingers_axis = Vector()
    for chain in chains_:
        axis = _bend_axis(armature, chain)
        axes[chain[0]] = axis
        if axis is not None and not is_thumb(chain):
            fingers_axis += axis
    fallback = fingers_axis.normalized() if fingers_axis.length > 1e-6 else Vector((1.0, 0.0, 0.0))
    for chain in chains_:
        if axes[chain[0]] is None:
            axes[chain[0]] = fallback
        elif not is_thumb(chain) and axes[chain[0]].dot(fallback) < 0:
            axes[chain[0]] = -axes[chain[0]]
    return chains_, axes


def _hand_axes(armature, hand):
    """Curl axes, measured once per hand and kept in the hand's own frame, so
    Curl then Open lands exactly where it started."""
    pb = armature.pose.bones[hand]
    key = "viewmodel_curl_axes"
    store = armature.get(key)
    stored = None
    if store is not None and hand in store.keys():
        stored = {k: Vector(v) for k, v in store[hand].items()}
    chains_ = finger_chains(armature, hand)
    to_world = pb.matrix.to_3x3().normalized()
    if stored is None or any(c[0] not in stored for c in chains_):
        _c, axes = curl_axes(armature, hand)
        stored = {k: (to_world.inverted() @ v).normalized() for k, v in axes.items()}
        if store is None:
            armature[key] = {}
        armature[key][hand] = {k: list(v) for k, v in stored.items()}
    return chains_, {k: (to_world @ v).normalized() for k, v in stored.items()}


def curl(armature, hand, degrees, thumb=False, key=True):
    """Bend each finger segment about the finger's curl axis, at its knuckle."""
    chains_, axes = _hand_axes(armature, hand)
    angle = math.radians(degrees)
    touched = []
    for chain in chains_:
        if is_thumb(chain) != thumb:
            continue
        axis = axes[chain[0]]
        for name in chain:
            pb = armature.pose.bones[name]
            local_axis = (pb.matrix.to_3x3().inverted() @ axis).normalized()
            pb.matrix_basis = pb.matrix_basis @ Quaternion(local_axis, angle).to_matrix().to_4x4()
            touched.append(name)
    if key and touched:
        key_bones(armature, touched)
    return touched


# --------------------------------------------------------------------------
# weapon parts
# --------------------------------------------------------------------------
_SKIN = {}


def deformed_meshes(armature):
    for obj in bpy.data.objects:
        if obj.type == "MESH" and any(m.type == "ARMATURE" and m.object == armature for m in obj.modifiers):
            yield obj


def skin_counts(armature):
    counts = {}
    for obj in deformed_meshes(armature):
        names = {g.index: g.name for g in obj.vertex_groups}
        for v in obj.data.vertices:
            for g in v.groups:
                if g.weight > 0.3 and g.group in names:
                    counts[names[g.group]] = counts.get(names[g.group], 0) + 1
    _SKIN[armature.name] = counts
    return counts


def part_bones(armature):
    arm_bones = set()
    for spec in chains(armature):
        arm_bones.update(spec[1:])
    out = []
    for bone in armature.data.bones:
        name = bone.name
        low = name.lower()
        if bone.parent is None or name in arm_bones or is_finger(name):
            continue
        if any(k in low for k in ("spine", "clavicle", "pelvis", "neck", "head", "control", "ulna", "wrist", "elbow",
                                  "muzzle", "eject")):
            continue
        out.append(name)
    return out


def lock_roots(armature):
    for pb in armature.pose.bones:
        if pb.parent is None:
            pb.lock_location = (True, True, True)
            pb.lock_rotation = (True, True, True)
            pb.lock_rotation_w = True
            pb.lock_scale = (True, True, True)


def style_bones(armature):
    """Bigger joint markers and colours: arms blue, fingers green, parts orange."""
    arm_bones = set()
    for spec in chains(armature):
        arm_bones.update(spec[1:])
    parts = set(part_bones(armature))
    for pb in armature.pose.bones:
        palette = None
        scale = None
        if pb.name in arm_bones:
            palette, scale = "THEME04", 3.0
        elif is_finger(pb.name):
            palette, scale = "THEME03", 1.2
        elif pb.name in parts:
            palette, scale = "THEME09", 2.5
        elif pb.parent is None:
            palette = "THEME01"
        try:
            if palette:
                pb.color.palette = palette
            if scale and pb.custom_shape is not None:
                pb.custom_shape_scale_xyz = (scale, scale, scale)
        except (AttributeError, TypeError):
            pass
    armature.show_in_front = True


def _armature_for(context):
    obj = context.active_object
    if obj is not None and obj.type == "ARMATURE":
        return obj
    if obj is not None and obj.type == "MESH":
        arm = obj.find_armature()
        if arm is not None:
            return arm
    for empty, chain in handles():
        return chain.armature
    return next((o for o in context.scene.objects if o.type == "ARMATURE"), None)


def _selected_vertices(mesh_obj):
    bm = bmesh.from_edit_mesh(mesh_obj.data)
    return bm, [v for v in bm.verts if v.select]


def _dominant_bone(mesh_obj, bm, verts):
    deform = bm.verts.layers.deform.verify()
    names = {g.index: g.name for g in mesh_obj.vertex_groups}
    totals = {}
    for v in verts:
        for gi, w in v[deform].items():
            if gi in names:
                totals[names[gi]] = totals.get(names[gi], 0.0) + w
    return max(totals.items(), key=lambda kv: kv[1])[0] if totals else None


def _bind(mesh_obj, bm, verts, bone_name):
    deform = bm.verts.layers.deform.verify()
    group = mesh_obj.vertex_groups.get(bone_name) or mesh_obj.vertex_groups.new(name=bone_name)
    for v in verts:
        weights = v[deform]
        for gi in list(weights.keys()):
            del weights[gi]
        weights[group.index] = 1.0
    bmesh.update_edit_mesh(mesh_obj.data)


def add_bone(armature, name, parent_name, head_armature):
    """New bone at a point, turned like its parent (so its local axes match
    the gun's). Needs the armature in Edit Mode; restores the caller's mode."""
    view_layer = bpy.context.view_layer
    previous_active = view_layer.objects.active
    previous_mode = bpy.context.mode
    if previous_mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode="EDIT")
    eb = armature.data.edit_bones.new(name)
    parent = armature.data.edit_bones.get(parent_name)
    rotation = parent.matrix.to_3x3() if parent is not None else Matrix.Identity(3)
    eb.head = head_armature
    eb.tail = head_armature + rotation.col[1].normalized() * 1.0
    eb.align_roll(rotation.col[2])
    eb.parent = parent
    eb.use_connect = False
    final_name = eb.name
    bpy.ops.object.mode_set(mode="OBJECT")
    view_layer.objects.active = previous_active
    if previous_mode == "EDIT_MESH":
        bpy.ops.object.mode_set(mode="EDIT")
    elif previous_mode == "POSE":
        view_layer.objects.active = armature
        bpy.ops.object.mode_set(mode="POSE")
    return final_name


# --------------------------------------------------------------------------
# triggers
# --------------------------------------------------------------------------
def _on_depsgraph_update(scene, depsgraph=None):
    if getattr(bpy.context, "mode", "OBJECT") in {"EDIT_ARMATURE", "EDIT_MESH"}:
        return
    sync_handles(fresh=True)


def _tick():
    if not bpy.context.scene:
        return None
    try:
        sync_handles(fresh=False)
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


def watching():
    return any(getattr(h, "__name__", "") == "viewmodel_ik_sync" for h in bpy.app.handlers.depsgraph_update_post)


# --------------------------------------------------------------------------
# operators
# --------------------------------------------------------------------------
def _view3d(context, event):
    """(area, window region, region_3d, mouse in region) under the mouse, or
    the first 3D view when the operator was started from the side panel."""
    areas = [context.area] if context.area and context.area.type == "VIEW_3D" else []
    areas += [a for a in context.screen.areas if a.type == "VIEW_3D" and a not in areas]
    for area in areas:
        for region in area.regions:
            if region.type != "WINDOW":
                continue
            x, y = event.mouse_x - region.x, event.mouse_y - region.y
            if 0 <= x < region.width and 0 <= y < region.height or area is areas[-1]:
                return area, region, area.spaces.active.region_3d, Vector((x, y))
    return None


class VIEWMODEL_OT_drag(bpy.types.Operator):
    """Drag (G) or turn (R) the IK handle nearest the mouse; click to key, right click to cancel"""

    bl_idname = "viewmodel.drag"
    bl_label = "Drag IK handle"
    bl_options = {"REGISTER", "UNDO", "BLOCKING"}

    handle: bpy.props.StringProperty(name="Handle", default="")
    mode: bpy.props.EnumProperty(items=(("MOVE", "Move", ""), ("ROTATE", "Turn", "")), default="MOVE")

    def _pick(self, context, region, rv3d, mouse):
        from bpy_extras.view3d_utils import location_3d_to_region_2d

        if self.handle and self.handle in bpy.data.objects:
            return bpy.data.objects[self.handle]
        active = context.active_object
        if active is not None and (active.get("viewmodel_kind") or active.get("viewmodel_pole_for")):
            if active.select_get():
                return active
        best, best_d = None, 1e9
        candidates = [e for e, _c in handles()] + [o for o in bpy.data.objects if o.get("viewmodel_pole_for")]
        for obj in candidates:
            p = location_3d_to_region_2d(region, rv3d, obj.location)
            if p is None:
                continue
            d = (p - mouse).length
            if d < best_d:
                best, best_d = obj, d
        return best

    def invoke(self, context, event):
        found = _view3d(context, event)
        if found is None:
            self.report({"WARNING"}, "No 3D viewport")
            return {"CANCELLED"}
        self.area, self.region, self.rv3d, mouse = found
        target = self._pick(context, self.region, self.rv3d, mouse)
        if target is None:
            self.report({"WARNING"}, "No IK handles - run the rig script")
            return {"CANCELLED"}
        self.target = target
        handle = bpy.data.objects.get(target["viewmodel_pole_for"]) if target.get("viewmodel_pole_for") else target
        self.handle_obj = handle
        self.chain = chain_of(handle)
        if self.chain is None:
            return {"CANCELLED"}
        self.start_mouse = mouse.copy()
        self.start_location = target.location.copy()
        self.start_rotation = target.rotation_quaternion.copy() if target.rotation_mode == "QUATERNION" else None
        self.saved = {n: self.chain.armature.pose.bones[n].matrix_basis.copy() for n in self.chain.bones}
        self.axis = None
        self.precise = False
        self.accum = Vector((0.0, 0.0))
        self.last_mouse = mouse.copy()
        _DRAGGING[0] = True
        context.window_manager.modal_handler_add(self)
        self._header(context)
        return {"RUNNING_MODAL"}

    def _header(self, context):
        lock = " [%s]" % "XYZ"[self.axis] if self.axis is not None else ""
        text = "%s %s%s   G move  R turn  X/Y/Z axis  Shift fine  LMB/Enter keep  RMB/Esc cancel" % (
            "Moving" if self.mode == "MOVE" else "Turning", self.target.name, lock)
        if self.area:
            self.area.header_text_set(text)

    def _apply(self, context):
        from bpy_extras.view3d_utils import region_2d_to_location_3d, location_3d_to_region_2d

        mouse = self.start_mouse + self.accum
        target = self.target
        if self.mode == "MOVE":
            a = region_2d_to_location_3d(self.region, self.rv3d, self.start_mouse, self.start_location)
            b = region_2d_to_location_3d(self.region, self.rv3d, mouse, self.start_location)
            delta = b - a
            if self.axis is not None:
                d = Vector((0.0, 0.0, 0.0))
                d[self.axis] = delta[self.axis]
                delta = d
            target.location = self.start_location + delta
            if self.start_rotation is not None:
                target.rotation_quaternion = self.start_rotation
        else:
            center = location_3d_to_region_2d(self.region, self.rv3d, self.start_location) or self.start_mouse
            v0, v1 = self.start_mouse - center, mouse - center
            if v0.length < 1 or v1.length < 1:
                return
            angle = math.atan2(v0.x * v1.y - v0.y * v1.x, v0.dot(v1))
            if self.axis is not None:
                axis = Vector((0.0, 0.0, 0.0))
                axis[self.axis] = 1.0
            else:
                axis = self.rv3d.view_rotation @ Vector((0.0, 0.0, -1.0))
            target.location = self.start_location
            if self.start_rotation is not None:
                target.rotation_quaternion = Quaternion(axis, -angle) @ self.start_rotation
        for name, basis in self.saved.items():
            self.chain.armature.pose.bones[name].matrix_basis = basis
        context.view_layer.update()
        position, rotation = handle_state(self.handle_obj)
        solve(self.chain, position, rotation, pole_position(self.handle_obj))
        context.view_layer.update()

    def modal(self, context, event):
        if event.type == "MOUSEMOVE":
            mouse = Vector((event.mouse_x - self.region.x, event.mouse_y - self.region.y))
            step = mouse - self.last_mouse
            self.last_mouse = mouse
            self.accum += step * (0.1 if event.shift else 1.0)
            self._apply(context)
        elif event.value == "PRESS" and event.type in {"X", "Y", "Z"}:
            index = "XYZ".index(event.type)
            self.axis = None if self.axis == index else index
            self._apply(context)
        elif event.value == "PRESS" and event.type in {"G", "R"}:
            if event.type == "R" and self.target.get("viewmodel_pole_for"):
                return {"RUNNING_MODAL"}  # poles only move
            self.mode = "MOVE" if event.type == "G" else "ROTATE"
            self.start_location = self.target.location.copy()
            if self.start_rotation is not None:
                self.start_rotation = self.target.rotation_quaternion.copy()
            self.start_mouse = self.start_mouse + self.accum
            self.accum = Vector((0.0, 0.0))
            self._apply(context)
        elif event.value == "PRESS" and event.type in {"LEFTMOUSE", "RET", "NUMPAD_ENTER", "SPACE"}:
            if getattr(context.scene, "viewmodel_ik_autokey", True):
                key_bones(self.chain.armature, self.chain.keyed)
            self._finish(context)
            return {"FINISHED"}
        elif event.value == "PRESS" and event.type in {"RIGHTMOUSE", "ESC"}:
            self.target.location = self.start_location
            if self.start_rotation is not None:
                self.target.rotation_quaternion = self.start_rotation
            for name, basis in self.saved.items():
                self.chain.armature.pose.bones[name].matrix_basis = basis
            self._finish(context)
            return {"CANCELLED"}
        else:
            self._header(context)
        return {"RUNNING_MODAL"}

    def _finish(self, context):
        if self.area:
            self.area.header_text_set(None)
        context.view_layer.update()
        _DRAGGING[0] = False
        _LAST.pop(self.handle_obj.name, None)
        sync_handles(autokey=False, fresh=True)


class VIEWMODEL_OT_solve_now(bpy.types.Operator):
    """Put the wrists on their IK handles"""

    bl_idname = "viewmodel.solve_now"
    bl_label = "Solve to handles"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if not solve_to_handles():
            self.report({"WARNING"}, "No IK handles in this file")
        context.view_layer.update()
        return {"FINISHED"}


class VIEWMODEL_OT_snap_handles(bpy.types.Operator):
    """Move the handles back onto the hands (does not change the pose)"""

    bl_idname = "viewmodel.snap_handles"
    bl_label = "Handles to hands"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        context.view_layer.update()
        snap_handles_to_hands()
        return {"FINISHED"}


class VIEWMODEL_OT_key_pose(bpy.types.Operator):
    """Keyframe the arm and finger bones at the current frame"""

    bl_idname = "viewmodel.key_pose"
    bl_label = "Key arms + fingers"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        for _empty, chain in handles():
            key_bones(chain.armature, chain.keyed)
            fingers = [n for c in finger_chains(chain.armature, chain.hand) for n in c]
            key_bones(chain.armature, fingers)
        return {"FINISHED"}


class VIEWMODEL_OT_watch(bpy.types.Operator):
    """Turn the live handle sync on or off"""

    bl_idname = "viewmodel.watch"
    bl_label = "Toggle live sync"
    bl_options = {"REGISTER"}

    def execute(self, context):
        if watching():
            stop_watch()
        else:
            start_watch()
        return {"FINISHED"}


class VIEWMODEL_OT_poles(bpy.types.Operator):
    """Add an elbow target per two-bone arm (or remove them)"""

    bl_idname = "viewmodel.poles"
    bl_label = "Elbow targets"
    bl_options = {"REGISTER", "UNDO"}

    remove: bpy.props.BoolProperty(default=False)

    def execute(self, context):
        collection = rig_collection(context.scene)
        context.view_layer.update()
        for empty, chain in handles():
            if self.remove:
                pole = bpy.data.objects.get(empty.get("viewmodel_pole", ""))
                if pole is not None:
                    bpy.data.objects.remove(pole)
                if "viewmodel_pole" in empty:
                    del empty["viewmodel_pole"]
            elif chain.kind == "two":
                make_pole(chain.armature, empty, collection)
        _LAST.clear()
        return {"FINISHED"}


class VIEWMODEL_OT_curl(bpy.types.Operator):
    """Curl (positive) or open (negative) the fingers of one hand, and key them"""

    bl_idname = "viewmodel.curl"
    bl_label = "Curl fingers"
    bl_options = {"REGISTER", "UNDO"}

    handle: bpy.props.StringProperty()
    degrees: bpy.props.FloatProperty(default=10.0)
    thumb: bpy.props.BoolProperty(default=False)

    def execute(self, context):
        empty = bpy.data.objects.get(self.handle)
        chain = chain_of(empty) if empty else None
        if chain is None:
            return {"CANCELLED"}
        context.view_layer.update()
        touched = curl(chain.armature, chain.hand, self.degrees, self.thumb,
                       key=getattr(context.scene, "viewmodel_ik_autokey", True))
        if not touched:
            self.report({"WARNING"}, "%s has no finger bones" % chain.hand)
        return {"FINISHED"}


class VIEWMODEL_OT_select_bone(bpy.types.Operator):
    """Select this bone in Pose Mode (then R / G to move it, I to key)"""

    bl_idname = "viewmodel.select_bone"
    bl_label = "Select bone"
    bl_options = {"REGISTER", "UNDO"}

    armature: bpy.props.StringProperty()
    bone: bpy.props.StringProperty()

    def execute(self, context):
        armature = bpy.data.objects.get(self.armature)
        if armature is None or self.bone not in armature.data.bones:
            return {"CANCELLED"}
        if context.mode != "OBJECT" and context.active_object is not armature:
            bpy.ops.object.mode_set(mode="OBJECT")
        for obj in context.selected_objects:
            obj.select_set(False)
        armature.select_set(True)
        context.view_layer.objects.active = armature
        if context.mode != "POSE":
            bpy.ops.object.mode_set(mode="POSE")
        for b in armature.data.bones:
            b.select = b.name == self.bone
        armature.data.bones.active = armature.data.bones[self.bone]
        return {"FINISHED"}


class VIEWMODEL_OT_part_from_selection(bpy.types.Operator):
    """New bone at the centre of the selected vertices, holding just them"""

    bl_idname = "viewmodel.part_from_selection"
    bl_label = "Part from selection"
    bl_options = {"REGISTER", "UNDO"}

    name: bpy.props.StringProperty(name="Bone name", default="Part")
    parent: bpy.props.StringProperty(name="Parent bone")

    @classmethod
    def poll(cls, context):
        return context.mode == "EDIT_MESH" and context.active_object is not None and context.active_object.find_armature()

    def invoke(self, context, event):
        obj = context.active_object
        bm, verts = _selected_vertices(obj)
        if not verts:
            self.report({"WARNING"}, "Select the part's vertices first (L picks linked geometry)")
            return {"CANCELLED"}
        self.parent = _dominant_bone(obj, bm, verts) or ""
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        armature = context.active_object.find_armature()
        self.layout.prop(self, "name")
        self.layout.prop_search(self, "parent", armature.data, "bones")

    def execute(self, context):
        obj = context.active_object
        armature = obj.find_armature()
        bm, verts = _selected_vertices(obj)
        if not verts:
            return {"CANCELLED"}
        center = Vector()
        for v in verts:
            center += v.co
        center /= len(verts)
        head = armature.matrix_world.inverted() @ (obj.matrix_world @ center)
        indices = [v.index for v in verts]
        name = add_bone(armature, self.name, self.parent, head)
        # adding a bone leaves and re-enters Edit Mode: use the vertices
        # chosen before, not whatever is selected now
        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        verts = [bm.verts[i] for i in indices]
        count = len(verts)
        _bind(obj, bm, verts, name)
        skin_counts(armature)
        self.report({"INFO"}, "%s: %d vertices, parent %s" % (name, count, self.parent or "none"))
        return {"FINISHED"}


class VIEWMODEL_OT_bind_selection(bpy.types.Operator):
    """Move the selected vertices onto one bone (weight 1, all others removed)"""

    bl_idname = "viewmodel.bind_selection"
    bl_label = "Bind selection to bone"
    bl_options = {"REGISTER", "UNDO"}

    bone: bpy.props.StringProperty(name="Bone")

    @classmethod
    def poll(cls, context):
        return context.mode == "EDIT_MESH" and context.active_object is not None and context.active_object.find_armature()

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop_search(self, "bone", context.active_object.find_armature().data, "bones")

    def execute(self, context):
        obj = context.active_object
        armature = obj.find_armature()
        if self.bone not in armature.data.bones:
            self.report({"WARNING"}, "Pick a bone")
            return {"CANCELLED"}
        bm, verts = _selected_vertices(obj)
        _bind(obj, bm, verts, self.bone)
        skin_counts(armature)
        return {"FINISHED"}


class VIEWMODEL_OT_refresh(bpy.types.Operator):
    """Re-read bones, handles and skinning (after adding bones)"""

    bl_idname = "viewmodel.refresh"
    bl_label = "Refresh rig"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        build(context.scene, quiet=True)
        return {"FINISHED"}


# --------------------------------------------------------------------------
# panel
# --------------------------------------------------------------------------
class VIEWMODEL_PT_panel(bpy.types.Panel):
    bl_label = "3  Pose: hands, fingers, gun"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Viewmodel"
    bl_order = 3

    @classmethod
    def poll(cls, context):
        return context.scene is not None

    def draw(self, context):
        layout = self.layout
        found = list(handles())
        col = layout.column(align=True)
        col.operator(VIEWMODEL_OT_drag.bl_idname, text="Drag handle (J)", icon="ORIENTATION_GLOBAL")
        row = col.row(align=True)
        row.operator(VIEWMODEL_OT_solve_now.bl_idname, icon="CON_ROTLIKE")
        row.operator(VIEWMODEL_OT_snap_handles.bl_idname, icon="SNAP_ON")
        col.operator(VIEWMODEL_OT_key_pose.bl_idname, icon="KEYTYPE_KEYFRAME_VEC")
        row = col.row(align=True)
        row.prop(context.scene, "viewmodel_ik_autokey")
        row.operator(VIEWMODEL_OT_watch.bl_idname, text="Live sync: %s" % ("on" if watching() else "off"),
                     icon="FILE_REFRESH", depress=watching())
        row = col.row(align=True)
        row.operator(VIEWMODEL_OT_poles.bl_idname, text="Elbow targets", icon="CON_TRACKTO").remove = False
        row.operator(VIEWMODEL_OT_poles.bl_idname, text="", icon="X").remove = True
        col.operator("view3d.view_camera", text="Viewmodel camera", icon="CAMERA_DATA")
        if not found:
            layout.label(text="No handles - run the rig script again", icon="ERROR")
            return

        for empty, chain in found:
            box = layout.box()
            wrist, _rotation = hand_world(chain.armature, chain.hand)
            position, _r = handle_state(empty)
            gap = (wrist - position).length
            head = box.row(align=True)
            head.label(text="%s  (%s)" % (chain.hand.replace("ValveBiped.", ""),
                                          "2 bone" if chain.kind == "two" else "1 bone"),
                       icon="CHECKMARK" if gap < 0.05 else "ERROR")
            op = head.operator(VIEWMODEL_OT_drag.bl_idname, text="", icon="ORIENTATION_GLOBAL")
            op.handle = empty.name
            box.label(text="wrist to handle: %0.2f" % gap)
            box.prop(empty, '["viewmodel_orient"]', text="Handle turns the hand")
            if finger_chains(chain.armature, chain.hand):
                row = box.row(align=True)
                for label, deg, thumb in (("Curl", 10.0, False), ("Open", -10.0, False), ("Thumb +", 10.0, True), ("Thumb -", -10.0, True)):
                    op = row.operator(VIEWMODEL_OT_curl.bl_idname, text=label)
                    op.handle, op.degrees, op.thumb = empty.name, deg, thumb

        armature = found[0][1].armature
        box = layout.box()
        box.label(text="Gun parts", icon="TOOL_SETTINGS")
        counts = _SKIN.get(armature.name)
        if counts is None:
            counts = skin_counts(armature)
        for name in part_bones(armature):
            row = box.row(align=True)
            n = counts.get(name, 0)
            op = row.operator(VIEWMODEL_OT_select_bone.bl_idname, text=name.replace("ValveBiped.", ""),
                              icon="BONE_DATA")
            op.armature, op.bone = armature.name, name
            row.label(text="%d verts" % n if n else "no mesh")
        col = box.column(align=True)
        col.operator(VIEWMODEL_OT_part_from_selection.bl_idname, icon="ADD")
        col.operator(VIEWMODEL_OT_bind_selection.bl_idname, icon="GROUP_VERTEX")
        col.operator(VIEWMODEL_OT_refresh.bl_idname, icon="FILE_REFRESH")


CLASSES = (
    VIEWMODEL_OT_drag,
    VIEWMODEL_OT_solve_now,
    VIEWMODEL_OT_snap_handles,
    VIEWMODEL_OT_key_pose,
    VIEWMODEL_OT_watch,
    VIEWMODEL_OT_poles,
    VIEWMODEL_OT_curl,
    VIEWMODEL_OT_select_bone,
    VIEWMODEL_OT_part_from_selection,
    VIEWMODEL_OT_bind_selection,
    VIEWMODEL_OT_refresh,
    VIEWMODEL_PT_panel,
)

_KEYMAPS = []


def register_ui():
    for cls in CLASSES:
        old = getattr(bpy.types, cls.__name__, None)
        if old is not None:
            try:
                bpy.utils.unregister_class(old)
            except Exception:
                pass
    # v1 classes
    for name in ("VIEWMODEL_OT_solve_now", "VIEWMODEL_OT_key_pose", "VIEWMODEL_OT_watch", "VIEWMODEL_PT_panel"):
        old = getattr(bpy.types, name, None)
        if old is not None:
            try:
                bpy.utils.unregister_class(old)
            except Exception:
                pass
    for cls in CLASSES:
        bpy.utils.register_class(cls)

    if not hasattr(bpy.types.Scene, "viewmodel_ik_autokey"):
        bpy.types.Scene.viewmodel_ik_autokey = bpy.props.BoolProperty(
            name="Auto key", description="Keyframe the arm bones when a pose is confirmed", default=True)

    keyconfig = bpy.context.window_manager.keyconfigs.addon
    if keyconfig is not None:
        for km_name in ("Object Mode", "Pose"):
            km = keyconfig.keymaps.get(km_name) or keyconfig.keymaps.new(name=km_name, space_type="EMPTY")
            for item in list(km.keymap_items):
                if item.idname == VIEWMODEL_OT_drag.bl_idname:
                    km.keymap_items.remove(item)
            km.keymap_items.new(VIEWMODEL_OT_drag.bl_idname, "J", "PRESS")


def build(scene, quiet=False):
    camera = first_person_camera(scene)
    selected = [o for o in bpy.context.selected_objects if o.type == "ARMATURE"]
    active = bpy.context.view_layer.objects.active
    if not selected and active is not None and active.type == "ARMATURE":
        selected = [active]
    if not selected:
        selected = [o for o in scene.objects if o.type == "ARMATURE"]
    if not selected:
        print("! no armature in the scene - import a _anims.qc first")
        return 0
    collection = rig_collection(scene)
    bpy.context.view_layer.update()
    total = 0
    for armature in selected:
        lock_roots(armature)
        style_bones(armature)
        specs = chains(armature)
        names = {HANDLE_PREFIX + s[-1] for s in specs}
        # handles left over from bones that no longer exist on this armature
        for obj in list(bpy.data.objects):
            if obj.get(ARMATURE_PROP) == armature.name and obj.get("viewmodel_kind") and obj.name not in names:
                bpy.data.objects.remove(obj)
        for spec in specs:
            empty = make_handle(armature, Chain(armature, spec), collection)
            total += 1
            if not quiet:
                print("  %-34s %s arm: %s" % (empty.name, "two bone" if spec[0] == "two" else "one bone", " / ".join(spec[1:])))
        skin_counts(armature)
        if not specs and not quiet:
            print("! %s: no arm chain found" % armature.name)
        if not quiet:
            parts = part_bones(armature)
            counts = _SKIN.get(armature.name, {})
            print("  gun parts: %s" % ", ".join("%s%s" % (p, "" if counts.get(p) else " (no mesh)") for p in parts))
    if not quiet:
        print("Viewmodel camera: %s, %.0f deg horizontal" % (camera.name, VIEWMODEL_FOV))
    return total


def main():
    total = build(bpy.context.scene)
    register_ui()
    bpy.context.view_layer.update()
    start_watch()
    print("%d IK handle(s) ready. J over the viewport drags the nearest one." % total)
    print("N panel > Viewmodel tab: hands, fingers, gun parts.")
    return 0


def unregister_ui():
    stop_watch()
    keyconfig = bpy.context.window_manager.keyconfigs.addon
    if keyconfig is not None:
        for km_name in ("Object Mode", "Pose"):
            km = keyconfig.keymaps.get(km_name)
            if km is None:
                continue
            for item in list(km.keymap_items):
                if item.idname == VIEWMODEL_OT_drag.bl_idname:
                    km.keymap_items.remove(item)
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
