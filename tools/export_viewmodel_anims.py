#!/usr/bin/env python3
"""Export Source viewmodel animations to SMD + QC so they can be edited in Blender.

Reads a compiled .mdl (plus everything it pulls animations from through
$includemodel) and writes one animation SMD per sequence plus a reference SMD and
a QC that ties them together:

    <out>/<model>/anims/<sequence>.smd   one animation SMD per sequence
    <out>/<model>/anims/ref.smd          bind pose + the model's own mesh
    <out>/<model>/<model>_anims.qc       QC referencing all of the above

<out> defaults to <mod>/Blender so nothing lands next to the QCs and meshes that
studiomdl compiles; pass --out to put them somewhere else.

Everything written is verified against the compiler: --verify recompiles the QC
with studiomdl and re-decodes the result, so the SMDs are known to reproduce the
source animation rather than merely looking plausible.

Runs under Blender's bundled Python (it needs numpy and the SourceIO addon
library, which parses the .mdl files):

    blender --background --python-exit-code 1 --python tools/export_viewmodel_anims.py -- v_deagle --verify

or directly:

    ~/.steam/debian-installation/steamapps/common/Blender/5.0/python/bin/python3.11 \
        tools/export_viewmodel_anims.py v_deagle --verify

Conventions this tool reproduces (all measured against the studiomdl that built
the models in this mod, see --self-test):

* SMD rotation numbers are RADIANS, not degrees. That is what Blender Source
  Tools writes and what this studiomdl expects; the hand-written SMDs in
  modelsrc/ are in radians too. Pass --degrees for a degrees-based toolchain.
* studiomdl bakes the SMD-space -> studio-space conversion (a +90 degree yaw)
  into the root bone of every sequence. It is not in the reference pose, so the
  root's animated position/rotation need it removed on export, otherwise it
  would be applied twice. Disable with --no-root-compensation.
* Animations store absolute bone orientations: angle = anim_value * bone_rotscale
  + bone_base_angle, per bone_setup.cpp.

The reference SMD carries the model's real mesh (positions, normals, UVs and
bone weights read straight out of the .vvd/.vtx), so importing the generated QC
gives the weapon and hands sitting on the rig rather than a floating skeleton.
Bones the mesh does not use (rig bones with no geometry) each get one small
marker triangle at the bind pose, because studiomdl drops bones that no triangle
references.
"""
from __future__ import annotations

import argparse
import glob
import importlib.util
import math
import os
import re
import struct
import subprocess
import sys
import time
from dataclasses import dataclass, field

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# studiomdl rotates SMD space into studio space by this yaw and bakes it into the
# root bone of every sequence (verified with --self-test against this mod's
# studiomdl: a root written as (0.3, 0.4, 0.5) rad reads back as R90z * that).
ROOT_YAW = math.pi / 2.0


# --------------------------------------------------------------------------
# Source engine math (mathlib.cpp semantics)
#
# Angles are RadianEuler: (x = roll about X, y = pitch about Y, z = yaw about Z).
# Matrices are row-vector matrices, exactly like the engine's matrix3x4_t.
# --------------------------------------------------------------------------
def angle_quaternion(e) -> tuple[float, float, float, float]:
    """AngleQuaternion(): RadianEuler -> quaternion."""
    sr, cr = math.sin(e[0] * 0.5), math.cos(e[0] * 0.5)
    sp, cp = math.sin(e[1] * 0.5), math.cos(e[1] * 0.5)
    sy, cy = math.sin(e[2] * 0.5), math.cos(e[2] * 0.5)
    sr_cp, cr_sp = sr * cp, cr * sp
    cr_cp, sr_sp = cr * cp, sr * sp
    return (
        sr_cp * cy - cr_sp * sy,
        cr_sp * cy + sr_cp * sy,
        cr_cp * sy - sr_sp * cy,
        cr_cp * cy + sr_sp * sy,
    )


def quaternion_matrix(q):
    """QuaternionMatrix(): quaternion -> 3x3 row-vector matrix."""
    x, y, z, w = q
    return (
        (1 - 2 * y * y - 2 * z * z, 2 * x * y - 2 * w * z, 2 * x * z + 2 * w * y),
        (2 * x * y + 2 * w * z, 1 - 2 * x * x - 2 * z * z, 2 * y * z - 2 * w * x),
        (2 * x * z - 2 * w * y, 2 * y * z + 2 * w * x, 1 - 2 * x * x - 2 * y * y),
    )


def matrix_angles(m) -> tuple[float, float, float]:
    """MatrixAngles(): 3x3 row-vector matrix -> RadianEuler."""
    forward = (m[0][0], m[1][0], m[2][0])
    left = (m[0][1], m[1][1], m[2][1])
    xy_dist = math.hypot(forward[0], forward[1])
    if xy_dist > 0.001:
        yaw = math.atan2(forward[1], forward[0])
        pitch = math.atan2(-forward[2], xy_dist)
        roll = math.atan2(left[2], m[2][2])
    else:  # gimbal lock: only yaw survives
        yaw = math.atan2(-left[0], left[1])
        pitch = math.atan2(-forward[2], xy_dist)
        roll = 0.0
    return (roll, pitch, yaw)


def quat_to_euler(q) -> tuple[float, float, float]:
    return matrix_angles(quaternion_matrix(q))


def quat_mul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def rotate_z(v, radians: float):
    """Rotate an engine-space vector about Z (yaw)."""
    c, s = math.cos(radians), math.sin(radians)
    return (v[0] * c - v[1] * s, v[0] * s + v[1] * c, v[2])


def angle_distance(a, b) -> float:
    """Largest per-component difference between two RadianEulers, in radians."""
    return max(
        abs(((a[i] - b[i]) + math.pi) % (2.0 * math.pi) - math.pi) for i in range(3)
    )


# --------------------------------------------------------------------------
# SourceIO (MDL parser) bootstrap
# --------------------------------------------------------------------------
def load_sourceio() -> None:
    """Import the SourceIO addon library without needing Blender itself."""
    if "SourceIO" in sys.modules:
        return
    patterns = [
        "~/.config/blender/*/scripts/addons/sourceio",
        "~/.steam/*/steamapps/common/Blender/*/scripts/addons/sourceio",
        "~/.local/share/blender/*/scripts/addons/sourceio",
    ]
    found: list[str] = []
    for pattern in patterns:
        found.extend(glob.glob(os.path.expanduser(pattern)))
    found = [p for p in found if os.path.isfile(os.path.join(p, "__init__.py"))]
    if not found:
        sys.exit(
            "Could not find the SourceIO Blender addon. Install it from "
            "https://github.com/REDxEYE/SourceIO into Blender's addons folder."
        )
    pkg = sorted(found, key=lambda p: [int(x) if x.isdigit() else x for x in re.split(r"[\\/]", p)])[-1]
    spec = importlib.util.spec_from_file_location(
        "SourceIO", os.path.join(pkg, "__init__.py"), submodule_search_locations=[pkg]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["SourceIO"] = module
    spec.loader.exec_module(module)


def mdl_classes():
    load_sourceio()
    # v49 must be imported first: v44 imports flex expressions from it.
    from SourceIO.library.models.mdl.v49.mdl_file import MdlV49
    from SourceIO.library.models.mdl.v44.mdl_file import MdlV44

    return MdlV44, MdlV49


# --------------------------------------------------------------------------
# Source engine file lookup (loose files + VPK archives)
# --------------------------------------------------------------------------
class Vpk:
    """Minimal VPK reader (v1/v2 directory format)."""

    def __init__(self, dir_path: str):
        self.dir_path = dir_path
        self.entries: dict[str, tuple[int, int, int, bytes]] = {}
        with open(dir_path, "rb") as f:
            signature, version, tree_size = struct.unpack("<III", f.read(12))
            if signature != 0x55AA1234:
                raise ValueError(f"{dir_path} is not a VPK archive")
            self.version = version
            if version == 2:
                f.read(16)  # file data / md5 / signature section sizes
            tree = f.read(tree_size)
        self._parse(tree)

    def _parse(self, tree: bytes) -> None:
        pos = 0
        size = len(tree)

        def cstr() -> bytes:
            nonlocal pos
            end = tree.index(b"\x00", pos)
            value = tree[pos:end]
            pos = end + 1
            return value

        while pos < size:
            ext = cstr()
            if not ext:
                break
            while True:
                path = cstr()
                if not path:
                    break
                while True:
                    name = cstr()
                    if not name:
                        break
                    crc, preload, archive, offset, length, term = struct.unpack_from("<IHHIIH", tree, pos)
                    pos += 18
                    if term != 0xFFFF:
                        raise ValueError(f"bad VPK entry in {self.dir_path}")
                    preload_data = tree[pos : pos + preload]
                    pos += preload
                    full = "/".join(
                        p.decode("latin1") for p in (path, name + b"." + ext) if p
                    )
                    self.entries[full.lower()] = (archive, offset, length, preload_data)

    def read(self, game_path: str) -> bytes | None:
        entry = self.entries.get(game_path.lower().replace("\\", "/"))
        if entry is None:
            return None
        archive, offset, length, preload = entry
        data = bytearray(preload)
        if archive != 0x7FFF and length:
            base = self.dir_path[: -len("_dir.vpk")]
            chunk = f"{base}_{archive:03d}.vpk" if archive else f"{base}_000.vpk"
            with open(chunk, "rb") as f:
                f.seek(offset)
                data += f.read(length)
        return bytes(data)


class GameFiles:
    """Resolves Source game paths from loose files and VPKs."""

    def __init__(self, mod_dir: str, extra_game_dirs: list[str] | None = None):
        self.mod_dir = mod_dir
        self.game_dirs = [mod_dir]
        self._vpks: list[Vpk] | None = None
        self.extra_game_dirs = extra_game_dirs or []

    def _steam_roots(self) -> list[str]:
        roots = []
        for pattern in (
            "~/.steam/debian-installation/steamapps/common",
            "~/.steam/steam/steamapps/common",
            "~/.local/share/Steam/steamapps/common",
            "~/.steam/steam/SteamApps/common",
        ):
            path = os.path.expanduser(pattern)
            if os.path.isdir(path):
                roots.append(path)
        # gameinfo's all_source_engine_paths resolves next to the mod directory
        parent = os.path.dirname(os.path.abspath(self.mod_dir))
        if os.path.isdir(os.path.join(parent, "Half-Life 2")):
            roots.append(parent)
        return roots

    def _load_vpks(self) -> list[Vpk]:
        if self._vpks is not None:
            return self._vpks
        vpks = []
        search = list(self.extra_game_dirs)
        for root in self._steam_roots():
            search.extend(glob.glob(os.path.join(root, "*", "*_dir.vpk")))
            search.extend(glob.glob(os.path.join(root, "*", "*", "*_dir.vpk")))

        # Prefer hl2 content, then episodic/portal/platform, then everything else
        def rank(path: str) -> int:
            low = path.lower()
            for i, token in enumerate(("hl2_misc", "hl2_pak", "ep2_pak", "ep1_pak", "portal_pak", "platform_misc")):
                if token in low:
                    return i
            return 99

        seen = set()
        for path in sorted(set(p for p in search if p.lower().endswith("_dir.vpk")), key=rank):
            key = os.path.realpath(path)
            if key in seen:
                continue
            seen.add(key)
            try:
                vpks.append(Vpk(path))
            except (OSError, ValueError) as exc:
                print(f"  ! skipping {path}: {exc}")
        self._vpks = vpks
        return vpks

    def find_path(self, game_path: str) -> str | None:
        rel = game_path.replace("\\", "/").lstrip("/")
        for base in self.game_dirs:
            candidate = os.path.join(base, rel)
            if os.path.isfile(candidate):
                return candidate
        for root in self._game_roots_loose():
            candidate = os.path.join(root, rel)
            if os.path.isfile(candidate):
                return candidate
        return None

    def _game_roots_loose(self) -> list[str]:
        roots = []
        for root in self._steam_roots():
            for game in glob.glob(os.path.join(root, "*")):
                if os.path.isdir(game):
                    roots.append(game)
                    for sub in glob.glob(os.path.join(game, "*")):
                        if os.path.isdir(sub) and os.path.isfile(os.path.join(sub, "gameinfo.txt")):
                            roots.append(sub)
        return roots

    def read(self, game_path: str) -> bytes | None:
        path = self.find_path(game_path)
        if path:
            with open(path, "rb") as f:
                return f.read()
        for vpk in self._load_vpks():
            data = vpk.read(game_path)
            if data is not None:
                return data
        return None


# --------------------------------------------------------------------------
# Model loading
# --------------------------------------------------------------------------
@dataclass
class Bone:
    name: str
    parent: int
    pos: tuple[float, float, float]
    rot: tuple[float, float, float]  # RadianEuler


@dataclass
class Sequence:
    name: str
    fps: float
    frame_count: int
    looping: bool
    activity: str
    frames: dict[str, list]  # bone name -> [(pos, quat)] per frame


@dataclass
class MeshInfo:
    """One mesh of the model's default LOD, as described by the .mdl."""

    material_index: int
    vertex_start: int  # first vertex inside the .vvd
    vertex_count: int


@dataclass
class Model:
    name: str
    version: int
    bones: list[Bone]
    sequences: list[Sequence] = field(default_factory=list)
    includes: list[str] = field(default_factory=list)
    bone_names: set[str] = field(default_factory=set)
    unresolved: list[str] = field(default_factory=list)
    materials: list[str] = field(default_factory=list)
    meshes: list[MeshInfo] = field(default_factory=list)


def Buffer(data: bytes):
    from SourceIO.library.utils import MemoryBuffer

    return MemoryBuffer(data)


class MdlReader:
    def __init__(self, files: GameFiles):
        self.files = files
        self._MdlV44, self._MdlV49 = mdl_classes()
        self._cache: dict[str, Model | None] = {}

    def forget(self, game_path: str) -> None:
        self._cache.pop(game_path.lower().replace("\\", "/"), None)

    def load(self, game_path: str) -> Model | None:
        key = game_path.lower().replace("\\", "/")
        if key in self._cache:
            return self._cache[key]
        if os.path.isabs(game_path) and os.path.isfile(game_path):
            with open(game_path, "rb") as f:
                data = f.read()
        else:
            data = self.files.read(key)
        if data is None:
            print(f"  ! could not find {game_path}")
            self._cache[key] = None
            return None
        version = int.from_bytes(data[4:8], "little")
        cls = self._MdlV49 if version >= 45 else self._MdlV44
        try:
            mdl = cls.from_buffer(Buffer(data))
        except Exception as exc:  # malformed / unsupported model
            print(f"  ! failed to parse {game_path}: {exc}")
            self._cache[key] = None
            return None

        bones = [
            Bone(b.name, b.parent_id, tuple(float(v) for v in b.position),
                 tuple(float(v) for v in b.rotation))
            for b in mdl.bones
        ]
        model = Model(key, version, bones, includes=list(mdl.include_models))
        model.bone_names = {b.name for b in bones}
        model.materials = [(m.name or "").strip() for m in (getattr(mdl, "materials", None) or [])]
        # Geometry only exists for the default bodygroup/LOD; that is what an
        # animator needs as a reference and what the .vvd describes.
        if version > 36 and getattr(mdl, "body_parts", None):
            for body_model in mdl.body_parts[0].models[:1]:
                for mesh in body_model.meshes:
                    model.meshes.append(
                        MeshInfo(
                            mesh.material_index,
                            body_model.vertex_offset + mesh.vertex_index_start,
                            mesh.vertex_count,
                        )
                    )

        for seq in mdl.sequences:
            merged: dict[str, list] = {}
            fps = 30.0
            frame_count = 0
            looping = bool(int(seq.flags) & 1)
            for desc_index in seq.anim_desc_indices:
                if desc_index >= len(mdl.anim_descs):
                    continue
                desc = mdl.anim_descs[desc_index]
                frames = mdl.animations[desc_index]
                if not frames:
                    continue
                fps = desc.fps or fps
                frame_count = max(frame_count, int(desc.frame_count))
                looping = looping or bool(int(desc.flags) & 1)
                for bone_name, track in frames.items():
                    merged[bone_name] = [
                        (tuple(float(v) for v in track["pos"][i]),
                         tuple(float(v) for v in track["rot"][i]))
                        for i in range(len(track["pos"]))
                    ]
            if not merged:
                continue
            model.sequences.append(
                Sequence(
                    name=seq.name,
                    fps=fps,
                    frame_count=frame_count or max(len(v) for v in merged.values()),
                    looping=looping,
                    activity=(seq.activity_name or "").strip(),
                    frames=merged,
                )
            )
        self._cache[key] = model
        return model

    def include_chain(self, model: Model) -> list[Model]:
        """model plus every model reachable through $includemodel, in order."""
        chain = [model]
        seen = {model.name}
        queue = list(model.includes)
        while queue:
            include = queue.pop(0).lower().replace("\\", "/")
            if include in seen:
                continue
            seen.add(include)
            parent = self.load(include)
            if parent is None:
                model.unresolved.append(include)
                continue
            chain.append(parent)
            queue.extend(parent.includes)
        return chain

    def merged_skeleton(self, models: list[Model]) -> list[Bone]:
        """Bones of every model in the chain, de-duplicated by name."""
        bones: list[Bone] = []
        index_by_name: dict[str, int] = {}
        for model in models:
            for bone in model.bones:
                if bone.name in index_by_name:
                    continue
                index_by_name[bone.name] = len(bones)
                bones.append(Bone(bone.name, -1, bone.pos, bone.rot))
        for i, bone in enumerate(bones):
            for model in models:
                match = next((b for b in model.bones if b.name == bone.name), None)
                if match is None:
                    continue
                parent_name = None
                if 0 <= match.parent < len(model.bones):
                    parent_name = model.bones[match.parent].name
                bones[i] = Bone(bone.name, index_by_name.get(parent_name, -1), bone.pos, bone.rot)
                break
        return bones

    def sequences_with_inherited(self, models: list[Model]) -> list[tuple[Sequence, str]]:
        """(sequence, path of the model it is defined in), own sequences first."""
        sequences: list[tuple[Sequence, str]] = []
        seen: set[str] = set()
        for model in models:
            for seq in model.sequences:
                if seq.name in seen:
                    continue
                seen.add(seq.name)
                sequences.append((seq, model.name))
        return sequences


# --------------------------------------------------------------------------
# Mesh geometry (for the reference SMD)
# --------------------------------------------------------------------------
VVD_VERTEX_SIZE = 48  # float weight[3], uint8 bone[3] + count, Vector pos/nrm, Vector2 uv


def read_vvd(data: bytes) -> list[tuple]:
    """Per-vertex (position, normal, uv, [(bone index, weight)...]) from a .vvd."""
    fixup_count, fixup_start, vertex_start, tangent_start = struct.unpack_from("<4I", data, 48)
    end = tangent_start or fixup_start or len(data)
    if end <= vertex_start:
        end = len(data)
    count = (end - vertex_start) // VVD_VERTEX_SIZE
    vertices = []
    for i in range(count):
        offset = vertex_start + i * VVD_VERTEX_SIZE
        weights = struct.unpack_from("<3f", data, offset)
        bone_ids = data[offset + 12 : offset + 15]
        bone_count = data[offset + 15]
        position = struct.unpack_from("<3f", data, offset + 16)
        normal = struct.unpack_from("<3f", data, offset + 28)
        uv = struct.unpack_from("<2f", data, offset + 40)
        links = [
            (bone_ids[j], weights[j])
            for j in range(min(int(bone_count), 3))
            if weights[j] > 0.0
        ]
        vertices.append((position, normal, uv, links))
    return vertices


def vtx_triangles(data: bytes) -> list[tuple[int, list[int]]]:
    """(material index, three mesh-local vertex indices) per triangle of LOD 0."""
    import numpy as np

    for module, name in (("v7", "Vtx"), ("v107", "Vtx")):
        try:
            parser = __import__(f"SourceIO.library.models.vtx.{module}.vtx", fromlist=[name]).Vtx
            vtx = parser.from_buffer(Buffer(data))
            meshes = vtx.body_parts[0].models[0].model_lods[0].meshes
            break
        except Exception:  # pragma: no cover - fall back to the other layout
            vtx = None
    if vtx is None:
        return []

    triangles: list[tuple[int, list[int]]] = []
    for mesh_index, mesh in enumerate(meshes):
        for group in mesh.strip_groups:
            local = [int(np.asarray(v["original_mesh_vertex_index"]).ravel()[0]) for v in group.vertexes]
            indices = [local[int(i)] for i in group.indices]
            if all(int(s.flags) & 1 for s in group.strips):  # triangle list
                for i in range(0, len(indices) - 2, 3):
                    triangles.append((mesh_index, indices[i : i + 3]))
            else:  # triangle strip; flip winding on odd triangles
                for i in range(len(indices) - 2):
                    tri = indices[i : i + 3]
                    triangles.append((mesh_index, tri[::-1] if i % 2 else tri))
    return triangles


def read_geometry(reader: "MdlReader", model: Model, bone_index: dict[str, int]) -> list[tuple]:
    """(material name, three corner tuples) for the model's own mesh.

    Each corner is (position, normal, uv, [(bone index in the merged rig, weight)]).
    Vertex and triangle data live in the .vvd/.vtx next to the .mdl, which for
    stock models means a VPK lookup.
    """
    if not model.meshes or model.version <= 36:
        return []
    stem = os.path.splitext(model.name)[0]
    vvd = reader.files.read(stem + ".vvd")
    vtx = None
    for suffix in (".dx90.vtx", ".vtx", ".dx80.vtx", ".sw.vtx"):
        vtx = reader.files.read(stem + suffix)
        if vtx:
            break
    if not vvd or not vtx:
        return []

    vertices = read_vvd(vvd)
    triangles = vtx_triangles(vtx)
    if not vertices or not triangles:
        return []

    bone_names = [b.name for b in model.bones]
    out = []
    for mesh_index, corners in triangles:
        if mesh_index >= len(model.meshes):
            continue
        mesh = model.meshes[mesh_index]
        material = ""
        if 0 <= mesh.material_index < len(model.materials):
            material = model.materials[mesh.material_index]
        corners_out = []
        for corner in corners:
            index = mesh.vertex_start + corner
            if not 0 <= index < len(vertices):
                corners_out = []
                break
            position, normal, uv, links = vertices[index]
            weights = []
            for bone_id, weight in links:
                if 0 <= bone_id < len(bone_names):
                    merged = bone_index.get(bone_names[bone_id])
                    if merged is not None:
                        weights.append((merged, weight))
            if not weights:
                corners_out = []
                break
            corners_out.append((position, normal, uv, weights))
        if len(corners_out) == 3:
            out.append((material or f"mesh{mesh_index}", corners_out))
    return out


# --------------------------------------------------------------------------
# SMD writers
# --------------------------------------------------------------------------
def safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_") or "unnamed"


def is_root(bones: list[Bone], index: int) -> bool:
    return bones[index].parent < 0


def smd_angles(e, degrees: bool) -> tuple[float, float, float]:
    return tuple(math.degrees(v) for v in e) if degrees else e


MARKER_SIZE = 0.4  # units, for bones the real geometry does not use


def bind_positions(bones: list[Bone]) -> list[tuple[float, float, float]]:
    """Bind-pose position of every bone in model space.

    SMD/MDL bone positions are relative to the parent bone's frame, so they have
    to be composed down the chain before they mean anything absolute. The mesh
    in the .vvd is absolute, which is why geometry can be written verbatim.
    """
    import numpy as np

    matrices: list = [None] * len(bones)

    def compose(index: int, depth: int = 0):
        if matrices[index] is not None:
            return matrices[index]
        bone = bones[index]
        local = np.eye(4)
        local[:3, :3] = np.array(quaternion_matrix(angle_quaternion(bone.rot)))
        local[:3, 3] = bone.pos
        parent = bone.parent
        if parent < 0 or parent >= len(bones) or depth > len(bones):
            matrices[index] = local
        else:
            matrices[index] = compose(parent, depth + 1) @ local
        return matrices[index]

    return [tuple(float(v) for v in compose(i)[:3, 3]) for i in range(len(bones))]


def smd_triangle(lines: list[str], material: str, corners: list[tuple]) -> None:
    lines.append(material)
    for position, normal, uv, weights in corners:
        parent, weight = weights[0]
        text = " %d %.4f %.4f %.4f %.4f %.4f %.4f %.4f %.4f %d" % (
            parent, position[0], position[1], position[2],
            normal[0], normal[1], normal[2], uv[0], uv[1], len(weights),
        )
        for bone, bone_weight in weights:
            text += " %d %.6f" % (bone, bone_weight)
        lines.append(text)


def write_skeleton_smd(
    path: str,
    bones: list[Bone],
    degrees: bool = False,
    geometry: list[tuple] | None = None,
) -> int:
    """Write the bind pose, with the model's mesh as geometry when available."""
    lines = ["version 1", "nodes"]
    for i, bone in enumerate(bones):
        lines.append(f'{i} "{bone.name}" {bone.parent}')
    lines += ["end", "skeleton", "time 0"]
    for i, bone in enumerate(bones):
        rot = smd_angles(bone.rot, degrees)
        lines.append(
            "%d %.6f %.6f %.6f %.6f %.6f %.6f"
            % (i, bone.pos[0], bone.pos[1], bone.pos[2], rot[0], rot[1], rot[2])
        )
    lines += ["end"]
    if not bones:
        return 0

    lines.append("triangles")
    weighted: set[int] = set()
    for material, corners in geometry or []:
        smd_triangle(lines, material, corners)
        weighted.update(bone for _p, _n, _uv, weights in corners for bone, _w in weights)

    # A SMD with no triangles makes studiomdl drop every bone, so any bone the
    # mesh does not use gets one small triangle of its own, sitting at the bone
    # rather than spread out over a grid. Each marker gets its own material
    # name: with all triangles in a single material group this studiomdl crashes
    # (EXCEPTION_ACCESS_VIOLATION) on rigs like v_ar2_organic's.
    absolute = bind_positions(bones)
    for i, bone in enumerate(bones):
        if i in weighted:
            continue
        x, y, z = absolute[i]
        corners = [
            ((x + MARKER_SIZE, y, z), (0.0, 0.0, 1.0), (0.0, 0.0), [(i, 1.0)]),
            ((x, y + MARKER_SIZE, z), (0.0, 0.0, 1.0), (1.0, 0.0), [(i, 1.0)]),
            ((x, y, z + MARKER_SIZE), (0.0, 0.0, 1.0), (0.0, 1.0), [(i, 1.0)]),
        ]
        smd_triangle(lines, f"bone_{safe_filename(bone.name) or i}", corners)
    lines.append("end")
    with open(path, "w", newline="\n") as f:
        # studiomdl reads one token past the closing "end" and reports EOF as a
        # parse error, so finish the file with a blank line.
        f.write("\n".join(lines) + "\n\n")
    return len(geometry or [])


def write_animation_smd(
    path: str,
    bones: list[Bone],
    sequence: Sequence,
    degrees: bool = False,
    root_compensation: float = 0.0,
) -> int:
    """Write one animation SMD; returns the number of frames written."""
    lines = ["version 1", "nodes"]
    for i, bone in enumerate(bones):
        lines.append(f'{i} "{bone.name}" {bone.parent}')
    lines += ["end", "skeleton"]

    frames = max(1, sequence.frame_count)
    for frame in range(frames):
        lines.append(f"time {frame}")
        for i, bone in enumerate(bones):
            track = sequence.frames.get(bone.name)
            if track:
                pos, quat = track[min(frame, len(track) - 1)]
            else:
                pos, quat = bone.pos, angle_quaternion(bone.rot)
            if root_compensation and is_root(bones, i):
                # studiomdl re-applies this yaw to the root; remove it here so a
                # recompile reproduces exactly what is in the compiled model.
                pos = rotate_z(pos, -root_compensation)
                quat = quat_mul(angle_quaternion((0.0, 0.0, -root_compensation)), quat)
            rot = smd_angles(quat_to_euler(quat), degrees)
            lines.append(
                "%d %.6f %.6f %.6f %.6f %.6f %.6f"
                % (i, pos[0], pos[1], pos[2], rot[0], rot[1], rot[2])
            )
    lines += ["end"]
    with open(path, "w", newline="\n") as f:
        f.write("\n".join(lines) + "\n\n")
    return frames


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------
def material_paths(mod_dir: str, stem: str) -> list[str]:
    """$cdmaterials paths the model's materials live in.

    Taken from the mod's own QC when there is one, so the reference SMD keeps the
    same material search paths as the shipping model.
    """
    qc = os.path.join(mod_dir, "modelsrc", stem, f"{stem}.qc")
    paths: list[str] = []
    if os.path.isfile(qc):
        with open(qc, errors="replace") as f:
            for line in f:
                text = line.strip()
                if text.lower().startswith("$cdmaterials"):
                    match = re.search(r'"([^"]+)"', text)
                    if match:
                        paths.append(match.group(1))
    if not paths:
        guess = f"models/weapons/{stem}"
        if os.path.isdir(os.path.join(mod_dir, "materials", guess)):
            paths.append(guess + "/")
    return paths


def export_model(reader: MdlReader, game_path: str, out_root: str, args) -> dict | None:
    model = reader.load(game_path)
    if model is None:
        return None

    chain = reader.include_chain(model)
    bones = reader.merged_skeleton(chain)

    stem = os.path.splitext(os.path.basename(model.name))[0]
    out_dir = os.path.join(out_root, stem)
    anims_dir = os.path.join(out_dir, "anims")
    os.makedirs(anims_dir, exist_ok=True)

    # The reference SMD carries the model's real mesh so the imported rig has
    # something to animate against instead of floating bone markers.
    bone_index = {bone.name: i for i, bone in enumerate(bones)}
    result_geometry: list[tuple] = []
    for source in chain:
        result_geometry = read_geometry(reader, source, bone_index)
        if result_geometry:
            break

    write_skeleton_smd(
        os.path.join(anims_dir, "ref.smd"), bones, args.degrees, result_geometry
    )

    compensation = 0.0 if args.no_root_compensation else ROOT_YAW
    seq_entries = []
    for seq, owner in reader.sequences_with_inherited(chain):
        if seq.name.lstrip("@").lower() == "ref":
            continue  # bind pose; already covered by the reference SMD
        filename = safe_filename(seq.name.lstrip("@")) + ".smd"
        frames = write_animation_smd(
            os.path.join(anims_dir, filename), bones, seq, args.degrees, compensation
        )
        seq_entries.append((seq, filename, frames, owner))

    qc_path = os.path.join(out_dir, f"{stem}_anims.qc")
    with open(qc_path, "w", newline="\n") as f:
        f.write(f"// Generated by tools/export_viewmodel_anims.py from {game_path}\n")
        f.write(f'// Compiles to models/sl_animtest/{stem}.mdl, not to {game_path}\n')
        f.write("// Import in Blender with Blender Source Tools\n")
        f.write("// (File > Import > Source Engine QC) for the rig plus one action per sequence.\n")
        # Never write to the shipping path: this QC is a scratch copy for editing
        # and for --verify, so a compile can't overwrite the real model.
        f.write(f'$modelname "sl_animtest/{stem}.mdl"\n')
        for path in material_paths(args.mod_dir, stem):
            f.write(f'$cdmaterials "{path}"\n')
        f.write(f"$model \"{stem}\" \"anims/ref.smd\"\n\n")
        for seq, filename, _frames, _owner in seq_entries:
            line = f'$sequence "{seq.name}" "anims/{filename}" fps {seq.fps:g}'
            if seq.activity and seq.activity.upper().startswith("ACT_"):
                line += f" {seq.activity} 1"
            if seq.looping:
                line += " loop"
            f.write(line + "\n")

    return {
        "model": model,
        "chain": chain,
        "bones": bones,
        "out_dir": out_dir,
        "qc": qc_path,
        "sequences": seq_entries,
        "geometry": result_geometry,
    }


# --------------------------------------------------------------------------
# Verification: recompile the QC and compare the decoded animation
# --------------------------------------------------------------------------
def find_studiomdl(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    patterns = [
        "~/.steam/debian-installation/steamapps/common/Half-Life 2/bin/studiomdl.exe",
        "~/.steam/steam/steamapps/common/Half-Life 2/bin/studiomdl.exe",
        "~/.local/share/Steam/steamapps/common/Half-Life 2/bin/studiomdl.exe",
        "~/.steam/*/steamapps/common/*/bin/studiomdl.exe",
        "~/.local/share/Steam/steamapps/common/*/bin/studiomdl.exe",
    ]
    for pattern in patterns:
        hits = glob.glob(os.path.expanduser(pattern))
        if hits:
            return hits[0]
    return None


def run_studiomdl(studiomdl: str, game_dir: str, qc_path: str, cwd: str) -> subprocess.CompletedProcess:
    command = [studiomdl, "-nop4", "-game", game_dir, os.path.basename(qc_path)]
    if os.name != "nt" and os.path.basename(studiomdl).lower().endswith(".exe"):
        command.insert(0, "wine")
    env = dict(os.environ, WINEDEBUG="-all")
    return subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=900)


def decode_sequence(reader: MdlReader, game_path: str, sequence: str):
    """Absolute pose per bone per frame of one sequence, from a compiled model."""
    model = reader.load(game_path)
    if model is None:
        return None
    seq = next((s for s in model.sequences if s.name.lstrip("@") == sequence.lstrip("@")), None)
    if seq is None:
        return None
    pose = {}
    bind = {b.name: b for b in model.bones}
    for frame in range(seq.frame_count):
        for name, bone in bind.items():
            track = seq.frames.get(name)
            if track:
                pos, quat = track[min(frame, len(track) - 1)]
            else:
                pos, quat = bone.pos, angle_quaternion(bone.rot)
            pose[(name, frame)] = (pos, quat_to_euler(quat))
    return seq, pose


def verify_export(reader: MdlReader, result: dict, game_dir: str, studiomdl: str) -> bool:
    qc_path = result["qc"]
    gcd = os.path.dirname(qc_path)
    print(f"  verifying: {os.path.basename(studiomdl)} {os.path.basename(qc_path)}")
    model_name = re.search(r'\$modelname\s+"([^"]+)"', open(qc_path).read())
    if not model_name:
        print("  ! no $modelname in QC")
        return False
    compiled = os.path.join(game_dir, "models", model_name.group(1).replace("\\", "/"))
    # Clear stale scratch output so the check below can't read an old build. This
    # only ever touches models/sl_animtest/, never a shipping model.
    for ext in (".mdl", ".vvd", ".dx80.vtx", ".dx90.vtx", ".sw.vtx"):
        stale = compiled[: -len(".mdl")] + ext
        if os.path.isfile(stale):
            os.remove(stale)

    proc = run_studiomdl(studiomdl, game_dir, qc_path, gcd)
    # studiomdl occasionally dies inside wine on a cold start; retry twice before
    # reporting a real compile failure.
    for _attempt in range(2):
        if "Completed" in (proc.stdout + proc.stderr):
            break
        proc = run_studiomdl(studiomdl, game_dir, qc_path, gcd)
    if proc.returncode != 0 or "Completed" not in (proc.stdout + proc.stderr):
        print("  ! studiomdl failed")
        for line in (proc.stdout + proc.stderr).splitlines()[-12:]:
            print("    " + line.strip())
        return False

    # studiomdl under wine can hand the prompt back while the real work (and its
    # writes) are still running inside wineserver, so wait for the .mdl to settle.
    sibling = [compiled, compiled[:-4] + ".vvd", compiled[:-4] + ".dx90.vtx"]
    deadline = time.time() + 240
    stable = 0
    last = None
    while time.time() < deadline:
        sizes = tuple(os.path.getsize(p) if os.path.isfile(p) else -1 for p in sibling)
        if all(s > 0 for s in sizes) and sizes == last:
            stable += 1
            if stable >= 3:
                break
        else:
            stable = 0
        last = sizes
        time.sleep(1.0)
    if not os.path.isfile(compiled):
        print(f"  ! compiled model missing: {compiled}")
        return False
    reader.forget(compiled)

    ok = True
    checked = 0
    worst = (0.0, "", 0)
    for seq, _filename, _frames, owner in result["sequences"]:
        before = decode_sequence(reader, owner, seq.name)
        after = decode_sequence(reader, compiled, seq.name)
        if before is None or after is None:
            print(f"  ! {seq.name}: sequence missing after recompile")
            ok = False
            continue
        _seq_a, pose_a = before
        _seq_b, pose_b = after
        checked += 1
        for key in pose_a:
            if key not in pose_b:
                continue
            pos_a, rot_a = pose_a[key]
            pos_b, rot_b = pose_b[key]
            drot = angle_distance(rot_a, rot_b)
            dpos = max(abs(pos_a[i] - pos_b[i]) for i in range(3))
            if drot > worst[0]:
                worst = (drot, key[0], key[1])
            if drot > 0.01 or dpos > 0.05:  # 0.6 deg / 0.05 units
                ok = False
    if checked == 0:
        print("  ! nothing verified")
        return False
    print(
        "  %s: %d sequences round-tripped, worst bone rotation delta %.4f deg (%s frame %d)"
        % ("OK" if ok else "MISMATCH", checked, math.degrees(worst[0]), worst[1] or "-", worst[2])
    )
    return ok


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def resolve_model_paths(names: list[str], files: GameFiles) -> list[str]:
    paths = []
    for name in names:
        if os.path.isfile(name) or name.lower().endswith(".mdl") and os.path.sep in name:
            paths.append(name)
            continue
        normalized = name.replace("\\", "/")
        if normalized.lower().endswith(".mdl"):
            paths.append(normalized)
            continue
        paths.append(f"models/weapons/{normalized}.mdl")
    return paths


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("models", nargs="*", help="model names (v_deagle) or game paths (models/weapons/v_357.mdl)")
    parser.add_argument("--mod-dir", default=REPO_ROOT, help="mod directory containing models/ (default: repo root)")
    parser.add_argument("--out", default=None, help="output directory (default: <mod>/Blender)")
    parser.add_argument("--game-dir", action="append", default=[], help="extra directory to search for game files")
    parser.add_argument("--degrees", action="store_true",
                        help="write SMD rotations in degrees instead of the radians this toolchain uses")
    parser.add_argument("--no-root-compensation", action="store_true",
                        help="do not remove the root bone yaw that studiomdl bakes in during compile")
    parser.add_argument("--verify", action="store_true",
                        help="recompile the generated QC with studiomdl and compare the result")
    parser.add_argument("--studiomdl", default=None, help="path to studiomdl.exe (for --verify)")
    parser.add_argument("--self-test", action="store_true",
                        help="check the rotation math and print the toolchain conventions")
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()

    out_root = args.out or os.path.join(args.mod_dir, "Blender")
    files = GameFiles(args.mod_dir, args.game_dir)
    reader = MdlReader(files)

    studiomdl = find_studiomdl(args.studiomdl) if args.verify else None
    if args.verify and studiomdl is None:
        print("! --verify needs studiomdl.exe; pass --studiomdl")

    failed = False
    for game_path in resolve_model_paths(args.models, files):
        print(f"Exporting {game_path}")
        result = export_model(reader, game_path, out_root, args)
        if result is None:
            failed = True
            continue
        model = result["model"]
        print(
            f"  bones: {len(result['bones'])} ({len(model.bones)} own, "
            f"{len(result['bones']) - len(model.bones)} from includes)"
            f"  sequences: {len(result['sequences'])}"
        )
        if result["geometry"]:
            print(f"  reference mesh: {len(result['geometry'])} triangles")
        else:
            print("  ! no mesh found for the reference SMD; bones will appear as markers only")
        if model.includes:
            print(f"  animations inherited from: {', '.join(model.includes)}")
        for missing in model.unresolved:
            print(f"  ! include model not found: {missing}")
        print(f"  -> {result['qc']}")
        if args.verify:
            if studiomdl and not verify_export(reader, result, args.mod_dir, studiomdl):
                failed = True
    return 1 if failed else 0


def self_test() -> int:
    cases = [(0.0, 0.0, 0.0), (0.3, -0.2, 0.5), (-1.2, 0.4, 2.1), (0.0, 0.0, ROOT_YAW)]
    worst = 0.0
    for e in cases:
        back = quat_to_euler(angle_quaternion(e))
        worst = max(worst, angle_distance(e, back))
    print(f"rotation math round-trip error: {worst:.3e} rad")
    print("SMD rotation units: radians (use --degrees for tools that expect degrees)")
    print(f"root bone yaw compensation: {math.degrees(ROOT_YAW):.1f} deg")
    return 0 if worst < 1e-9 else 1


def script_args(argv: list[str]) -> list[str]:
    """Drop whatever Blender itself was launched with (it keeps it in sys.argv)."""
    return argv[argv.index("--") + 1 :] if "--" in argv else argv


if __name__ == "__main__":
    sys.exit(main(script_args(sys.argv[1:])))
