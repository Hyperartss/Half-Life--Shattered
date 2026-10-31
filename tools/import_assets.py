#!/usr/bin/env python3
"""Import models, materials and other Source assets into HLShattered.

Hammer's model and material browsers only list what the game's search paths can
see, so an asset that lives in another game's VPK (Portal, HL2, EP2, ...) is
invisible until it is copied into this mod -- and a downloaded custom model is
invisible until it lands in the right ``models/`` + ``materials/`` layout with
its textures.  This tool does that copy for you, and it walks the dependency
graph instead of making you guess:

    .mdl  -> .vvd, .vtx variants, .phy, .ani, $includemodel chain, its materials
    .vmt  -> $basetexture / $bumpmap / ... textures, ``patch`` includes
    .vtf  -> the .vmt that uses it (or a generated one, so Hammer lists it)

Examples (run from the mod root):

    tools/import_assets.py sources
    tools/import_assets.py list portal lab_desk
    tools/import_assets.py import portal models/props/lab_desk01/lab_desk01.mdl
    tools/import_assets.py import ~/Downloads/coolgun.zip
    tools/import_assets.py import ~/Downloads/pack/models/weapons/v_gun.mdl
    tools/import_assets.py check

Sources are the paths in gameinfo.txt (mod, hl2, ep2, episodic, platform,
portal, custom/*), or any folder / .zip / .vpk you point at.  Overwriting an
existing file needs --force, and --pack NAME puts the import under
custom/NAME/ so it can be removed again with ``unimport --pack NAME``.

Releasing without mounted games:

    tools/import_assets.py audit "<game>/<content dir>"   # what this engine can load
    tools/import_assets.py bake portal                    # content into the mod
    tools/import_assets.py release --write dist/gameinfo.txt

``audit`` reads header versions (studio, VTF, DMX/pcf) and says which files this
engine build rejects; ``bake`` copies a whole source with its dependency graph;
``release`` resolves the mod against itself and lists whatever still has to be
mounted.  See IMPORTING.md for the measured per-game numbers.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import struct
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# --------------------------------------------------------------------------
# Where things are
# --------------------------------------------------------------------------

MOD_ROOT = Path(__file__).resolve().parent.parent
GAMEINFO = MOD_ROOT / "gameinfo.txt"
MANIFEST_NAME = ".import.json"

# Only these top-level folders hold engine assets.  Keeping the list narrow
# means indexing the mod does not walk src/, Blender/ or .git/.
ASSET_ROOTS = ("models", "materials", "particles", "sound", "scripts", "resource")

# What this engine can load, read out of src/Portal-Base/sp/src/public:
#   studio.h   STUDIO_VERSION 48          -> Portal 2 models (v49) will not load
#   vtf/vtf.h  VTF 7.4                   -> Portal 2 / newer textures (7.5) will not
# and the client's particle loader speaks the Portal 1 DMX format (pcf 1), not
# Portal 2's pcf 2.
STUDIO_VERSION = 48
VTF_VERSION = (7, 4)
PCF_VERSION = 1

VPK_SIGNATURE = 0x55AA1234
VPK_DIR_ARCHIVE = 0x7FFF

# VMT keys whose value names a texture.  Values that name existing textures are
# followed even under unknown keys, so custom shaders still pull their maps.
TEXTURE_KEYS = {
    "$basetexture",
    "$basetexture2",
    "$bumpmap",
    "$normalmap",
    "$detail",
    "$detail2",
    "$blendmodulatetexture",
    "$blendmodulate",
    "$phongexponenttexture",
    "$envmapmask",
    "$reflecttexture",
    "$envmap",
    "$dudvmap",
    "$flowmap",
    "$noise",
    "$selfillummask",
    "$lightwarptexture",
    "$texture2",
}

# $envmap is frequently a keyword rather than a file.
NON_TEXTURE_VALUES = {"env_cubemap", "env_cubemap_box", "0", "1", ""}


def is_render_target(rel: str) -> bool:
    """`materials/_rt_FullFrameFB.vtf` is a render target the engine owns, not a
    file any game ships, so it is never a missing dependency."""
    return rel.rsplit("/", 1)[-1].lower().startswith("_rt_")

MODEL_EXTENSIONS = (".mdl", ".vvd", ".vtx", ".phy", ".ani")
MATERIAL_EXTENSIONS = (".vmt", ".vtf")


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------


def norm_rel(rel: str) -> str:
    """Forward slashes, no leading/trailing separators, no '.' segments."""
    rel = str(rel).replace("\\", "/").strip()
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    return "/".join(parts)


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} GB"


def cstring(data: bytes, offset: int) -> str:
    if offset < 0 or offset >= len(data):
        raise ValueError(f"string offset {offset} outside header")
    end = data.find(b"\0", offset)
    if end < 0:
        end = len(data)
    return data[offset:end].decode("latin-1", "replace")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# --------------------------------------------------------------------------
# Asset format versions: what this engine can actually load
# --------------------------------------------------------------------------

DMX_HEADER_RE = re.compile(
    rb"<!--\s*dmx\s+encoding\s+(\S+)\s+(\d+)\s+format\s+(\S+)\s+(\d+)\s*-->"
)


@dataclass
class FormatStats:
    """Format versions seen in a source, and which files this engine rejects."""

    counts: dict[str, int] = field(default_factory=dict)
    too_new: list[tuple[str, str]] = field(default_factory=list)

    def add(self, rel: str, label: str, supported: bool) -> None:
        self.counts[label] = self.counts.get(label, 0) + 1
        if not supported:
            self.too_new.append((rel, label))


def examine_asset(bundle: Bundle, rel: str, stats: FormatStats) -> None:
    """Read one header and record whether this engine can open the file."""
    extension = os.path.splitext(rel)[1].lower()
    try:
        head = bundle.peek(rel, 96)
    except OSError as error:
        stats.add(rel, f"{extension}: unreadable ({error})", False)
        return

    if extension == ".mdl":
        if head[:4] != b"IDST" or len(head) < 8:
            stats.add(rel, "model: no IDST header", False)
            return
        version = struct.unpack_from("<i", head, 4)[0]
        stats.add(rel, f"studio v{version}", version <= STUDIO_VERSION)
    elif extension == ".vtf":
        if head[:4] != b"VTF\0" or len(head) < 12:
            stats.add(rel, "texture: no VTF header", False)
            return
        version = struct.unpack_from("<II", head, 4)
        stats.add(rel, f"vtf {version[0]}.{version[1]}", version <= VTF_VERSION)
    elif extension == ".pcf":
        match = DMX_HEADER_RE.search(head)
        if match is None:
            stats.add(rel, "particles: no DMX header", False)
            return
        version = int(match.group(4))
        stats.add(rel, f"pcf {version} ({match.group(1).decode('latin-1')})", version <= PCF_VERSION)


# --------------------------------------------------------------------------
# VPK (Valve Pak) reading
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class VpkEntry:
    crc: int
    preload: bytes
    archive: int
    offset: int
    length: int

    @property
    def size(self) -> int:
        return len(self.preload) + self.length


class Vpk:
    """A Valve Pak file.  Handles single-file v1/v2 packs and split archives."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.entries: dict[str, VpkEntry] = {}
        self.version = 0
        self._handles: dict[Path, object] = {}
        self._parse()

    def _parse(self) -> None:
        with open(self.path, "rb") as f:
            head = f.read(28)
            if len(head) < 12:
                raise ValueError("truncated VPK header")
            signature, version = struct.unpack_from("<II", head, 0)
            if signature != VPK_SIGNATURE:
                raise ValueError("not a VPK file")
            self.version = version
            if version == 1:
                tree_size = struct.unpack_from("<I", head, 8)[0]
            elif version == 2:
                tree_size = struct.unpack_from("<I", head, 8)[0]
            else:
                raise ValueError(f"unsupported VPK version {version}")
            f.seek(0)
            f.read(12 if version == 1 else 28)
            tree = f.read(tree_size)

        pos = 0

        def read_cstr() -> str:
            nonlocal pos
            end = tree.find(b"\0", pos)
            if end < 0:
                raise ValueError("truncated VPK directory tree")
            text = tree[pos:end].decode("latin-1")
            pos = end + 1
            return text

        while pos < len(tree):
            ext = read_cstr()
            if ext == "":
                break
            while True:
                folder = read_cstr()
                if folder == "":
                    break
                while True:
                    name = read_cstr()
                    if name == "":
                        break
                    if pos + 18 > len(tree):
                        raise ValueError("truncated VPK entry")
                    crc, preload_bytes, archive, offset, length = struct.unpack_from(
                        "<IHHII", tree, pos
                    )
                    pos += 16
                    # The terminator comes *before* the preload bytes.  Portal 1
                    # and Black Mesa put nothing in the directory, so reading
                    # preload first happens to work there; Portal 2 keeps ~2.6 MB
                    # of it inline and desynchronises the rest of the tree.
                    terminator = struct.unpack_from("<H", tree, pos)[0]
                    pos += 2
                    if terminator != 0xFFFF:
                        raise ValueError(
                            f"bad VPK entry terminator in {self.path.name} "
                            f"({terminator:#06x})"
                        )
                    preload = tree[pos : pos + preload_bytes]
                    pos += preload_bytes
                    filename = name if ext == " " else f"{name}.{ext}"
                    rel = f"{folder}/{filename}" if folder else filename
                    self.entries[rel.lower()] = VpkEntry(
                        crc, preload, archive, offset, length
                    )

    def read(self, rel: str) -> bytes:
        entry = self.entries[rel.lower()]
        chunks = [entry.preload]
        if entry.length:
            handle = self._handle(entry.archive)
            handle.seek(entry.offset)
            chunks.append(handle.read(entry.length))
        return b"".join(chunks)

    def peek(self, rel: str, length: int = 64) -> bytes:
        """First `length` bytes, without reading the rest of a large entry."""
        entry = self.entries[rel.lower()]
        data = entry.preload[:length]
        if len(data) < length and entry.length:
            handle = self._handle(entry.archive)
            handle.seek(entry.offset)
            data += handle.read(length - len(data))
        return data

    def _handle(self, index: int):
        """One open handle per archive: whole-game work would otherwise open the
        same multi-GB shard tens of thousands of times."""
        archive = self._archive_path(index)
        handle = self._handles.get(archive)
        if handle is None:
            handle = open(archive, "rb")
            self._handles[archive] = handle
        return handle

    def close(self) -> None:
        for handle in self._handles.values():
            try:
                handle.close()  # type: ignore[union-attr]
            except OSError:
                pass
        self._handles.clear()

    def _archive_path(self, index: int) -> Path:
        if index == VPK_DIR_ARCHIVE:
            return self.path
        name = self.path.name
        if name.lower().endswith("_dir.vpk"):
            base = name[:-8]
        else:
            base = name[: -len(".vpk")]
        candidate = self.path.parent / f"{base}_{index:03d}.vpk"
        if candidate.exists():
            return candidate
        matches = sorted(self.path.parent.glob(f"*_{index:03d}.vpk"))
        if matches:
            return matches[0]
        raise FileNotFoundError(f"missing VPK archive {candidate.name}")


# --------------------------------------------------------------------------
# Bundles: one source of files (folder, VPK, or zip)
# --------------------------------------------------------------------------


class Bundle:
    label = "bundle"

    def entries(self) -> dict[str, int]:
        """relative path (lowercase) -> size in bytes"""
        raise NotImplementedError

    def size(self, rel: str) -> int | None:
        return self.entries().get(norm_rel(rel).lower())

    def read(self, rel: str) -> bytes:
        raise NotImplementedError

    def peek(self, rel: str, length: int = 64) -> bytes:
        """First `length` bytes of a file.  Reading a header must not cost the
        whole file: a whole-game audit would otherwise pull gigabytes."""
        return self.read(rel)[:length]


class DirBundle(Bundle):
    def __init__(self, root: Path, label: str | None = None):
        self.root = Path(root)
        self.label = label or str(self.root)
        self._index: dict[str, Path] | None = None

    def entries(self) -> dict[str, int]:
        if self._index is None:
            index: dict[str, Path] = {}
            for folder in ASSET_ROOTS:
                base = self.root / folder
                if not base.is_dir():
                    continue
                for path in base.rglob("*"):
                    if path.is_file():
                        index[path.relative_to(self.root).as_posix().lower()] = path
            self._index = index
        return {rel: p.stat().st_size for rel, p in self._index.items()}

    def size(self, rel: str) -> int | None:
        path = self._index_path(rel)
        if path is None:
            return None
        try:
            return path.stat().st_size
        except OSError:
            return None

    def _index_path(self, rel: str) -> Path | None:
        if self._index is None:
            self.entries()
        return self._index.get(norm_rel(rel).lower())  # type: ignore[union-attr]

    def read(self, rel: str) -> bytes:
        path = self._index_path(rel)
        if path is None:
            raise FileNotFoundError(rel)
        return path.read_bytes()

    def peek(self, rel: str, length: int = 64) -> bytes:
        path = self._index_path(rel)
        if path is None:
            raise FileNotFoundError(rel)
        with open(path, "rb") as f:
            return f.read(length)


class VpkBundle(Bundle):
    def __init__(self, path: Path, label: str | None = None):
        self.vpk = Vpk(path)
        self.label = label or str(path)
        self._sizes: dict[str, int] | None = None

    def entries(self) -> dict[str, int]:
        if self._sizes is None:
            self._sizes = {rel: e.size for rel, e in self.vpk.entries.items()}
        return self._sizes

    def read(self, rel: str) -> bytes:
        return self.vpk.read(rel)

    def peek(self, rel: str, length: int = 64) -> bytes:
        return self.vpk.peek(rel, length)


class ZipBundle(Bundle):
    """A .zip, re-rooted at the first models/ materials/ ... folder it holds."""

    def __init__(self, path: Path, label: str | None = None):
        self.path = Path(path)
        self.label = label or str(self.path)
        self.zip = zipfile.ZipFile(self.path)
        self._members: dict[str, zipfile.ZipInfo] | None = None

    def _index(self) -> dict[str, zipfile.ZipInfo]:
        if self._members is None:
            members: dict[str, zipfile.ZipInfo] = {}
            for info in self.zip.infolist():
                if info.is_dir():
                    continue
                parts = info.filename.replace("\\", "/").split("/")
                start = next(
                    (i for i, part in enumerate(parts) if part.lower() in ASSET_ROOTS),
                    None,
                )
                if start is None:
                    continue
                rel = "/".join(parts[start:]).lower()
                if rel:
                    members.setdefault(rel, info)
            self._members = members
        return self._members

    def entries(self) -> dict[str, int]:
        return {rel: info.file_size for rel, info in self._index().items()}

    def size(self, rel: str) -> int | None:
        info = self._index().get(norm_rel(rel).lower())
        return None if info is None else info.file_size

    def read(self, rel: str) -> bytes:
        info = self._index()[norm_rel(rel).lower()]
        return self.zip.read(info)


@dataclass(frozen=True)
class FileRef:
    bundle: Bundle
    rel: str
    size: int

    def read(self) -> bytes:
        return self.bundle.read(self.rel)


class Source:
    """A game content root (or a folder/zip the user pointed at)."""

    def __init__(self, name: str, label: str, bundles: list[Bundle]):
        self.name = name
        self.label = label
        self.bundles = bundles
        self._entries: dict[str, int] | None = None

    def find(self, rel: str) -> FileRef | None:
        rel = norm_rel(rel).lower()
        for bundle in self.bundles:
            size = bundle.size(rel)
            if size is not None:
                return FileRef(bundle, rel, size)
        return None

    def entries(self) -> dict[str, int]:
        if self._entries is None:
            merged: dict[str, int] = {}
            for bundle in self.bundles:
                for rel, size in bundle.entries().items():
                    merged.setdefault(rel, size)
            self._entries = merged
        return self._entries


# --------------------------------------------------------------------------
# gameinfo.txt: search paths are the mount list Hammer uses
# --------------------------------------------------------------------------


@dataclass
class KV:
    items: list[tuple[str, object]] = field(default_factory=list)

    def get(self, key: str, default: str | None = None) -> str | None:
        for name, value in self.items:
            if name.lower() == key.lower() and isinstance(value, str):
                return value
        return default

    def blocks(self, key: str) -> list["KV"]:
        return [
            value
            for name, value in self.items
            if name.lower() == key.lower() and isinstance(value, KV)
        ]


KV_TOKEN_RE = re.compile(r'"[^"]*"|//[^\n]*|/\*.*?\*/|[{}]|[^\s{}]+', re.S)


def _kv_tokens(text: str):
    for match in KV_TOKEN_RE.finditer(text):
        token = match.group(0)
        if token.startswith(("//", "/*")):
            continue
        if token.startswith('"'):
            token = token[1:-1]
        yield token


def parse_kv(text: str) -> KV:
    tokens = list(_kv_tokens(text))
    root = KV()
    stack = [root]
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token == "}":
            if len(stack) > 1:
                stack.pop()
            i += 1
            continue
        if token == "{":
            i += 1
            continue
        key = token
        i += 1
        if i < len(tokens) and tokens[i] == "{":
            block = KV()
            stack[-1].items.append((key, block))
            stack.append(block)
            i += 1
        elif i < len(tokens) and tokens[i] != "}":
            stack[-1].items.append((key, tokens[i]))
            i += 1
    return root


def find_steamapps() -> Path | None:
    for parent in MOD_ROOT.parents:
        if parent.name == "steamapps":
            return parent
    return None


def find_engine_root(steamapps: Path | None) -> Path | None:
    """The SDK Base 2013 install, which is what |all_source_engine_paths| means."""
    if steamapps is None:
        return None
    common = steamapps / "common"
    candidates = sorted(common.glob("Source SDK Base 2013*"))
    for candidate in candidates:
        if (candidate / "hl2").is_dir() and candidate.name.endswith("Singleplayer"):
            return candidate
    return candidates[0] if candidates else None


def expand_search_path(value: str, gameinfo_dir: Path, engine_root: Path | None) -> list[Path]:
    raw = value.strip()
    resolved: Path
    match = re.match(r"^\|([a-z_]+)\|(.*)$", raw)
    if match:
        prefix, rest = match.group(1), match.group(2)
        if prefix == "gameinfo_path":
            resolved = gameinfo_dir / rest
        elif prefix in ("all_source_engine_paths", "all_game_paths"):
            if engine_root is None:
                return []
            resolved = engine_root / rest
        else:
            return []
    else:
        resolved = Path(raw)
        if not resolved.is_absolute():
            resolved = gameinfo_dir / raw
    if "*" in str(resolved) or "?" in str(resolved):
        parent = resolved.parent
        if parent.is_dir():
            return sorted(parent.glob(resolved.name))
        return []
    return [resolved]


@dataclass
class Mount:
    name: str
    path: Path
    exists: bool
    bundles: list[Bundle] = field(default_factory=list)


def read_search_paths() -> tuple[list[tuple[str, Path]], Path | None]:
    """(search path, resolved location) pairs plus the engine root used."""
    if not GAMEINFO.exists():
        return [], None
    steamapps = find_steamapps()
    engine_root = find_engine_root(steamapps)
    tree = parse_kv(GAMEINFO.read_text(encoding="latin-1", errors="replace"))
    roots = tree.blocks("GameInfo") or [tree]
    paths: list[tuple[str, Path]] = []
    for fs in [block for root in roots for block in root.blocks("FileSystem")]:
        for container in fs.blocks("SearchPaths"):
            for key, value in container.items:
                if not isinstance(value, str):
                    continue
                if key.lower().startswith("gamebin"):
                    continue
                for resolved in expand_search_path(value, MOD_ROOT, engine_root):
                    paths.append((key, resolved))
    return paths, engine_root


def build_mounts() -> list[Mount]:
    """The mod plus everything gameinfo mounts, in engine search order.

    One Mount is one logical source (a game folder plus its VPKs).  gameinfo
    usually lists both a folder and one of its VPKs, so paths are de-duplicated
    and bundles merged instead of producing two rows for the same game.
    """
    mounts: list[Mount] = []
    by_name: dict[str, Mount] = {}
    seen_paths: set[str] = set()

    def add(path: Path, name: str | None = None) -> None:
        key = str(path.resolve())
        if key in seen_paths:
            return
        if path.is_file():
            if path.suffix.lower() != ".vpk":
                return
            try:
                bundle: Bundle = VpkBundle(path)
            except (ValueError, OSError):
                return
            label = name or path.parent.name
        elif path.is_dir():
            bundle = DirBundle(path)
            label = name or path.name
        else:
            return
        seen_paths.add(key)
        mount = by_name.get(label)
        if mount is None:
            mount = Mount(label, path, True, [bundle])
            by_name[label] = mount
            mounts.append(mount)
        else:
            mount.bundles.append(bundle)

    add(MOD_ROOT, "mod")

    paths, _ = read_search_paths()
    for _key, path in paths:
        if path.is_dir():
            add(path)
            for vpk in sorted(path.glob("*.vpk")):
                if re.search(r"_\d{3}\.vpk$", vpk.name, re.I):
                    continue  # numbered shard of a split archive
                add(vpk, path.name)
        else:
            add(path)
    return mounts


def build_catalog() -> list[Source]:
    return [Source(m.name, str(m.path), m.bundles) for m in build_mounts()]


class Catalog:
    def __init__(self, sources: list[Source]):
        self.sources = sources

    def find(self, rel: str) -> tuple[Source, FileRef] | None:
        rel = norm_rel(rel).lower()
        for source in self.sources:
            ref = source.find(rel)
            if ref is not None:
                return source, ref
        return None

    def has(self, rel: str) -> bool:
        return self.find(rel) is not None

    def read(self, rel: str) -> bytes | None:
        hit = self.find(rel)
        return None if hit is None else hit[1].read()


# --------------------------------------------------------------------------
# Studio models (.mdl header: studio.h, STUDIO_VERSION 48)
# --------------------------------------------------------------------------

# studiohdr_t fields after the six vectors, in order (versions 44-48).
MDL_FIELDS = (
    "flags",
    "numbones",
    "boneindex",
    "numbonecontrollers",
    "bonecontrollerindex",
    "numhitboxsets",
    "hitboxsetindex",
    "numlocalanim",
    "localanimindex",
    "numlocalseq",
    "localseqindex",
    "activitylistversion",
    "eventsindexed",
    "numtextures",
    "textureindex",
    "numcdtextures",
    "cdtextureindex",
    "numskinref",
    "numskinfamilies",
    "skinindex",
    "numbodyparts",
    "bodypartindex",
    "numlocalattachments",
    "localattachmentindex",
    "numlocalnodes",
    "localnodeindex",
    "localnodenameindex",
    "numflexdesc",
    "flexdescindex",
    "numflexcontrollers",
    "flexcontrollerindex",
    "numflexrules",
    "flexruleindex",
    "numikchains",
    "ikchainindex",
    "nummouths",
    "mouthindex",
    "numlocalposeparameters",
    "localposeparamindex",
    "surfacepropindex",
    "keyvalueindex",
    "keyvaluesize",
    "numlocalikautoplaylocks",
    "localikautoplaylockindex",
)


@dataclass
class MdlInfo:
    version: int
    name: str
    bodyparts: int
    textures: list[str]
    cdtextures: list[str]
    includes: list[str]
    animblock: str | None

    @property
    def has_mesh(self) -> bool:
        """Animation-only models ($includemodel sources) ship no .vvd/.vtx."""
        return self.bodyparts > 0


def parse_mdl(data: bytes) -> MdlInfo:
    if len(data) < 160:
        raise ValueError("file too short")
    ident, version = struct.unpack_from("<4si", data, 0)
    if ident != b"IDST":
        raise ValueError("no IDST signature")
    name = cstring(data, 12)
    header = 80 + 6 * 12
    values = struct.unpack_from("<%di" % len(MDL_FIELDS), data, header)
    fields = dict(zip(MDL_FIELDS, values))

    textures: list[str] = []
    texture_index = fields["textureindex"]
    for i in range(max(0, fields["numtextures"])):
        base = texture_index + i * 64
        if base + 64 > len(data):
            break
        name_offset = struct.unpack_from("<i", data, base)[0]
        try:
            textures.append(cstring(data, base + name_offset))
        except ValueError:
            continue

    cdtextures: list[str] = []
    cd_index = fields["cdtextureindex"]
    for i in range(max(0, fields["numcdtextures"])):
        offset_pos = cd_index + i * 4
        if offset_pos + 4 > len(data):
            break
        offset = struct.unpack_from("<i", data, offset_pos)[0]
        try:
            cdtextures.append(cstring(data, offset))
        except ValueError:
            continue

    includes: list[str] = []
    animblock: str | None = None
    if version >= 44:
        after = header + 4 * len(MDL_FIELDS)
        # mass (float), contents, numincludemodels, includemodelindex,
        # virtualModel, szanimblocknameindex
        if after + 24 <= len(data):
            num_includes, include_index = struct.unpack_from("<ii", data, after + 8)
            for i in range(max(0, min(num_includes, 64))):
                base = include_index + i * 8
                if base + 8 > len(data):
                    break
                label_offset, name_offset = struct.unpack_from("<ii", data, base)
                try:
                    group_name = cstring(data, base + name_offset)
                except ValueError:
                    continue
                if not group_name and label_offset:
                    try:
                        group_name = cstring(data, base + label_offset)
                    except ValueError:
                        group_name = ""
                if group_name.lower().endswith(".mdl"):
                    includes.append(norm_rel(group_name))
            anim_offset = struct.unpack_from("<i", data, after + 20)[0]
            try:
                candidate = cstring(data, anim_offset)
            except ValueError:
                candidate = ""
            if candidate.lower().endswith(".ani"):
                animblock = norm_rel(candidate)

    return MdlInfo(
        version,
        name,
        max(0, fields["numbodyparts"]),
        textures,
        cdtextures,
        includes,
        animblock,
    )


def model_material_candidates(info: MdlInfo) -> list[list[str]]:
    """One candidate list per texture slot, best guess first."""
    out: list[list[str]] = []
    for texture in info.textures:
        name = texture.replace("\\", "/").strip("/")
        if name.lower().endswith(".vmt"):
            name = name[: -len(".vmt")]
        candidates: list[str] = []
        for cd in info.cdtextures:
            folder = cd.replace("\\", "/").strip("/")
            if folder.lower().startswith("materials/"):
                folder = folder[len("materials/") :]
            ref = f"{folder}/{name}" if folder else name
            candidates.append("materials/" + ref.replace("//", "/") + ".vmt")
        candidates.append("materials/" + name + ".vmt")
        # keep order, drop duplicates
        seen: set[str] = set()
        unique = [c for c in candidates if not (c in seen or seen.add(c))]
        out.append(unique)
    return out


# --------------------------------------------------------------------------
# VMT parsing
# --------------------------------------------------------------------------

VMT_TOKEN_RE = re.compile(r'"[^"]*"|//[^\n]*|/\*.*?\*/|[{}]|[^\s{}]+', re.S)


def _vmt_tokens(text: str):
    for match in VMT_TOKEN_RE.finditer(text):
        token = match.group(0)
        if token.startswith(("//", "/*")):
            continue
        if token.startswith('"'):
            token = token[1:-1]
        yield token


def _parse_vmt_block(tokens: list[str], i: int) -> tuple[list[tuple[str, object]], int]:
    items: list[tuple[str, object]] = []
    while i < len(tokens):
        token = tokens[i]
        if token == "}":
            return items, i + 1
        if token == "{":
            i += 1
            continue
        key = token
        i += 1
        if i >= len(tokens):
            break
        if tokens[i] == "{":
            block, i = _parse_vmt_block(tokens, i + 1)
            items.append((key, block))
        else:
            items.append((key, tokens[i]))
            i += 1
    return items, i


def parse_vmt(text: str) -> tuple[str | None, list[tuple[str, object]]]:
    tokens = list(_vmt_tokens(text))
    if not tokens:
        return None, []
    shader = tokens[0]
    index = 1
    while index < len(tokens) and tokens[index] != "{":
        index += 1
    body, _ = _parse_vmt_block(tokens, index + 1)
    return shader, body


def flatten_vmt(items: list[tuple[str, object]]):
    for key, value in items:
        if isinstance(value, list):
            yield from flatten_vmt(value)
        else:
            yield key, value


def material_path(ref: str, extension: str) -> str:
    """'models/x/tex' / 'materials/models/x/tex.vtf' -> materials/.../tex.vtf"""
    path = ref.strip().strip('"').replace("\\", "/").strip("/")
    if path.lower().startswith("materials/"):
        path = path[len("materials/") :]
    if extension and not path.lower().endswith(extension):
        path += extension
    return "materials/" + path.replace("//", "/")


# --------------------------------------------------------------------------
# Import planning
# --------------------------------------------------------------------------


@dataclass
class Planned:
    rel: str
    ref: FileRef


class Plan:
    def __init__(self):
        self.files: dict[str, Planned] = {}
        self.generated: dict[str, bytes] = {}
        self.existing: list[str] = []
        self.missing: dict[str, set[str]] = {}
        self.notes: list[str] = []

    def bytes_to_write(self) -> int:
        return sum(p.ref.size for p in self.files.values())

    def missing_for(self, rel: str, needed_by: str) -> None:
        self.missing.setdefault(rel, set()).add(needed_by)


class Importer:
    def __init__(
        self,
        catalog: Catalog,
        dest_root: Path,
        source: Source,
        *,
        force: bool = False,
        dry_run: bool = False,
        shader: str | None = None,
    ):
        self.catalog = catalog
        self.dest_root = dest_root
        self.source = source
        self.force = force
        self.dry_run = dry_run
        self.shader = shader
        self.plan = Plan()
        self._seen: set[str] = set()

    # -- expanding what the user asked for --------------------------------

    def expand(self, pattern: str) -> list[str]:
        entries = self.source.entries()
        wanted = norm_rel(pattern).lower()
        if not wanted and pattern.strip() == ".":
            return sorted(entries)
        if wanted in entries:
            return [wanted]
        if "*" in wanted or "?" in wanted:
            return sorted(rel for rel in entries if fnmatch.fnmatch(rel, wanted))
        prefix = wanted.rstrip("/") + "/"
        children = sorted(rel for rel in entries if rel.startswith(prefix))
        if children:
            return children
        if "/" not in wanted:
            by_name = sorted(
                rel for rel in entries if fnmatch.fnmatch(rel.rsplit("/", 1)[-1], wanted)
            )
            if by_name:
                return by_name
        for extension in (".mdl", ".vmt", ".vtf"):
            if wanted + extension in entries:
                return [wanted + extension]
        return []

    # -- adding one file and everything it needs --------------------------

    def lookup(self, rel: str) -> FileRef | None:
        """Find a file, preferring the source being imported from.

        Given two games that both ship `materials/models/foo.vmt`, a Portal
        import must take Portal's copy; catalog order would pick whichever
        game mounted first.
        """
        ref = self.source.find(rel)
        if ref is not None:
            return ref
        hit = self.catalog.find(rel)
        return None if hit is None else hit[1]

    def has(self, rel: str) -> bool:
        return self.lookup(rel) is not None

    def add(self, rel: str, needed_by: str = "<request>", explicit: bool = False) -> None:
        rel = norm_rel(rel).lower()
        if not rel or rel in self._seen:
            return
        self._seen.add(rel)

        target = self.dest_root / rel
        if target.exists() and not self.force:
            self.plan.existing.append(rel)
            self._analyse(rel, target.read_bytes, explicit)
            return

        ref = self.lookup(rel)
        if ref is None:
            self.plan.missing_for(rel, needed_by)
            return
        self.plan.files[rel] = Planned(rel, ref)
        self._analyse(rel, ref.read, explicit)

    # -- dependency walkers -----------------------------------------------

    def _analyse(self, rel: str, read, explicit: bool) -> None:
        extension = os.path.splitext(rel)[1].lower()
        if extension == ".mdl":
            self._analyse_model(rel, read())
        elif extension == ".vmt":
            self._analyse_vmt(rel, read())
        elif extension == ".vtf":
            self._analyse_vtf(rel, explicit)

    def _analyse_model(self, rel: str, data: bytes) -> None:
        stem = rel[: -len(".mdl")]
        try:
            info = parse_mdl(data)
        except (ValueError, struct.error) as error:
            self.plan.notes.append(f"{rel}: cannot read header ({error}); materials not resolved")
            for extension in (".vvd", ".dx90.vtx", ".dx80.vtx", ".sw.vtx", ".vtx", ".phy"):
                if self.has(stem + extension):
                    self.add(stem + extension, rel)
            return

        if info.version > STUDIO_VERSION:
            self.plan.notes.append(
                f"{rel}: studio version {info.version}; this engine reads up to "
                f"{STUDIO_VERSION}, so it may not load"
            )

        for extension in (".vvd", ".dx90.vtx", ".dx80.vtx", ".sw.vtx", ".vtx", ".phy"):
            if self.has(stem + extension):
                self.add(stem + extension, rel)
        if info.has_mesh:
            if not self.has(stem + ".vvd"):
                self.plan.missing_for(stem + ".vvd", rel)
            if not any(
                self.has(stem + extension)
                for extension in (".dx90.vtx", ".dx80.vtx", ".sw.vtx", ".vtx")
            ):
                self.plan.missing_for(stem + ".dx90.vtx", rel)
        if info.animblock:
            if self.has(info.animblock):
                self.add(info.animblock, rel)
            else:
                self.plan.missing_for(info.animblock, rel)

        for include in info.includes:
            if self.has(include):
                self.add(include, rel)
            else:
                self.plan.missing_for(include, rel)

        for candidates in model_material_candidates(info):
            found = next((rel for rel in candidates if self.has(rel)), None)
            if found is None:
                self.plan.missing_for(candidates[0], rel)
            else:
                self.add(found, rel)

    def _analyse_vmt(self, rel: str, data: bytes) -> None:
        text = data.decode("latin-1", "replace")
        shader, body = parse_vmt(text)
        pairs = list(flatten_vmt(body))

        if (shader or "").lower() == "patch":
            for key, value in pairs:
                if key.lower() in ("include", "$include"):
                    include = material_path(value, ".vmt")
                    if self.has(include):
                        self.add(include, rel)
                    else:
                        self.plan.missing_for(include, rel)

        for key, value in pairs:
            lowered_key = key.lower()
            lowered_value = value.strip().lower()
            if not lowered_value or lowered_value in NON_TEXTURE_VALUES:
                continue
            is_texture_key = lowered_key in TEXTURE_KEYS
            looks_like_texture = lowered_value.endswith(".vtf")
            if not (is_texture_key or looks_like_texture):
                continue
            texture = material_path(value, ".vtf")
            if is_render_target(texture):
                continue
            if self.has(texture):
                self.add(texture, rel)
            else:
                self.plan.missing_for(texture, rel)

        # Unknown keys can still carry textures (custom shaders, proxies): only
        # follow values that look like paths and actually exist.
        for key, value in pairs:
            if key.lower() in TEXTURE_KEYS:
                continue
            if "/" not in value and "\\" not in value:
                continue
            texture = material_path(value, ".vtf")
            if self.has(texture):
                self.add(texture, rel)

    def _analyse_vtf(self, rel: str, explicit: bool) -> None:
        if not explicit:
            return
        vmt_rel = rel[: -len(".vtf")] + ".vmt"
        # A material that is already in the destination was either imported or
        # written by hand; never replace it with a generated one.
        if (self.dest_root / vmt_rel).exists():
            return
        if self.has(vmt_rel):
            self.add(vmt_rel, rel)
            return
        self.plan.generated[vmt_rel] = self._synthesise_vmt(rel)

    def _synthesise_vmt(self, vtf_rel: str) -> bytes:
        ref = vtf_rel[: -len(".vtf")]
        if ref.lower().startswith("materials/"):
            ref = ref[len("materials/") :]
        shader = self.shader or (
            "VertexLitGeneric" if ref.lower().startswith("models/") else "LightmappedGeneric"
        )
        return (
            f'"{shader}"\n{{\n\t"$basetexture"\t"{ref}"\n}}\n'.encode("ascii", "replace")
        )


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------


def write_plan(plan: Plan, dest_root: Path, dry_run: bool) -> int:
    written = 0
    for rel in sorted(plan.files):
        planned = plan.files[rel]
        target = dest_root / rel
        if dry_run:
            print(f"  would write  {rel}  ({human_size(planned.ref.size)})")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(planned.ref.read())
        written += 1
    for rel, data in sorted(plan.generated.items()):
        target = dest_root / rel
        if dry_run:
            print(f"  would create {rel}  (generated material)")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        written += 1
    return written


def update_manifest(dest_root: Path, source_name: str, patterns: list[str], files: list[str]) -> None:
    manifest_path = dest_root / MANIFEST_NAME
    data: dict = {"files": {}, "history": []}
    if manifest_path.exists():
        try:
            data = json.loads(manifest_path.read_text())
        except (OSError, ValueError):
            pass
    data.setdefault("files", {})
    data.setdefault("history", [])
    stamp = now_iso()
    for rel in files:
        data["files"][rel] = source_name
    data["history"].append({"at": stamp, "source": source_name, "patterns": patterns})
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


# --------------------------------------------------------------------------
# Sources on the command line
# --------------------------------------------------------------------------


def detect_asset_root(path: Path) -> Path | None:
    if any((path / root).is_dir() for root in ASSET_ROOTS):
        return path
    candidates = [
        child
        for child in sorted(path.iterdir())
        if child.is_dir() and any((child / root).is_dir() for root in ASSET_ROOTS)
    ]
    if len(candidates) == 1:
        return candidates[0]
    return None


def source_from_path(path: Path) -> tuple[Source, list[str], bool]:
    """Build a Source from a folder / .vpk / .zip / single asset file."""
    path = Path(path).expanduser().resolve()
    implied: list[str] = []

    if path.is_file() and path.suffix.lower() == ".zip":
        return Source(path.stem, str(path), [ZipBundle(path)]), implied, True
    if path.is_file() and path.suffix.lower() == ".vpk":
        return Source(path.stem, str(path), [VpkBundle(path)]), implied, True
    if path.is_file() and path.suffix.lower() in MODEL_EXTENSIONS + MATERIAL_EXTENSIONS:
        parts = path.parts
        root_index = next(
            (i for i, part in enumerate(parts) if part.lower() in ASSET_ROOTS), None
        )
        if root_index is None:
            raise SystemExit(
                f"{path} is not inside a models/ or materials/ folder, so there is no "
                "asset root to import it from"
            )
        root = Path(*parts[:root_index])
        rel = path.relative_to(root).as_posix().lower()
        implied.append(rel)
        return Source(root.name or "custom", str(root), [DirBundle(root)]), implied, True
    if path.is_dir():
        root = detect_asset_root(path)
        vpks = sorted(path.glob("*_dir.vpk"))
        if root is None and not vpks:
            raise SystemExit(
                f"no models/ materials/ particles/ sound/ folder in {path}; "
                "point at the folder that contains them, or at a .zip/.vpk"
            )
        # A game content folder (Portal 2/portal2, Black Mesa/bms) keeps its
        # assets in split VPKs; taking the whole folder has to take those too.
        root = root or path
        bundles: list[Bundle] = [DirBundle(root)]
        for vpk_path in sorted(root.glob("*_dir.vpk")):
            try:
                bundles.append(VpkBundle(vpk_path))
            except (ValueError, OSError):
                continue
        return Source(root.name, str(root), bundles), implied, True
    raise SystemExit(f"no such source: {path}")


def resolve_source(argument: str, sources: list[Source]) -> tuple[Source, list[str], bool]:
    """Resolve a source name or a path.  Third value: was it an explicit path?"""
    candidate = Path(argument).expanduser()
    if candidate.exists():
        return source_from_path(candidate)
    wanted = argument.lower()
    wanted = {"ep1": "episodic"}.get(wanted, wanted)
    exact = [s for s in sources if s.name.lower() == wanted]
    if exact:
        return exact[0], [], False
    partial = [s for s in sources if s.name.lower().startswith(wanted)]
    if len(partial) == 1:
        return partial[0], [], False
    names = ", ".join(sorted(s.name for s in sources))
    raise SystemExit(f"unknown source '{argument}'. Known sources: {names}\n"
                     "A folder, .zip or .vpk path works here too.")


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------


def cmd_sources(args: argparse.Namespace) -> int:
    mounts = build_mounts()
    print(f"mod root: {MOD_ROOT}")
    print()
    width = max((len(m.name) for m in mounts), default=4)
    for mount in mounts:
        folders = [b.root for b in mount.bundles if isinstance(b, DirBundle)]
        vpks = [b for b in mount.bundles if isinstance(b, VpkBundle)]
        folder = folders[0] if folders else mount.path
        empty = not vpks and not any((folder / r).is_dir() for r in ASSET_ROOTS)
        detail = "empty" if empty else (f"{len(vpks)} vpk" if vpks else "loose files")
        print(f"  {mount.name:<{width}}  {detail:<12}  {folder}")

    # gameinfo entries that point nowhere are worth naming: Hammer cannot see
    # those assets either, which is usually why an import is needed.  A missing
    # single .vpk is not a problem when its whole folder is mounted too.
    paths, engine_root = read_search_paths()
    print()
    if engine_root:
        print(f"engine root (|all_source_engine_paths|): {engine_root}")
    mounted_dirs = {m.path.resolve() for m in mounts if m.path.is_dir()}
    missing = [
        (key, path)
        for key, path in paths
        if not path.exists() and path.parent.resolve() not in mounted_dirs
    ]
    if missing:
        print("\nmissing mount points:")
        for key, path in missing:
            print(f"  {key}: {path}")
        print("  (gameinfo.txt points there, but the content is not installed)")
    packs_root = MOD_ROOT / "custom"
    packs = sorted(p.name for p in packs_root.iterdir() if p.is_dir()) if packs_root.is_dir() else []
    if packs:
        print("\nimport packs (custom/*):")
        for pack in packs:
            print(f"  custom/{pack}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    sources = build_catalog()
    source, implied, _explicit = resolve_source(args.source, sources)
    patterns = list(args.pattern) + implied

    entries = source.entries()
    if not patterns:
        counts: dict[str, int] = {}
        for rel in entries:
            extension = os.path.splitext(rel)[1].lower() or "(none)"
            counts[extension] = counts.get(extension, 0) + 1
        print(f"{source.name}: {len(entries)} files  ({source.label})")
        for extension, count in sorted(counts.items(), key=lambda kv: -kv[1])[:15]:
            print(f"  {extension:<8} {count}")
        print("\npass a pattern to list matches, e.g.  list portal lab_desk")
        return 0

    matches: list[str] = []
    for pattern in patterns:
        wanted = norm_rel(pattern).lower()
        if wanted in entries:
            matches.append(wanted)
            continue
        if "*" in wanted or "?" in wanted:
            matches.extend(rel for rel in entries if fnmatch.fnmatch(rel, wanted))
            continue
        prefix = wanted.rstrip("/") + "/"
        children = [rel for rel in entries if rel.startswith(prefix)]
        if children:
            matches.extend(children)
        elif "/" not in wanted:
            matches.extend(
                rel for rel in entries if fnmatch.fnmatch(rel.rsplit("/", 1)[-1], wanted)
            )
        else:
            matches.extend(
                rel for rel in entries if rel.startswith(wanted) and rel[len(wanted)] == "."
            )

    matches = sorted(dict.fromkeys(matches))
    if not matches:
        print(f"nothing in {source.name} matches {' '.join(patterns)}")
        return 1
    shown = matches[: args.limit]
    for rel in shown:
        print(f"  {rel}  ({human_size(entries[rel])})")
    if len(matches) > len(shown):
        print(f"  ... {len(matches) - len(shown)} more (use --limit)")
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    sources = build_catalog()
    source, implied, explicit_path = resolve_source(args.source, sources)
    patterns = list(args.pattern) + implied
    if not patterns:
        if not explicit_path:
            print(
                "nothing to import: pass a model/material path or pattern "
                "(a whole game source is too much to import by default)",
                file=sys.stderr,
            )
            return 2
        # A folder/zip/vpk the user pointed at: take its models and materials.
        patterns = ["*.mdl", "*.vmt"]

    if args.pack:
        if not re.fullmatch(r"[A-Za-z0-9._-]+", args.pack):
            print(f"invalid pack name '{args.pack}'", file=sys.stderr)
            return 2
        dest_root = MOD_ROOT / "custom" / args.pack
        gameinfo_text = (
            GAMEINFO.read_text(encoding="latin-1", errors="replace")
            if GAMEINFO.exists()
            else ""
        )
        if not re.search(r"custom/\*", gameinfo_text):
            print(
                "note: gameinfo.txt has no 'custom/*' search path, so Hammer will not "
                "see this pack; import without --pack instead.",
                file=sys.stderr,
            )
    else:
        dest_root = MOD_ROOT

    importer = Importer(
        Catalog(sources),
        dest_root,
        source,
        force=args.force,
        dry_run=args.dry_run,
        shader=args.shader,
    )

    wanted: list[str] = []
    for pattern in patterns:
        expanded = importer.expand(pattern)
        if not expanded:
            print(f"nothing in {source.name} matches {pattern}", file=sys.stderr)
            continue
        wanted.extend(expanded)
    if not wanted:
        print("no files matched; nothing imported", file=sys.stderr)
        return 1

    for rel in sorted(dict.fromkeys(wanted)):
        importer.add(rel, "<request>", explicit=True)

    plan = importer.plan
    print(f"source: {source.name}  ({source.label})")
    print(f"destination: {dest_root}")

    written = write_plan(plan, dest_root, args.dry_run)

    if plan.existing:
        shown = plan.existing[:6] if not args.verbose else plan.existing
        for rel in shown:
            print(f"  kept existing {rel}  (use --force to overwrite)")
        if len(plan.existing) > len(shown):
            print(f"  ... and {len(plan.existing) - len(shown)} more kept existing")

    if plan.notes:
        print("\nnotes:")
        for note in plan.notes:
            print(f"  {note}")

    if plan.missing:
        print("\nnot found in any mounted source (will show as error/pink in Hammer):")
        for rel, parents in sorted(plan.missing.items()):
            parent = ", ".join(sorted(parents)[:2])
            print(f"  {rel}  <- {parent}")

    total = plan.bytes_to_write()
    if args.dry_run:
        print(f"\ndry run: {len(plan.files) + len(plan.generated)} files, {human_size(total)}")
        return 0

    print(
        f"\n{written} files written ({human_size(total)}), "
        f"{len(plan.existing)} kept, {len(plan.missing)} missing"
    )
    if written:
        update_manifest(
            dest_root,
            source.name,
            patterns,
            sorted(list(plan.files) + list(plan.generated)),
        )
        print("reopen the model/material browser in Hammer to see the new files")
    return 0


def cmd_unimport(args: argparse.Namespace) -> int:
    root = (MOD_ROOT / "custom" / args.pack) if args.pack else MOD_ROOT
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.exists():
        print(f"no import manifest at {manifest_path}", file=sys.stderr)
        return 1
    try:
        data = json.loads(manifest_path.read_text())
    except ValueError:
        print(f"{manifest_path} is not valid JSON", file=sys.stderr)
        return 1
    files = sorted(data.get("files", {}))
    if not files:
        print("manifest lists no files")
        return 0
    removed = 0
    for rel in files:
        target = root / rel
        if target.is_file():
            target.unlink()
            removed += 1
            parent = target.parent
            while parent != root and parent.is_dir():
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent
    manifest_path.unlink()
    print(f"removed {removed} of {len(files)} files listed in {manifest_path}")
    if args.pack and root.is_dir() and not any(root.iterdir()):
        root.rmdir()
        print(f"removed empty pack custom/{args.pack}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    mounts = build_mounts()
    catalog = Catalog([Source(m.name, str(m.path), m.bundles) for m in mounts])
    if not mounts or mounts[0].name != "mod":
        print("gameinfo.txt is missing, so there is nothing to check", file=sys.stderr)
        return 2

    # Check everything this mod ships: its own folders and any custom/* packs.
    # Mounts that live outside the mod (hl2, portal, ...) are dependencies, not
    # things to audit, so only folders inside MOD_ROOT are scanned.
    local: list[tuple[str, Bundle]] = []
    for mount in mounts:
        bundle = next((b for b in mount.bundles if isinstance(b, DirBundle)), None)
        if bundle is None:
            continue
        try:
            bundle.root.resolve().relative_to(MOD_ROOT)
        except (OSError, ValueError):
            continue
        local.append((str(bundle.root), bundle))

    patterns = [norm_rel(p).lower() for p in args.pattern]

    def selected(rel: str) -> bool:
        if not patterns:
            return True
        return any(
            rel == p
            or fnmatch.fnmatch(rel, p)
            or rel.startswith(p.rstrip("/") + "/")
            for p in patterns
        )

    entries: dict[str, tuple[Bundle, str]] = {}
    for folder, bundle in local:
        for rel in bundle.entries():
            entries.setdefault(rel, (bundle, str(folder)))
    models = [rel for rel in sorted(entries) if rel.endswith(".mdl") and selected(rel)]
    vmts = [rel for rel in sorted(entries) if rel.endswith(".vmt") and selected(rel)]

    problems: list[str] = []
    notes: list[str] = []

    def label_for(rel: str) -> str:
        folder = entries[rel][1]
        prefix = Path(folder).resolve().relative_to(MOD_ROOT).as_posix()
        return rel if prefix == "." else f"{prefix}/{rel}"

    for rel in models:
        bundle, _folder = entries[rel]
        label = label_for(rel)
        try:
            info = parse_mdl(bundle.read(rel))
        except (ValueError, struct.error, OSError) as error:
            problems.append(f"{label}: unreadable header ({error})")
            continue
        if info.version > STUDIO_VERSION:
            notes.append(
                f"{label}: studio version {info.version}; this engine reads up to {STUDIO_VERSION}"
            )
        stem = rel[: -len(".mdl")]
        if info.has_mesh:
            if not catalog.has(stem + ".vvd"):
                problems.append(f"{label}: no {stem.split('/')[-1]}.vvd")
            if not any(
                catalog.has(stem + extension)
                for extension in (".dx90.vtx", ".dx80.vtx", ".sw.vtx", ".vtx")
            ):
                problems.append(f"{label}: no .vtx (model will not load)")
        for include in info.includes:
            if not catalog.has(include):
                problems.append(f"{label}: $includemodel {include} is missing")
        for candidates in model_material_candidates(info):
            if not any(catalog.has(candidate) for candidate in candidates):
                problems.append(f"{label}: material {candidates[0]} is missing")

    # A texture or particle file from a newer Source build imports cleanly and
    # then draws pink (or silently does nothing) in game, so gate on it here too.
    format_stats = FormatStats()
    for rel in (
        r for r in sorted(entries) if r.endswith((".vtf", ".pcf")) and selected(r)
    ):
        examine_asset(entries[rel][0], rel, format_stats)
    for problem_rel, label in format_stats.too_new:
        notes.append(
            f"{label_for(problem_rel)}: {label}; this engine reads vtf up to "
            f"{VTF_VERSION[0]}.{VTF_VERSION[1]} and pcf {PCF_VERSION}"
        )

    for rel in vmts:
        bundle, _folder = entries[rel]
        label = label_for(rel)
        text = bundle.read(rel).decode("latin-1", "replace")
        shader, body = parse_vmt(text)
        pairs = list(flatten_vmt(body))
        if (shader or "").lower() == "patch":
            for key, value in pairs:
                if key.lower() in ("include", "$include"):
                    include = material_path(value, ".vmt")
                    if not catalog.has(include):
                        problems.append(f"{label}: patch include {include} is missing")
        for key, value in pairs:
            lowered_key = key.lower()
            lowered_value = value.strip().lower()
            if not lowered_value or lowered_value in NON_TEXTURE_VALUES:
                continue
            if lowered_key not in TEXTURE_KEYS and not lowered_value.endswith(".vtf"):
                continue
            texture = material_path(value, ".vtf")
            if is_render_target(texture):
                continue
            if not catalog.has(texture):
                problems.append(f"{label}: texture {texture} is missing")

    if args.verbose:
        for rel in models:
            print(f"model    {label_for(rel)}")
        for rel in vmts:
            print(f"material {label_for(rel)}")

    locations = ", ".join(
        sorted(
            {
                "mod root"
                if str(Path(folder).resolve()) == str(MOD_ROOT)
                else Path(folder).resolve().relative_to(MOD_ROOT).as_posix()
                for folder, _b in local
            }
        )
    )
    print(f"checked {len(models)} models and {len(vmts)} materials in {locations}")
    for note in notes:
        print(f"note: {note}")
    if not problems:
        print("no missing dependencies")
        return 0

    print(f"\n{len(problems)} problem(s):")
    for problem in problems[: args.limit]:
        print(f"  {problem}")
    if len(problems) > args.limit:
        print(f"  ... {len(problems) - args.limit} more (use --limit)")
    return 1


# --------------------------------------------------------------------------
# Whole-source commands: audit / bake / release
# --------------------------------------------------------------------------

# What a folder is allowed to contribute when a whole source is copied.  Keeping
# the list explicit means a bake never drags in level .bsp, .lst or readme files.
BAKE_EXTENSIONS = {
    "models": (".mdl", ".vvd", ".vtx", ".phy", ".ani"),
    "materials": (".vmt", ".vtf"),
    "particles": (".pcf",),
    "sound": (".wav", ".mp3", ".ogg"),
}
BAKE_DEFAULT = "models,materials,particles"


def format_summary(stats: FormatStats, limit: int) -> None:
    print("formats in this source:")
    for label in sorted(stats.counts):
        print(f"  {label:<26} {stats.counts[label]}")
    if not stats.too_new:
        print("  everything is a format this engine reads")
        return
    print(
        f"\n  {len(stats.too_new)} file(s) are a format this engine cannot load "
        f"(studio > {STUDIO_VERSION}, vtf > {VTF_VERSION[0]}.{VTF_VERSION[1]}, "
        f"pcf > {PCF_VERSION}):"
    )
    for rel, label in stats.too_new[:limit]:
        print(f"    {rel}  ({label})")
    if len(stats.too_new) > limit:
        print(f"    ... {len(stats.too_new) - limit} more (use --limit)")


def cmd_audit(args: argparse.Namespace) -> int:
    sources = build_catalog()
    source, _implied, _explicit = resolve_source(args.source, sources)
    entries = source.entries()

    counts: dict[str, int] = {}
    for rel in entries:
        extension = os.path.splitext(rel)[1].lower() or "(none)"
        counts[extension] = counts.get(extension, 0) + 1

    stats = FormatStats()
    for rel in sorted(entries):
        if os.path.splitext(rel)[1].lower() not in (".mdl", ".vtf", ".pcf"):
            continue
        ref = source.find(rel)
        if ref is not None:
            examine_asset(ref.bundle, rel, stats)

    print(f"{source.name}: {len(entries)} files  ({source.label})")
    for extension, count in sorted(counts.items(), key=lambda kv: -kv[1])[:10]:
        print(f"  {extension:<12} {count}")
    print()
    format_summary(stats, args.limit)
    if stats.too_new:
        print(
            "\nThose cannot be fixed by copying: they need converting first "
            "(decompile + recompile models, re-encode textures)."
        )
    return 0


def bake_destination(pack: str | None) -> Path:
    if not pack:
        return MOD_ROOT
    if not re.fullmatch(r"[A-Za-z0-9._-]+", pack):
        raise SystemExit(f"invalid pack name '{pack}'")
    return MOD_ROOT / "custom" / pack


def cmd_bake(args: argparse.Namespace) -> int:
    sources = build_catalog()
    source, _implied, _explicit = resolve_source(args.source, sources)

    folders = [f.strip().lower() for f in (args.only or BAKE_DEFAULT).split(",") if f.strip()]
    unknown = [f for f in folders if f not in BAKE_EXTENSIONS]
    if unknown:
        print(
            f"unknown folder(s): {', '.join(unknown)}\n"
            f"choose from: {', '.join(BAKE_EXTENSIONS)}",
            file=sys.stderr,
        )
        return 2

    selection: list[str] = []
    for rel in sorted(source.entries()):
        folder = rel.split("/", 1)[0]
        if folder not in folders:
            continue
        if os.path.splitext(rel)[1].lower() not in BAKE_EXTENSIONS[folder]:
            continue
        if args.pattern and not any(
            fnmatch.fnmatch(rel, pattern) or rel.startswith(norm_rel(pattern) + "/")
            for pattern in args.pattern
        ):
            continue
        selection.append(rel)

    if not selection:
        print(f"nothing in {source.name} matches", file=sys.stderr)
        return 1

    dest_root = bake_destination(args.pack)
    importer = Importer(
        Catalog(sources),
        dest_root,
        source,
        force=args.force,
        dry_run=args.dry_run,
    )
    for rel in selection:
        # explicit=False: a baked texture must not grow a generated .vmt, the
        # game's own material has to come with it or the texture is unreachable.
        importer.add(rel, "<bake>", explicit=False)

    plan = importer.plan
    stats = FormatStats()
    for rel, planned in sorted(plan.files.items()):
        if os.path.splitext(rel)[1].lower() in (".mdl", ".vtf", ".pcf"):
            examine_asset(planned.ref.bundle, rel, stats)

    per_folder = {
        folder: sum(1 for rel in selection if rel.startswith(folder + "/"))
        for folder in folders
    }
    print(f"source: {source.name}  ({source.label})")
    print(f"destination: {dest_root}")
    print(
        f"selected: {len(selection):,} files  ("
        + ", ".join(f"{n:,} in {folder}/" for folder, n in per_folder.items())
        + ")"
    )
    print(
        f"planned: {len(plan.files) + len(plan.generated):,} files, "
        f"{human_size(plan.bytes_to_write())}"
        f" ({len(plan.existing):,} already in the mod)"
    )
    print()
    format_summary(stats, args.limit)

    if plan.notes and args.verbose:
        print("\nnotes:")
        for note in plan.notes:
            print(f"  {note}")

    if plan.missing:
        print(f"\nnot found in {source.name} or any mounted source:")
        for rel, parents in sorted(plan.missing.items())[: args.limit]:
            print(f"  {rel}  <- {', '.join(sorted(parents)[:2])}")
        if len(plan.missing) > args.limit:
            print(f"  ... {len(plan.missing) - args.limit} more (use --limit)")

    if args.dry_run:
        print("\ndry run: nothing written")
        return 0

    written = write_plan(plan, dest_root, False)
    print(f"\n{written} files written ({human_size(plan.bytes_to_write())})")
    if written:
        update_manifest(
            dest_root,
            source.name,
            args.pattern or [f"{folder}/*" for folder in folders],
            sorted(list(plan.files) + list(plan.generated)),
        )
        if args.pack:
            print(f"pack: custom/{args.pack}  (remove with: unimport --pack {args.pack})")
        print("this content now lives in the mod; gameinfo.txt no longer needs it mounted")
    return 0


MISSING_LABEL = "missing everywhere"


def local_and_external_mounts() -> tuple[list[Mount], list[Mount]]:
    local: list[Mount] = []
    external: list[Mount] = []
    for mount in build_mounts():
        try:
            mount.path.resolve().relative_to(MOD_ROOT)
        except (OSError, ValueError):
            external.append(mount)
        else:
            local.append(mount)
    return local, external


def release_gameinfo_text(text: str) -> str:
    """Drop every content mount that is not inside this mod.

    ``|gameinfo_path|`` paths and ``platform`` stay; everything else (hl2,
    episodic, ep2 and the absolute Portal path) is what baking replaces.
    """
    kept: list[str] = []
    for line in text.splitlines():
        stripped = line.strip().lower()
        if stripped.startswith("platform"):
            kept.append(line)
        elif "|gameinfo_path|" in stripped:
            kept.append(line)
        elif "|" in stripped and "|all_source_engine_paths|" in stripped:
            continue
        elif stripped.startswith(("game\t", "game ", "game+mod", "mod+mod_write", "gamebin")):
            continue
        else:
            kept.append(line)
    header = [
        "		// Generated by tools/import_assets.py release --write.",
        "		// External game content has been baked into this mod, so only the mod",
        "		// itself is mounted. Keep gameinfo.txt (with its mounts) for editing.",
    ]
    out: list[str] = []
    inside_search_paths = False
    inserted = False
    for line in kept:
        out.append(line)
        stripped = line.strip().lower()
        if stripped == "searchpaths":
            inside_search_paths = True
        elif inside_search_paths and not inserted and stripped == "{":
            out.extend(header)
            inserted = True
    return "\n".join(out) + "\n"


def cmd_release(args: argparse.Namespace) -> int:
    local, external = local_and_external_mounts()
    if not local:
        print("gameinfo.txt is missing, so there is nothing to release", file=sys.stderr)
        return 2

    local_catalog = Catalog([Source(m.name, str(m.path), m.bundles) for m in local])
    external_catalog = Catalog([Source(m.name, str(m.path), m.bundles) for m in external])

    # Resolving every dependency against the mod alone puts exactly the files
    # that would have to be mounted into plan.missing.
    scratch = Path(tempfile.mkdtemp(prefix="hls-release-"))
    importer = Importer(local_catalog, scratch, local_catalog.sources[0], dry_run=True)
    models = materials = 0
    for source in local_catalog.sources:
        for rel in sorted(source.entries()):
            extension = os.path.splitext(rel)[1].lower()
            if extension == ".mdl":
                models += 1
            elif extension == ".vmt":
                materials += 1
            else:
                continue
            importer.add(rel, "<release>", explicit=False)

    missing = importer.plan.missing
    print(f"checked {models} models and {materials} materials inside the mod")
    if not missing:
        print("self-contained: every dependency resolves inside the mod")
    else:
        by_source: dict[str, list[str]] = {}
        for rel in missing:
            hit = external_catalog.find(rel)
            by_source.setdefault(hit[0].name if hit else MISSING_LABEL, []).append(rel)
        total = sum(len(rels) for rels in by_source.values())
        print(f"\n{total} file(s) still come from mounted games:")
        for name in sorted(by_source, key=lambda n: -len(by_source[n])):
            rels = sorted(by_source[name])
            print(f"  {name:<14} {len(rels)} file(s)")
            for rel in rels[:4]:
                print(f"      {rel}")
            if len(rels) > 4:
                print(f"      ... {len(rels) - 4} more")
        bakeable = [name for name in sorted(by_source) if name != MISSING_LABEL]
        if bakeable:
            print("\nbake those sources to stop depending on them:")
            for name in bakeable:
                print(f"  tools/import_assets.py bake {name}")

    if args.write:
        if missing:
            print(
                f"\nrefusing to write {args.write}: the mod is not self-contained yet",
                file=sys.stderr,
            )
            return 1
        target = Path(args.write)
        if not target.is_absolute():
            target = MOD_ROOT / target
        target.parent.mkdir(parents=True, exist_ok=True)
        text = GAMEINFO.read_text(encoding="latin-1", errors="replace")
        target.write_text(release_gameinfo_text(text), encoding="latin-1")
        print(f"\nwrote mount-free gameinfo: {target}")

    return 1 if missing else 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="import_assets.py",
        description=(
            "Copy Source models, materials, particles and sounds into this mod, "
            "following their dependencies, so Hammer's model and material "
            "browsers can use them."
        ),
        epilog=(
            "sources: mod, hl2, ep2, episodic, platform, portal (from gameinfo.txt)\n"
            "         or any folder / .zip / .vpk path\n\n"
            "examples:\n"
            "  import_assets.py list portal lab_desk\n"
            "  import_assets.py import portal models/props/lab_desk01/lab_desk01.mdl\n"
            "  import_assets.py import ~/Downloads/coolgun.zip\n"
            "  import_assets.py import --pack myprops portal 'models/props/*.mdl'\n"
            "  import_assets.py audit '/media/.../Portal 2/portal2'\n"
            "  import_assets.py bake portal\n"
            "  import_assets.py release --write dist/gameinfo.txt\n"
            "  import_assets.py check\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("sources", help="list the mounts Hammer can see, and missing ones")
    p.set_defaults(func=cmd_sources)

    p = sub.add_parser("list", help="search a source for assets")
    p.add_argument("source", help="source name or folder/zip/vpk path")
    p.add_argument("pattern", nargs="*", help="path, glob or filename (optional)")
    p.add_argument("--limit", type=int, default=60, help="max rows to print")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("import", help="copy assets and their dependencies into the mod")
    p.add_argument("source", help="source name or folder/zip/vpk path")
    p.add_argument("pattern", nargs="*", help="model/material path, glob or directory")
    p.add_argument("--pack", help="install under custom/<NAME>/ instead of the mod root")
    p.add_argument("--force", action="store_true", help="overwrite files that already exist")
    p.add_argument("--dry-run", action="store_true", help="show what would be copied")
    p.add_argument("--verbose", action="store_true", help="list every kept file")
    p.add_argument(
        "--shader",
        help="shader for materials generated from bare .vtf files "
        "(default: VertexLitGeneric under models/, else LightmappedGeneric)",
    )
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("unimport", help="remove files recorded in an import manifest")
    p.add_argument("--pack", help="pack name under custom/ (omit for imports into the mod root)")
    p.set_defaults(func=cmd_unimport)

    p = sub.add_parser(
        "audit",
        help="report the asset formats in a source and which this engine can load",
    )
    p.add_argument("source", help="source name or folder/zip/vpk path")
    p.add_argument("--limit", type=int, default=25, help="max unsupported files to list")
    p.set_defaults(func=cmd_audit)

    p = sub.add_parser(
        "bake",
        help="copy a whole game's assets into the mod so it need not be mounted",
    )
    p.add_argument("source", help="source name or game folder / .vpk path")
    p.add_argument("pattern", nargs="*", help="limit to matching paths")
    p.add_argument(
        "--only",
        help=f"comma-separated folders to take (default: {BAKE_DEFAULT}; "
        f"available: {', '.join(BAKE_EXTENSIONS)})",
    )
    p.add_argument("--pack", help="install under custom/<NAME>/ instead of the mod root")
    p.add_argument("--force", action="store_true", help="overwrite files that already exist")
    p.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    p.add_argument("--verbose", action="store_true", help="show per-file notes")
    p.add_argument("--limit", type=int, default=15, help="max rows to print")
    p.set_defaults(func=cmd_bake)

    p = sub.add_parser(
        "release",
        help="check that the mod resolves everything without mounted games",
    )
    p.add_argument(
        "--write",
        metavar="PATH",
        help="write a mount-free gameinfo there (only when fully self-contained)",
    )
    p.set_defaults(func=cmd_release)

    p = sub.add_parser("check", help="report models/materials whose dependencies are missing")
    p.add_argument("pattern", nargs="*", help="limit the check to matching paths")
    p.add_argument("--limit", type=int, default=40, help="max problems to print")
    p.add_argument("--verbose", action="store_true", help="list every file checked")
    p.set_defaults(func=cmd_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
