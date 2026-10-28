"""Compile the Adrian Shephard playermodel from the Sketchfab FBX.

The FBX outside the mod (Sketchfab "adrian shephard gmod") is already skinned to a
ValveBiped skeleton in HL2 units, so this is a port rather than a retarget:

  * the model's skeleton, attachments and include-animation list are taken from the
    shipping playermodel (models/sirgibs/ragdolls/gordon_survivor_player.mdl), which
    is byte-for-byte the stock HL2 player skeleton that models/player/male_anims.mdl
    animates. Using that skeleton verbatim is what makes $includemodel animations
    play correctly - the FBX bone *positions* match it to within a unit, but its bone
    orientations (roll) are Blender's, which would twist every animated bone.
  * only the mesh (positions, normals, UVs, weights) comes from the FBX.

Physics is rebuilt for this mesh as well: the collision SMD carries one convex box
per ragdoll solid, and the QC's $collisionjoints block reproduces the shipping
playermodel's mass, damping and joint limits, so the corpse behaves as before.
A borrowed .phy cannot work here - it addresses physics bones, and a model compiled
without a collision model has none.

Measured conventions (see HANDOFF.md and export_viewmodel_anims.py):
  * SMD and compiled model space are the same for a reference pose: writing the
    vertices and bones in this space and recompiling reproduces them exactly
    (verified by round-tripping gordon_survivor_player through studiomdl).
  * SMD bone rotations are radians here, and bone lines are parent-relative.

Run with Blender's Python (the FBX importer needs bpy):

  ~/.local/bin/blender -b --python-exit-code 1 --python tools/build_adrian_playermodel.py

Options: --fbx <path> --mod-dir <path> --skip-textures --skip-compile
"""

from __future__ import annotations

import argparse
import glob
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

DEFAULT_FBX = (
    "/media/hyper/Storage HDD/Asset Library/Models/Sketchfab/Characters/"
    "adrian-shephard-gmod"
)
DEFAULT_TEXTURE_DIR = os.path.join(DEFAULT_FBX, "textures")
DEFAULT_MOD_DIR = os.path.expanduser(
    "~/.steam/debian-installation/steamapps/sourcemods/HLShattered"
)

STEM = "adrian_shephard_player"
# The shipping Gordon model is the authority for the skeleton, attachments and
# include list; its skeleton is identical to models/player/male_anims.mdl.
REFERENCE_MODEL = "models/sirgibs/ragdolls/gordon_survivor_player.mdl"
OUT_MODEL_PATH = "sirgibs/ragdolls/" + STEM + ".mdl"
# cl_playermodel's default value and the mod-settings panel's model commands are
# compiled into bin/client.so, so the Gordon slot has to serve the new model for
# those paths to show Adrian. The original files are kept next to it.
SLOT_NAME = "gordon_survivor_player"
SLOT_DIR = "models/sirgibs/ragdolls"
BACKUP_DIR = "models/sirgibs/ragdolls/original_gordon"
# Once the slot is replaced, the reference has to come from the original copy.
REFERENCE_BACKUP = BACKUP_DIR + "/" + SLOT_NAME + ".mdl"
MODEL_EXTENSIONS = (".mdl", ".vvd", ".dx80.vtx", ".dx90.vtx", ".sw.vtx")
MATERIAL_ROOT = "models/sirgibs/adrian_shephard"
MAX_WEIGHTS = 3  # SMD/studiomdl limit per vertex
DEFAULT_PLAYERMODEL = "models/sirgibs/ragdolls/gordon_survivor_player.mdl"

# The FBX carries a few bones the HL2 player skeleton does not have. Elbow sits on
# the forearm's head, and the *_end stubs are Blender leaf bones, so their weights
# belong to the bone that owns the joint.
BONE_ALIASES = {
    "ValveBiped.Bip01_L_Elbow": "ValveBiped.Bip01_L_Forearm",
    "ValveBiped.Bip01_R_Elbow": "ValveBiped.Bip01_R_Forearm",
}

# Blender material name -> (VMT name, texture file)
MATERIALS = {
    "humangrunt_sheet": ("adrian_body", "humangrunt_sheet.png"),
    "Gasmask_sheet": ("adrian_gasmask", "Gasmask_sheet.jpg"),
    "mask_glass": ("adrian_glass", "mask_glass.jpg"),
    "eyeball_r": ("adrian_eyeball_r", "eye2.png"),
    "eyeball_l": ("adrian_eyeball_l", "eye2.png"),
}

# Source vtex only reads TGA; system Pillow is used instead of bpy's Image.save,
# which fails with "does not have any image data" after the FBX import.
TGA_SNIPPET = """
import sys
from PIL import Image


def power_of_two(n):
    size = 1
    while size < n:
        size *= 2
    return size


image = Image.open(sys.argv[1]).convert("RGB")
width, height = image.size
# vtex rejects non-power-of-two source textures (the eye texture is 56x55).
if (width, height) != (power_of_two(width), power_of_two(height)):
    image = image.resize((power_of_two(width), power_of_two(height)), Image.LANCZOS)
image.save(sys.argv[2], "TGA")
"""


# --------------------------------------------------------------------------
# FBX import (Blender 5.0's importer trips over this file's lamp)
# --------------------------------------------------------------------------
def patch_fbx_importer() -> None:
    import bpy
    import io_scene_fbx.import_fbx as importer

    original = importer.blen_read_light

    def safe_read_light(fbx_obj, fbx_tmpl, settings):
        try:
            return original(fbx_obj, fbx_tmpl, settings)
        except AttributeError:
            # Blender 5.0 dropped CyclesLightSettings.cast_shadow, which the
            # importer still writes. The lamp is discarded anyway.
            for lamp in list(bpy.data.lights):
                if lamp.users == 0:
                    bpy.data.lights.remove(lamp)
            return bpy.data.lights.new(name="ImportedLight", type="POINT")

    importer.blen_read_light = safe_read_light


def import_fbx(path: str):
    import bpy

    patch_fbx_importer()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=path)

    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    if not meshes:
        raise SystemExit(f"no mesh found in {path}")
    # The FBX points its images at the original author's C:/Users/... folders, which
    # leaves unloadable datablocks behind and makes a later load() of the real
    # texture return an empty image. Only the material names matter here.
    for image in list(bpy.data.images):
        bpy.data.images.remove(image)
    # The Sketchfab file has one skinned body mesh plus a lamp.
    body = max(meshes, key=lambda o: len(o.data.vertices))
    return body


# --------------------------------------------------------------------------
# Mesh -> SMD geometry
# --------------------------------------------------------------------------
# Hitbox layout copied from the shipping playermodel: one head, chest and stomach box,
# three per arm and four per leg, using HL2's hit group numbers
# (1 head, 2 chest, 3 stomach, 4 left arm, 5 right arm, 6 left leg, 7 right leg).
HITBOX_PLAN = (
    ("ValveBiped.Bip01_Head1", 1),
    ("ValveBiped.Bip01_Spine4", 2),
    ("ValveBiped.Bip01_Pelvis", 3),
    ("ValveBiped.Bip01_L_UpperArm", 4),
    ("ValveBiped.Bip01_L_Forearm", 4),
    ("ValveBiped.Bip01_L_Hand", 4),
    ("ValveBiped.Bip01_R_UpperArm", 5),
    ("ValveBiped.Bip01_R_Forearm", 5),
    ("ValveBiped.Bip01_R_Hand", 5),
    ("ValveBiped.Bip01_L_Thigh", 6),
    ("ValveBiped.Bip01_L_Calf", 6),
    ("ValveBiped.Bip01_L_Foot", 6),
    ("ValveBiped.Bip01_L_Toe0", 6),
    ("ValveBiped.Bip01_R_Thigh", 7),
    ("ValveBiped.Bip01_R_Calf", 7),
    ("ValveBiped.Bip01_R_Foot", 7),
    ("ValveBiped.Bip01_R_Toe0", 7),
)
HITBOX_MARGIN = 0.35  # units of padding so boxes are not inside the surface

# Ragdoll: the same 17-solid layout the shipping playermodel uses, read out of its
# .phy keyvalue block. Parents come from the bone hierarchy, so only the solid bones
# are listed. Spine/Spine1 are folded into the pelvis solid by $jointmerge, exactly
# as the original does, which is why they are not solids themselves.
PHYSICS_SOLIDS = (
    "ValveBiped.Bip01_Pelvis",
    "ValveBiped.Bip01_Spine2",
    "ValveBiped.Bip01_Head1",
    "ValveBiped.Bip01_L_Clavicle",
    "ValveBiped.Bip01_L_UpperArm",
    "ValveBiped.Bip01_L_Forearm",
    "ValveBiped.Bip01_L_Hand",
    "ValveBiped.Bip01_R_Clavicle",
    "ValveBiped.Bip01_R_UpperArm",
    "ValveBiped.Bip01_R_Forearm",
    "ValveBiped.Bip01_R_Hand",
    "ValveBiped.Bip01_L_Thigh",
    "ValveBiped.Bip01_L_Calf",
    "ValveBiped.Bip01_L_Foot",
    "ValveBiped.Bip01_R_Thigh",
    "ValveBiped.Bip01_R_Calf",
    "ValveBiped.Bip01_R_Foot",
)
PHYSICS_MERGED = ("ValveBiped.Bip01_Spine1",)  # what the original .phy merges
JOINT_LIMITS = {
    "ValveBiped.Bip01_L_Thigh": ((-12, 12), (-73, 6), (-93, 30)),
    "ValveBiped.Bip01_L_Calf": ((0, 0), (0, 0), (-8, 126)),
    "ValveBiped.Bip01_R_Thigh": ((-12, 12), (-8, 75), (-97, 32)),
    "ValveBiped.Bip01_R_Calf": ((0, 0), (0, 0), (-12, 126)),
    "ValveBiped.Bip01_R_Foot": ((0, 0), (-25, 6), (-15, 35)),
    "ValveBiped.Bip01_Spine2": ((-48, 48), (-25, 25), (-25, 50)),
    "ValveBiped.Bip01_L_Clavicle": ((0, 0), (0, 0), (0, 0)),
    "ValveBiped.Bip01_L_UpperArm": ((-30, 30), (-95, 84), (-86, 26)),
    "ValveBiped.Bip01_L_Forearm": ((0, 0), (0, 0), (-149, 4)),
    "ValveBiped.Bip01_R_Clavicle": ((0, 0), (0, 0), (0, 0)),
    "ValveBiped.Bip01_R_UpperArm": ((-39, 39), (-79, 95), (-93, 23)),
    "ValveBiped.Bip01_R_Forearm": ((0, 0), (0, 0), (-149, 4)),
    "ValveBiped.Bip01_R_Hand": ((-60, 60), (0, 0), (-57, 70)),
    "ValveBiped.Bip01_L_Hand": ((-37, 37), (0, 0), (-57, 59)),
    "ValveBiped.Bip01_Head1": ((-20, 20), (-25, 25), (-13, 30)),
    "ValveBiped.Bip01_L_Foot": ((0, 0), (-19, 19), (-15, 35)),
}
# The original .phy gives every solid a mass of 1 kg, which is what studiomdl does
# when a QC sets no $mass, so no $mass is emitted here either: that keeps the body's
# weight (and therefore how it is pushed around) identical to before.
RAGDOLL_DAMPING = 0.01
RAGDOLL_ROTDAMPING = 1.5
RAGDOLL_INERTIA = 10.0
# animfrictionmin, max, timein, timeout, timehold - straight from the original .phy
RAGDOLL_ANIMFRICTION = (1.0, 400.0, 0.5, 0.3, 0.0)
HULL_MARGIN = 0.25
HULL_MIN_EXTENT = 1.0


def bone_matrices(bones) -> list:
    """Absolute bone matrix per bone, composed the same way the MDL stores them."""
    import numpy as np
    import export_viewmodel_anims as eva

    matrices: list = [None] * len(bones)

    def compose(index: int, depth: int = 0):
        if matrices[index] is not None:
            return matrices[index]
        bone = bones[index]
        local = np.eye(4)
        local[:3, :3] = np.array(eva.quaternion_matrix(eva.angle_quaternion(bone.rot)))
        local[:3, 3] = bone.pos
        parent = bone.parent
        if parent < 0 or parent >= len(bones) or depth > len(bones):
            matrices[index] = local
        else:
            matrices[index] = compose(parent, depth + 1) @ local
        return matrices[index]

    return [compose(i) for i in range(len(bones))]


def bone_hitboxes(mesh_obj, bones, bone_index: dict[str, int], weights: dict[int, list]) -> list:
    """Fit one box per hitbox bone around the vertices that bone actually drives."""
    import numpy as np

    matrices = bone_matrices(bones)
    inverse = [np.linalg.inv(matrix) for matrix in matrices]
    world = mesh_obj.matrix_world

    # Each vertex counts for the bone with the largest influence, so boxes follow the
    # anatomy instead of every joint claiming the skin around it.
    dominant: dict[int, list] = {}
    for vertex_index, links in weights.items():
        if not links:
            continue
        bone, _weight = max(links, key=lambda item: item[1])
        dominant.setdefault(bone, []).append(vertex_index)

    def nearest_driver(index: int, depth: int = 0) -> list:
        """Vertices for a bone, or for its nearest ancestor that drives skin."""
        points = dominant.get(index)
        if points or depth > len(bones):
            return points or []
        parent = bones[index].parent if 0 <= index < len(bones) else -1
        return nearest_driver(parent, depth + 1) if parent >= 0 else []

    boxes = []
    for name, group in HITBOX_PLAN:
        index = bone_index.get(name)
        if index is None:
            continue
        points = nearest_driver(index)
        if not points:
            print(f"  ! no vertices for hitbox bone {name}")
            continue
        low = np.array([np.inf, np.inf, np.inf])
        high = np.array([-np.inf, -np.inf, -np.inf])
        for vertex_index in points:
            position = world @ mesh_obj.data.vertices[vertex_index].co
            local = (inverse[index] @ np.array([position.x, position.y, position.z, 1.0]))[:3]
            low = np.minimum(low, local)
            high = np.maximum(high, local)
        boxes.append((group, name, low - HITBOX_MARGIN, high + HITBOX_MARGIN))
    return boxes


def local_bounds(mesh_obj, bones, bone_index: dict[str, int], weights: dict[int, list], names) -> dict:
    """Bone-space bounding box of the vertices each bone dominates."""
    import numpy as np

    matrices = bone_matrices(bones)
    inverse = [np.linalg.inv(matrix) for matrix in matrices]
    world = mesh_obj.matrix_world

    dominant: dict[int, list] = {}
    for vertex_index, links in weights.items():
        if not links:
            continue
        bone, _weight = max(links, key=lambda item: item[1])
        dominant.setdefault(bone, []).append(vertex_index)

    result = {}
    for name in names:
        index = bone_index.get(name)
        if index is None:
            continue
        points = dominant.get(index) or []
        if not points:
            print(f"  ! no vertices for {name}")
            continue
        low = np.array([np.inf, np.inf, np.inf])
        high = np.array([-np.inf, -np.inf, -np.inf])
        for vertex_index in points:
            position = world @ mesh_obj.data.vertices[vertex_index].co
            local = (inverse[index] @ np.array([position.x, position.y, position.z, 1.0]))[:3]
            low = np.minimum(low, local)
            high = np.maximum(high, local)
        result[name] = (low, high)
    return result


def box_triangles(low, high, bone_index: int, matrix=None) -> list:
    """Twelve outward-facing triangles for a bone-space box, weighted to one bone.

    ``matrix`` is the bone's absolute transform: collision triangles, unlike
    $hbox, live in model space, so the box has to be rotated out of bone space.
    """
    import numpy as np

    x0, y0, z0 = low
    x1, y1, z1 = max(high[0], low[0] + HULL_MIN_EXTENT), max(high[1], low[1] + HULL_MIN_EXTENT), max(high[2], low[2] + HULL_MIN_EXTENT)
    corners = [
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
    ]
    faces = (
        (0, 3, 2), (0, 2, 1),
        (4, 5, 6), (4, 6, 7),
        (0, 1, 5), (0, 5, 4),
        (1, 2, 6), (1, 6, 5),
        (2, 3, 7), (2, 7, 6),
        (3, 0, 4), (3, 4, 7),
    )
    rotation = np.eye(3) if matrix is None else np.asarray(matrix)[:3, :3]
    translation = np.zeros(3) if matrix is None else np.asarray(matrix)[:3, 3]

    def place(point):
        return rotation @ np.array(point, dtype=float) + translation

    triangles = []
    for a, b, c in faces:
        pa, pb, pc = (place(corners[i]) for i in (a, b, c))
        normal = np.cross(pb - pa, pc - pa)
        length = np.linalg.norm(normal)
        normal = normal / length if length else np.array([0.0, 0.0, 1.0])
        triangles.append(
            tuple(
                ((p[0], p[1], p[2]), (normal[0], normal[1], normal[2]), (0.0, 0.0), [(bone_index, 1.0)])
                for p in (pa, pb, pc)
            )
        )
    return triangles


def write_collision_smd(path: str, bones, geometry: list) -> None:
    """Collision SMD: skeleton plus one convex box per physics bone.

    No marker triangles here - every triangle in this file becomes a collision hull,
    so anything extra would add a solid to the ragdoll.
    """
    import export_viewmodel_anims as eva

    lines = ["version 1", "nodes"]
    for i, bone in enumerate(bones):
        lines.append(f'{i} "{bone.name}" {bone.parent}')
    lines += ["end", "skeleton", "time 0"]
    for i, bone in enumerate(bones):
        lines.append(
            "%d %.6f %.6f %.6f %.6f %.6f %.6f" % (i, *bone.pos, *bone.rot)
        )
    lines += ["end", "triangles"]
    for material, corners in geometry:
        eva.smd_triangle(lines, material, list(corners))
    lines += ["end"]
    with open(path, "w", newline="\n") as f:
        f.write("\n".join(lines) + "\n\n")


def collision_geometry(mesh_obj, bones, bone_index: dict[str, int], weights: dict[int, list]) -> list:
    """One box per solid bone, sized from the mesh it represents.

    Only PHYSICS_SOLIDS get a hull: Spine and Spine1 are merged into the pelvis by
    $jointmerge, so a hull for them would be a second solid at the same place.
    """
    bounds = local_bounds(mesh_obj, bones, bone_index, weights, PHYSICS_SOLIDS)
    matrices = bone_matrices(bones)
    geometry = []
    for name in PHYSICS_SOLIDS:
        box = bounds.get(name)
        if box is None:
            continue
        low, high = box
        index = bone_index[name]
        # All physics triangles share one material name. A distinct name per bone
        # makes this studiomdl collide the solids into each other: it built 8 solids
        # out of 17 and fell back to a single hull for the rest.
        material = "phys"
        for triangle in box_triangles(
            low - HULL_MARGIN, high + HULL_MARGIN, index, matrices[index]
        ):
            geometry.append((material, triangle))
    return geometry


def resolve_bone(name: str, bone_index: dict[str, int]) -> int | None:
    if name in bone_index:
        return bone_index[name]
    alias = BONE_ALIASES.get(name)
    if alias in bone_index:
        return bone_index[alias]
    if name.endswith("_end") and name[:-4] in bone_index:
        return bone_index[name[:-4]]
    return None


def vertex_weights(mesh_obj, bone_index: dict[str, int], stats: dict) -> dict[int, list]:
    groups = {g.index: g.name for g in mesh_obj.vertex_groups}
    per_vertex: dict[int, list] = {}
    for vertex in mesh_obj.data.vertices:
        links = []
        for element in vertex.groups:
            name = groups.get(element.group)
            if name is None or element.weight <= 0.0:
                continue
            index = resolve_bone(name, bone_index)
            if index is None:
                stats["unknown_groups"].add(name)
                continue
            links.append((index, float(element.weight)))
        links.sort(key=lambda item: -item[1])
        stats["max_influences"] = max(stats["max_influences"], len(links))
        if len(links) > MAX_WEIGHTS:
            stats["truncated"] += 1
            links = links[:MAX_WEIGHTS]
        total = sum(w for _i, w in links)
        if total > 0.0:
            links = [(i, w / total) for i, w in links]
        per_vertex[vertex.index] = links
    return per_vertex


def mesh_geometry(mesh_obj, bone_index: dict[str, int]) -> tuple[list, dict]:
    """Triangles in the format export_viewmodel_anims.write_skeleton_smd wants."""
    import bpy  # noqa: F401  (only needed for the operator context)

    mesh = mesh_obj.data
    mesh.calc_loop_triangles()
    uv_layer = mesh.uv_layers.active
    if uv_layer is None:
        raise SystemExit("mesh has no UV layer; SMD export needs UVs")

    matrix = mesh_obj.matrix_world
    normal_matrix = matrix.to_3x3().inverted().transposed()
    corner_normals = getattr(mesh, "corner_normals", None)

    stats = {"max_influences": 0, "truncated": 0, "unknown_groups": set()}
    weights = vertex_weights(mesh_obj, bone_index, stats)

    materials = [m.name if m else "" for m in mesh.materials]
    geometry = []
    dropped = 0
    for tri in mesh.loop_triangles:
        material = materials[tri.material_index] if tri.material_index < len(materials) else ""
        corners = []
        for loop_index in tri.loops:
            loop = mesh.loops[loop_index]
            vertex = mesh.vertices[loop.vertex_index]
            links = weights.get(loop.vertex_index, [])
            if not links:
                corners = []
                break
            position = matrix @ vertex.co
            if corner_normals is not None:
                normal = (normal_matrix @ corner_normals[loop_index].vector).normalized()
            else:
                normal = (normal_matrix @ vertex.normal).normalized()
            uv = uv_layer.data[loop_index].uv
            corners.append(
                (
                    (position.x, position.y, position.z),
                    (normal.x, normal.y, normal.z),
                    (uv.x, uv.y),
                    links,
                )
            )
        if len(corners) == 3:
            geometry.append((name_of(material), corners))
        else:
            dropped += 1

    if dropped:
        print(f"  ! {dropped} triangles had no weights and were dropped")
    print(
        f"  mesh: {len(geometry)} triangles, max {stats['max_influences']} influences/vertex"
        + (f", {stats['truncated']} truncated to {MAX_WEIGHTS}" if stats["truncated"] else "")
    )
    if stats["unknown_groups"]:
        print(f"  ! vertex groups with no bone: {sorted(stats['unknown_groups'])}")
    return geometry, stats, weights


def add_marker_triangles(geometry: list, bones, material: str, size: float = 0.02) -> int:
    """Keep bones the mesh does not weight, without leaving visible geometry.

    studiomdl drops bones no triangle references, and the HL2 animation sets drive
    bones this model has no skin on (Tie, Ulna, Wrist, the fourth fingers...). A
    half-millimetre triangle at the bone's bind position keeps the bone and stays
    inside the body. export_viewmodel_anims adds its own marker triangles for
    weighted-less bones, so these must exist before it sees the geometry.
    """
    import export_viewmodel_anims as eva

    used = {bone for _m, corners in geometry for _p, _n, _uv, links in corners for bone, _w in links}
    absolute = eva.bind_positions(bones)
    added = 0
    for index, _bone in enumerate(bones):
        if index in used:
            continue
        x, y, z = absolute[index]
        corners = [
            ((x + size, y, z), (0.0, 0.0, 1.0), (0.0, 0.0), [(index, 1.0)]),
            ((x, y + size, z), (0.0, 0.0, 1.0), (1.0, 0.0), [(index, 1.0)]),
            ((x, y, z + size), (0.0, 0.0, 1.0), (0.0, 1.0), [(index, 1.0)]),
        ]
        geometry.append((material, corners))
        added += 1
    return added


def name_of(material: str) -> str:
    entry = MATERIALS.get(material)
    return entry[0] if entry else re.sub(r"[^A-Za-z0-9_.-]+", "_", material) or "default"


# --------------------------------------------------------------------------
# Reference model: skeleton, attachments, includes
# --------------------------------------------------------------------------
def reference_data(mod_dir: str):
    import export_viewmodel_anims as eva

    # After the first build the Gordon slot holds Adrian, so the pristine copy is
    # the authority from then on. Reading the slot again would fold a previous
    # build's output into the next one.
    game_path = REFERENCE_MODEL
    if os.path.isfile(os.path.join(mod_dir, REFERENCE_BACKUP)):
        game_path = REFERENCE_BACKUP
    reader = eva.MdlReader(eva.GameFiles(mod_dir))
    model = reader.load(game_path)
    if model is None:
        raise SystemExit(f"could not read the reference model {game_path}")
    print(f"reference: {game_path}")
    eva.load_sourceio()
    from SourceIO.library.models.mdl.v49.mdl_file import MdlV49

    with open(os.path.join(mod_dir, game_path), "rb") as f:
        data = f.read()
    header_model = MdlV49.from_buffer(eva.Buffer(data))

    attachments = []
    for attachment in header_model.attachments:
        bone = model.bones[attachment.parent_bone].name if attachment.parent_bone < len(model.bones) else ""
        attachments.append((attachment.name, bone, attachment.pos, attachment.rot))

    includes = [path[len("models/"):] if path.startswith("models/") else path for path in model.includes]
    return reader, model, attachments, includes, header_model, ik_chains(
        data, header_model.header.ik_chain_count, header_model.header.ik_chain_offset, model.bones
    )


def ik_chains(data: bytes, count: int, offset: int, bones) -> list:
    """(chain name, end bone, knee direction) per IK chain in a compiled model.

    The engine drives the player's hands and feet through these, so a playermodel
    without them loses procedural IK. $ikchain wants the end bone only; studiomdl
    walks back two bones to build the three links.
    """
    chains = []
    for i in range(max(0, count)):
        base = offset + i * 16
        name_off, _link_type, link_count, link_index = struct.unpack_from("<iiii", data, base)
        name = data[base + name_off:].split(b"\x00")[0].decode(errors="replace")
        if link_count <= 0:
            continue
        last = base + link_index + (link_count - 1) * 28
        end_bone = struct.unpack_from("<i", data, last)[0]
        knee = struct.unpack_from("<3f", data, base + link_index + 4)
        if 0 <= end_bone < len(bones):
            chains.append((name, bones[end_bone].name, knee))
    return chains


# --------------------------------------------------------------------------
# Textures and materials
# --------------------------------------------------------------------------
def install_into_gordon_slot(mod_dir: str, compiled_stem: str) -> None:
    """Serve the new model at the path the client binary hardcodes for Gordon."""
    slot = os.path.join(mod_dir, SLOT_DIR, SLOT_NAME)
    backup = os.path.join(mod_dir, BACKUP_DIR, SLOT_NAME)
    if os.path.isfile(slot + ".mdl") and not os.path.isfile(backup + ".mdl"):
        os.makedirs(os.path.dirname(backup), exist_ok=True)
        for extension in MODEL_EXTENSIONS + (".phy",):
            if os.path.isfile(slot + extension):
                shutil.copy2(slot + extension, backup + extension)
        print(f"  backed up the original Gordon model to {BACKUP_DIR}/")
    for extension in MODEL_EXTENSIONS:
        shutil.copy2(compiled_stem + extension, slot + extension)
    print(f"  installed as {SLOT_DIR}/{SLOT_NAME}.mdl")


def install_physics(mod_dir: str, compiled_stem: str) -> None:
    """Put the compiled ragdoll .phy next to every path that serves the model.

    The .phy has to be this model's own: it stores one convex hull per solid and
    indexes them by the model's *physics* bones, so the original file borrowed onto a
    model compiled without a collision model drives nothing.
    """
    source = compiled_stem + ".phy"
    if not os.path.isfile(source):
        print("  ! studiomdl wrote no .phy; the ragdoll would be missing")
        return
    stems = [compiled_stem]
    if os.path.abspath(compiled_stem) != os.path.abspath(os.path.join(mod_dir, SLOT_DIR, SLOT_NAME)):
        stems.append(os.path.join(mod_dir, SLOT_DIR, SLOT_NAME))
    for stem in stems:
        if os.path.abspath(stem) != os.path.abspath(compiled_stem):
            shutil.copy2(source, stem + ".phy")
    print("  ragdoll physics: .phy installed next to the model")


def run_vtex(mod_dir: str, sources: list[str]) -> None:
    vtex = None
    for pattern in (
        "~/.steam/debian-installation/steamapps/common/Half-Life 2/bin/vtex.exe",
        "~/.steam/steam/steamapps/common/Half-Life 2/bin/vtex.exe",
    ):
        hits = glob.glob(os.path.expanduser(pattern))
        if hits:
            vtex = hits[0]
            break
    if vtex is None:
        raise SystemExit("vtex.exe not found (looked in the Half-Life 2 bin folder)")
    command = ["wine", vtex, "-nop4", "-game", mod_dir, "-mkdir", "-nopause", "-quiet", *sources]
    env = dict(os.environ, WINEDEBUG="-all")
    proc = subprocess.run(command, cwd=mod_dir, env=env, capture_output=True, text=True, timeout=900)
    output = proc.stdout + proc.stderr
    for line in output.splitlines():
        if "ERROR" in line or "Error" in line:
            print("  vtex:", line.strip())


def build_materials(mod_dir: str, texture_dir: str) -> None:
    material_dir = os.path.join(mod_dir, "materials", MATERIAL_ROOT)
    source_dir = os.path.join(mod_dir, "materialsrc", MATERIAL_ROOT)
    os.makedirs(material_dir, exist_ok=True)
    os.makedirs(source_dir, exist_ok=True)

    python = shutil.which("python3")
    if python is None:
        raise SystemExit("python3 with Pillow is needed to convert the textures to TGA")

    tga_paths = []
    for _material, (vmt, texture) in MATERIALS.items():
        image_path = os.path.join(texture_dir, texture)
        if not os.path.isfile(image_path):
            raise SystemExit(f"missing texture {image_path}")
        tga_path = os.path.join(source_dir, vmt + ".tga")
        proc = subprocess.run(
            [python, "-c", TGA_SNIPPET, image_path, tga_path], capture_output=True, text=True
        )
        if proc.returncode != 0:
            raise SystemExit(f"TGA conversion failed for {texture}: {proc.stderr.strip()}")
        print(f"  {texture} -> materialsrc/{MATERIAL_ROOT}/{vmt}.tga")
        if tga_path not in tga_paths:
            tga_paths.append(tga_path)

    run_vtex(mod_dir, tga_paths)

    for material, (vmt, _texture) in MATERIALS.items():
        vtf = os.path.join(material_dir, vmt + ".vtf")
        if not os.path.isfile(vtf):
            raise SystemExit(f"vtex did not produce {vtf}")
        surface = "glass" if "mask" in material else "flesh"
        lines = [
            f"// {STEM} - generated by tools/build_adrian_playermodel.py",
            '"VertexLitGeneric"',
            "{",
            f'\t"$basetexture" "{MATERIAL_ROOT}/{vmt}"',
            '\t"$model" "1"',
            f'\t"$surfaceprop" "{surface}"',
        ]
        if material.startswith("eyeball"):
            lines.append('\t"$halflambert" "1"')
        else:
            lines.append('\t"$phong" "1"')
            lines.append('\t"$phongexponent" "15"')
            lines.append('\t"$phongboost" "0.6"')
            lines.append('\t"$phongfresnelranges" "[0.4 1 1.6]"')
        lines += ["}", ""]
        with open(os.path.join(material_dir, vmt + ".vmt"), "w", newline="\n") as f:
            f.write("\n".join(lines))
        print(f"  materials/{MATERIAL_ROOT}/{vmt}.vmt")


# --------------------------------------------------------------------------
# QC
# --------------------------------------------------------------------------
def write_qc(path: str, attachments, includes, eyeposition, hitboxes, ik, phys_smd: str) -> None:
    lines = [
        f"// {STEM} - generated by tools/build_adrian_playermodel.py",
        f'$modelname "{OUT_MODEL_PATH}"',
        f'$model "{STEM}" "{STEM}_ref.smd"',
        "",
        f'$cdmaterials "{MATERIAL_ROOT}/"',
        '$surfaceprop "flesh"',
        "$ambientboost",  # the shipping playermodel has AMBIENT_BOOST set
        "$eyeposition " + " ".join(f"{(v + 0.0):g}" for v in eyeposition),
        "",
        '// Same animation sets as the Gordon playermodel.',
    ]
    for include in includes:
        lines.append(f'$includemodel "{include}"')
    lines.append("")
    lines.append("// Attachments copied from the shipping playermodel.")
    for name, bone, pos, rot in attachments:
        # The compiled attachment stores RadianEuler (roll, pitch, yaw); $attachment's
        # rotate takes degrees as (pitch, yaw, roll) with yaw and roll negated. Measured
        # against this studiomdl: rotate 0 -80.1 -90 reproduces HL2's eyes attachment.
        roll, pitch, yaw = rot
        degrees = " ".join(
            f"{        math.degrees(v):.4f}" for v in (pitch, -yaw, -roll)
        )
        lines.append(
            f'$attachment "{name}" "{bone}" '
            f"{pos[0]:.4f} {pos[1]:.4f} {pos[2]:.4f} rotate {degrees}"
        )
    if ik:
        lines += ["", "// Same IK chains as the shipping playermodel (procedural hand/foot IK)."]
        for name, bone, knee in ik:
            lines.append(
                f'$ikchain "{name}" "{bone}" knee {knee[0]:.4f} {knee[1]:.4f} {knee[2]:.4f}'
            )
    if hitboxes:
        lines += ["", "// Hitboxes fitted to this mesh; without them studiomdl generates one box per", "// bone, all in the generic group, so headshots would not register as headshots.", '$hboxset "default"']
        for group, bone, low, high in hitboxes:
            lines.append(
                f'$hbox {group} "{bone}" '
                f"{low[0]:.4f} {low[1]:.4f} {low[2]:.4f} "
                f"{high[0]:.4f} {high[1]:.4f} {high[2]:.4f}"
            )
    if phys_smd:
        lines += [
            "",
            "// Ragdoll: one convex hull per physics solid, fitted to this mesh. Damping,",
            "// inertia and all 16 joint limits are the shipping playermodel's own values.",
            "// No $mass is set: the original .phy keeps studiomdl's 1 kg per solid, so the",
            "// body weighs the same as it always did.",
            f'$collisionjoints "{phys_smd}"',
            "{",
            f"\t$inertia {RAGDOLL_INERTIA:g}",
            f"\t$damping {RAGDOLL_DAMPING:g}",
            f"\t$rotdamping {RAGDOLL_ROTDAMPING:g}",
        ]
        for bone, limits in JOINT_LIMITS.items():
            for axis, (low, high) in zip(("x", "y", "z"), limits):
                lines.append(f'\t$jointconstrain "{bone}" {axis} limit {low:g} {high:g} 0')
        for bone in PHYSICS_MERGED:
            lines.append(f'\t$jointmerge "{PHYSICS_SOLIDS[0]}" "{bone}"')
        # How hard the ragdoll is dragged back toward the animation before it goes
        # limp, in the order the command reads them: min, max, timein, timeout, hold.
        # Only accepted inline, inside the collision block.
        lines.append("\t$animatedfriction " + " ".join(f"{v:g}" for v in RAGDOLL_ANIMFRICTION))
        lines.append("}")
    lines += ["", '// Bind-pose sequence: studiomdl refuses a model with no sequences, and the', '// engine uses "ragdoll" as the reference pose for ragdolls.', f'$sequence "ragdoll" "{STEM}_ref.smd" fps 30', ""]
    with open(path, "w", newline="\n") as f:
        f.write("\n".join(lines))


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fbx", default=os.path.join(DEFAULT_FBX, "source", "adrian shephard gmod.fbx"))
    parser.add_argument("--texture-dir", default=DEFAULT_TEXTURE_DIR)
    parser.add_argument("--mod-dir", default=DEFAULT_MOD_DIR)
    parser.add_argument("--skip-textures", action="store_true")
    parser.add_argument("--skip-compile", action="store_true")
    parser.add_argument(
        "--no-gordon-slot",
        action="store_true",
        help="only build the adrian_shephard_player model, leave the Gordon slot alone",
    )
    # Blender passes its own arguments first; everything after "--" is ours.
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    args = parser.parse_args(argv)

    import export_viewmodel_anims as eva

    mod_dir = os.path.abspath(args.mod_dir)
    reader, reference, attachments, includes, header, ik = reference_data(mod_dir)
    bone_index = {bone.name: i for i, bone in enumerate(reference.bones)}
    print(f"reference skeleton: {len(reference.bones)} bones, {len(attachments)} attachments")
    print(f"include animations: {includes}")

    body = import_fbx(args.fbx)
    print(f"imported {args.fbx}")
    geometry, _stats, weights = mesh_geometry(body, bone_index)
    markers = add_marker_triangles(geometry, reference.bones, name_of("humangrunt_sheet"))
    print(f"  {markers} bones kept with marker triangles")
    hitboxes = bone_hitboxes(body, reference.bones, bone_index, weights)
    print(f"  {len(hitboxes)} hitboxes fitted to the mesh")

    source_dir = os.path.join(mod_dir, "modelsrc", STEM)
    os.makedirs(source_dir, exist_ok=True)
    smd_path = os.path.join(source_dir, f"{STEM}_ref.smd")
    eva.write_skeleton_smd(smd_path, reference.bones, geometry=geometry)
    print(f"wrote modelsrc/{STEM}/{STEM}_ref.smd")

    collision = collision_geometry(body, reference.bones, bone_index, weights)
    phys_smd = f"{STEM}_phys.smd"
    write_collision_smd(os.path.join(source_dir, phys_smd), reference.bones, collision)
    print(f"  {len(collision) // 12} collision hulls -> modelsrc/{STEM}/{phys_smd}")

    qc_path = os.path.join(source_dir, f"{STEM}.qc")
    write_qc(qc_path, attachments, includes, header.header.eye_position, hitboxes, ik, phys_smd)
    print(f"wrote modelsrc/{STEM}/{STEM}.qc")

    if not args.skip_textures:
        build_materials(mod_dir, args.texture_dir)

    if args.skip_compile:
        return 0

    studiomdl = eva.find_studiomdl(None)
    if studiomdl is None:
        raise SystemExit("studiomdl.exe not found")
    proc = eva.run_studiomdl(studiomdl, mod_dir, qc_path, source_dir)
    output = proc.stdout + proc.stderr
    if "Completed" not in output:
        print("  ! studiomdl failed")
        for line in output.splitlines()[-15:]:
            print("    " + line.strip())
        return 1
    for line in output.splitlines():
        if "WARNING" in line or "ERROR" in line:
            print("  " + line.strip())

    # studiomdl hands the prompt back inside wineserver while it is still writing,
    # so wait for the outputs to stop changing before touching them.
    compiled = os.path.join(mod_dir, "models", OUT_MODEL_PATH[:-4])
    deadline, stable, last = time.time() + 240, 0, None
    while time.time() < deadline:
        sizes = tuple(
            os.path.getsize(compiled + extension) if os.path.isfile(compiled + extension) else -1
            for extension in MODEL_EXTENSIONS
        )
        if all(size > 0 for size in sizes) and sizes == last:
            stable += 1
            if stable >= 3:
                break
        else:
            stable = 0
        last = sizes
        time.sleep(1.0)
    print(f"compiled models/{OUT_MODEL_PATH}")

    if not args.no_gordon_slot:
        install_into_gordon_slot(mod_dir, compiled)
    install_physics(mod_dir, compiled)
    return 0


if __name__ == "__main__":
    sys.exit(main())
