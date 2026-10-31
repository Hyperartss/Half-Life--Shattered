"""Write SMD animations, SMD reference meshes and QCs straight from Blender.

Conventions (the same ones the mod's decoder and Blender Source Tools use):

* bone lines are parent-relative: position + Euler XYZ rotation in RADIANS,
  R = Rz * Ry * Rx (Blender's 'XYZ' Euler order);
* a bone's rest matrix in Blender is its SMD bind pose (Source Tools imports
  it that way), so a pose bone's armature-space matrix is its SMD pose;
* root bones are written in armature space; the armature object's own
  transform is ignored (Source Tools imports it at identity).
"""
import math
import os
import re

import bpy
from mathutils import Matrix


def _bone_line(index, m):
    t = m.to_translation()
    e = m.to_3x3().normalized().to_euler("XYZ")
    return "%d %.6f %.6f %.6f %.6f %.6f %.6f" % (index, t.x, t.y, t.z, e.x, e.y, e.z)


def _nodes(armature):
    bones = list(armature.data.bones)
    index = {b.name: i for i, b in enumerate(bones)}
    lines = ["version 1", "nodes"]
    for i, b in enumerate(bones):
        lines.append('%d "%s" %d' % (i, b.name, index[b.parent.name] if b.parent else -1))
    lines.append("end")
    return bones, index, lines


def rest_locals(armature):
    out = {}
    for b in armature.data.bones:
        out[b.name] = (b.parent.matrix_local.inverted() @ b.matrix_local) if b.parent else b.matrix_local.copy()
    return out


def pose_locals(armature):
    out = {}
    for pb in armature.pose.bones:
        out[pb.name] = (pb.parent.matrix.inverted() @ pb.matrix) if pb.parent else pb.matrix.copy()
    return out


def write_animation(armature, path, frame_start, frame_end):
    """Sample the armature's current action slot frame by frame into an SMD."""
    scene = bpy.context.scene
    keep = scene.frame_current
    bones, _index, lines = _nodes(armature)
    lines.append("skeleton")
    try:
        for n, frame in enumerate(range(frame_start, frame_end + 1)):
            scene.frame_set(frame)
            local = pose_locals(armature)
            lines.append("time %d" % n)
            for i, b in enumerate(bones):
                lines.append(_bone_line(i, local[b.name]))
    finally:
        scene.frame_set(keep)
    lines.append("end")
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return frame_end - frame_start + 1


def write_reference(armature, meshes, path, markers=True):
    """Bind pose + the meshes' triangles with up to 3 bone weights per vertex."""
    bones, index, lines = _nodes(armature)
    rest = rest_locals(armature)
    lines += ["skeleton", "time 0"]
    for i, b in enumerate(bones):
        lines.append(_bone_line(i, rest[b.name]))
    lines += ["end", "triangles"]
    used = set()
    to_arm = armature.matrix_world.inverted()
    for obj in meshes:
        me = obj.data
        me.calc_loop_triangles()
        m = to_arm @ obj.matrix_world
        nm = m.to_3x3().inverted().transposed()
        groups = {g.index: g.name for g in obj.vertex_groups}
        uv = me.uv_layers.active.data if me.uv_layers.active else None
        normals = me.corner_normals
        links_of = {}
        for v in me.vertices:
            ws = sorted(((groups[g.group], g.weight) for g in v.groups if g.group in groups and groups[g.group] in index and g.weight > 0),
                        key=lambda kv: -kv[1])[:3]
            total = sum(w for _n, w in ws)
            if not ws or total <= 0:
                parent = obj.parent_bone if obj.parent_type == "BONE" and obj.parent_bone in index else bones[0].name
                ws, total = [(parent, 1.0)], 1.0
            links_of[v.index] = [(index[n], w / total) for n, w in ws]
            used.update(index[n] for n, _w in ws)
        for tri in me.loop_triangles:
            material = me.materials[tri.material_index].name if me.materials and me.materials[tri.material_index] else "default"
            lines.append(material)
            for li, vi in zip(tri.loops, tri.vertices):
                co = m @ me.vertices[vi].co
                no = (nm @ normals[li].vector).normalized()
                u, vv = (uv[li].uv[0], uv[li].uv[1]) if uv else (0.0, 0.0)
                links = links_of[vi]
                lines.append("%d %.6f %.6f %.6f %.6f %.6f %.6f %.6f %.6f %d %s" % (
                    links[0][0], co.x, co.y, co.z, no.x, no.y, no.z, u, vv, len(links),
                    " ".join("%d %.6f" % lw for lw in links)))
    if markers:
        # studiomdl drops bones no vertex uses; one tiny triangle keeps each
        for i, b in enumerate(bones):
            if i in used:
                continue
            o = b.head_local
            lines.append("bone_" + b.name)
            for d in ((0, 0, 0), (0.01, 0, 0), (0, 0.01, 0)):
                lines.append("%d %.6f %.6f %.6f 0 0 1 0 1 1 %d 1.000000" % (i, o.x + d[0], o.y + d[1], o.z + d[2], i))
    lines.append("end")
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")


# --------------------------------------------------------------------------
# QC
# --------------------------------------------------------------------------
SEQ_RE = re.compile(r'^\s*\$sequence\s+"([^"]+)"\s+"([^"]+)"(.*)$')


def parse_sequences(qc_path):
    """{name: {"file", "fps", "activity", "weight", "loop"}} from $sequence lines."""
    out = {}
    if not os.path.exists(qc_path):
        return out
    for line in open(qc_path, errors="ignore"):
        m = SEQ_RE.match(line)
        if not m:
            continue
        name, file, rest = m.groups()
        tokens = rest.split()
        info = {"file": file, "fps": 30.0, "activity": "", "weight": 1, "loop": False}
        i = 0
        while i < len(tokens):
            t = tokens[i]
            if t == "fps" and i + 1 < len(tokens):
                info["fps"] = float(tokens[i + 1])
                i += 2
                continue
            if t.startswith("ACT_"):
                info["activity"] = t
                if i + 1 < len(tokens) and tokens[i + 1].lstrip("-").isdigit():
                    info["weight"] = int(tokens[i + 1])
                    i += 1
            elif t == "loop":
                info["loop"] = True
            i += 1
        out[name] = info
    return out


def header_lines(qc_path):
    """Everything in a QC except its $sequence lines (and trailing blanks)."""
    if not os.path.exists(qc_path):
        return []
    lines = [l.rstrip("\n") for l in open(qc_path, errors="ignore") if not SEQ_RE.match(l)]
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def sequence_line(name, smd_path, info):
    parts = ['$sequence "%s" "%s" fps %g' % (name, smd_path, info.get("fps", 30.0))]
    if info.get("activity"):
        parts.append("%s %d" % (info["activity"], info.get("weight", 1)))
    if info.get("loop"):
        parts.append("loop")
    return " ".join(parts)


def write_test_qc(qc_path, sequences):
    """Rewrite the weapon's Blender QC: same header, one line per animation."""
    head = header_lines(qc_path)
    body = [sequence_line(n, "anims/%s.smd" % n, i) for n, i in sequences]
    with open(qc_path, "w") as fh:
        fh.write("\n".join(head + [""] + body) + "\n")


def write_shipping_qci(qci_path, weapon, sequences):
    body = ["// Written by the SL Viewmodel add-on: every animation of %s, from Blender/%s/anims." % (weapon, weapon)]
    body += [sequence_line(n, "../../Blender/%s/anims/%s.smd" % (weapon, n), i) for n, i in sequences]
    with open(qci_path, "w") as fh:
        fh.write("\n".join(body) + "\n")


def use_qci_in_shipping_qc(qc_path, qci_name):
    """Swap the shipping QC's $includemodel for our own sequences.

    Keeping both would give two sequences per activity and the engine would
    pick between the stock one and yours at random. The old line stays in the
    file as a comment. Returns True if the file changed."""
    text = open(qc_path).read()
    include = '$include "%s"' % qci_name
    if include in text and re.search(r"^\s*\$includemodel", text, re.M) is None:
        return False
    lines = []
    placed = False
    for line in text.splitlines():
        if re.match(r"^\s*\$includemodel", line):
            lines.append("// " + line.strip() + "   (replaced by the add-on's own sequences below)")
            if not placed:
                lines.append(include)
                placed = True
        elif line.strip() == include:
            if not placed:
                lines.append(line)
                placed = True
        else:
            lines.append(line)
    if not placed:
        lines.append(include)
    with open(qc_path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return True
