#!/usr/bin/env python3
"""Render a viewmodel ref SMD in a sequence pose, from the player's eye.

    blender -b --python-exit-code 1 --python tools/preview_viewmodel.py -- \
        Blender/v_portalgun/anims/ref.smd Blender/v_portalgun/anims/idle.smd out.png [fov]

Builds and skins the SMD geometry itself (no Source Tools), evaluates the given
SMD's frame 0, and renders with a camera at the model origin looking down -Y
with +Z up -- the same view space the stock viewmodels are authored in.
"""
from __future__ import annotations

import math
import sys

import bpy
import numpy as np
from mathutils import Matrix, Vector


def parse_smd(path: str, with_weights: bool = True):
    nodes, parents, skel = {}, {}, {}
    tris = []
    mode = None
    material = None
    corners = []
    for line in open(path, errors="ignore"):
        s = line.strip()
        if not s:
            continue
        if s in ("nodes", "skeleton", "triangles"):
            mode = s
            continue
        if s == "end":
            if mode == "triangles" and corners and material:
                tris.append((material, corners))
            mode = None
            corners = []
            continue
        p = s.split()
        if mode == "nodes":
            nodes[int(p[0])] = p[1].strip('"')
            parents[int(p[0])] = int(p[2])
        elif mode == "skeleton":
            if p[0] != "time":
                skel[int(p[0])] = (tuple(map(float, p[1:4])), tuple(map(float, p[4:7])))
        elif mode == "triangles":
            if len(p) == 1:
                if corners and material:
                    tris.append((material, corners))
                corners = []
                material = p[0]
                continue
            if len(p) < 10:
                continue
            pos = tuple(map(float, p[1:4]))
            nrm = tuple(map(float, p[4:7]))
            uv = tuple(map(float, p[7:9]))
            links = int(p[9])
            weights = []
            idx = 10
            for _ in range(links):
                weights.append((int(p[idx]), float(p[idx + 1])))
                idx += 2
            corners.append((pos, nrm, uv, weights))
    return nodes, parents, skel, tris


def angle_matrix(pos, rot):
    x, y, z = rot
    cx, sx = math.cos(x), math.sin(x)
    cy, sy = math.cos(y), math.sin(y)
    cz, sz = math.cos(z), math.sin(z)
    m = np.eye(4)
    m[:3, :3] = np.array(
        [
            [cy * cz, sx * sy * cz - cx * sz, cx * sy * cz + sx * sz],
            [cy * sz, sx * sy * sz + cx * cz, cx * sy * sz - sx * cz],
            [-sy, sx * cy, cx * cy],
        ]
    )
    m[:3, 3] = pos
    return m


def world_of(parents, skel):
    world = {}

    def get(i):
        if i in world:
            return world[i]
        local = angle_matrix(*skel[i])
        world[i] = local if parents[i] < 0 else get(parents[i]) @ local
        return world[i]

    return {i: get(i) for i in parents}


def build(ref, anim, fov):
    nodes, parents, bind, tris = parse_smd(ref)
    _, _, pose, _ = parse_smd(anim)
    world = world_of(parents, pose)
    bind_world = world_of(parents, bind)

    verts, faces, mats, vert_mats, face_uvs = [], [], [], [], []
    for material, corners in tris:
        if len(corners) != 3:
            continue
        base = len(verts)
        for pos, _nrm, _uv, weights in corners:
            p = np.array([*pos, 1.0])
            out = np.zeros(3)
            total = 0.0
            for bone, w in weights:
                if bone not in world or bone not in bind_world:
                    continue
                skin = world[bone] @ np.linalg.inv(bind_world[bone])
                out += w * (skin @ p)[:3]
                total += w
            if total <= 0:
                out = p[:3]
            else:
                out /= total
            verts.append(tuple(out))
            vert_mats.append(material)
        faces.append((base, base + 1, base + 2))
        mats.append(material)
        face_uvs.append([c[2] for c in corners])

    me = bpy.data.meshes.new("vm")
    me.from_pydata(verts, [], faces)
    me.update()
    uv_layer = me.uv_layers.new(name="UVMap")
    for poly, uvs in zip(me.polygons, face_uvs):
        for loop_index, uv in zip(poly.loop_indices, uvs):
            # SMD V runs top-down, Blender images bottom-up
            uv_layer.data[loop_index].uv = (uv[0], 1.0 - uv[1])
    ob = bpy.data.objects.new("vm", me)
    bpy.context.collection.objects.link(ob)

    groups = {}
    for material in mats:
        groups.setdefault(material, len(groups))
    for name, _i in sorted(groups.items(), key=lambda kv: kv[1]):
        mat = bpy.data.materials.new(name)
        hue = (abs(hash(name)) % 360) / 360.0
        if name.startswith("bone_") or name == "invisible":
            mat.diffuse_color = (0.05, 0.05, 0.05, 1.0)
        else:
            mat.diffuse_color = (0.35 + 0.5 * hue, 0.45, 0.85 - 0.5 * hue, 1.0)
        me.materials.append(mat)
    for poly, material in zip(me.polygons, mats):
        poly.material_index = groups[material]

    cam_data = bpy.data.cameras.new("cam")
    cam = bpy.data.objects.new("cam", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    cam_data.sensor_fit = "HORIZONTAL"
    cam_data.angle = math.radians(fov)
    cam_data.clip_start = 0.1
    cam_data.clip_end = 4096.0
    cam.matrix_world = Matrix(
        (
            (-1.0, 0.0, 0.0, 0.0),
            (0.0, 0.0, 1.0, 0.0),
            (0.0, 1.0, 0.0, 0.0),
            (0.0, 0.0, 0.0, 1.0),
        )
    )
    bpy.context.scene.camera = cam
    return ob, (verts, vert_mats)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:]
    ref, anim, out = argv[0], argv[1], argv[2]
    fov = float(argv[3]) if len(argv) > 3 else 54.0
    view = argv[4] if len(argv) > 4 else "fp"
    bpy.ops.wm.read_factory_settings(use_empty=True)
    ob, (verts, vert_mats) = build(ref, anim, fov)
    tex = argv[5] if len(argv) > 5 else None
    if view != "fp":
        pts = np.array([v for v, m in zip(verts, vert_mats) if not m.startswith("bone_") and m != "invisible"])
        center = Vector(pts.mean(axis=0))
        radius = float(np.linalg.norm(pts - np.array(center), axis=1).max())
        cam = bpy.context.scene.camera
        cam.data.type = "ORTHO"
        cam.data.ortho_scale = radius * 2.4
        offset = Vector((radius * 4, 0, 0)) if view == "side" else Vector((0, 0, radius * 4))
        cam.location = center + offset
        cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()
    scn = bpy.context.scene
    scn.render.engine = "BLENDER_WORKBENCH"
    scn.display.shading.light = "STUDIO"
    scn.display.shading.color_type = "MATERIAL"
    scn.display.shading.show_cavity = True
    scn.render.resolution_x = 1100
    scn.render.resolution_y = 750
    scn.render.film_transparent = False
    # a floor plane so the gun has a horizon to sit against
    bpy.ops.mesh.primitive_plane_add(size=400, location=(0, 0, -40))
    if tex:
        image = bpy.data.images.load(tex)
        for mat in ob.data.materials:
            if mat.name.startswith("bone_") or mat.name == "invisible":
                continue
            mat.use_nodes = True
            nodes = mat.node_tree.nodes
            for node in list(nodes):
                nodes.remove(node)
            out_node = nodes.new("ShaderNodeOutputMaterial")
            bsdf = nodes.new("ShaderNodeBsdfPrincipled")
            bsdf.inputs["Roughness"].default_value = 0.55
            bsdf.inputs["Metallic"].default_value = 0.2
            tex_node = nodes.new("ShaderNodeTexImage")
            tex_node.image = image
            mat.node_tree.links.new(tex_node.outputs["Color"], bsdf.inputs["Base Color"])
            mat.node_tree.links.new(bsdf.outputs["BSDF"], out_node.inputs["Surface"])
        scn.render.engine = "CYCLES"
        scn.cycles.device = "CPU"
        scn.cycles.samples = 24
        scn.cycles.use_denoising = True
        world = bpy.data.worlds.new("w")
        world.use_nodes = True
        world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.35, 0.37, 0.4, 1)
        world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.7
        scn.world = world
        light_data = bpy.data.lights.new("key", "SUN")
        light_data.energy = 3.0
        light = bpy.data.objects.new("key", light_data)
        light.rotation_euler = (math.radians(50), math.radians(10), math.radians(-30))
        scn.collection.objects.link(light)
    scn.render.filepath = out
    bpy.ops.render.render(write_still=True)
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
