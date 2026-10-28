#!/bin/bash
# Open SDK 2013 Hammer++ on HLShattered, with this mod's textures/models/maps.
#
#   tools/hammer.sh                 # open Hammer++ with the mod active
#   tools/hammer.sh maps/foo.vmf    # ...and load a map straight away
#
# Why this exists: the Linux Hammer Launcher writes hammerplusplus_gameconfig.txt
# with HL2 / EP1 / EP2 / SourceTest only, so those configs point Hammer at the
# SDK's own (empty) mapsrc folders and none of the mod's content. This script
# makes sure a HLShattered entry is present, marks it active, and starts Hammer++
# in the Wine prefix the launcher set up (the one with DXVK/d3dx9).
set -u

SDK="$HOME/.steam/steam/steamapps/common/Source SDK Base 2013 Singleplayer"
MOD="$HOME/.steam/steam/steamapps/sourcemods/HLShattered"
CFG="$SDK/binwin/hammerplusplus/hammerplusplus_gameconfig.txt"
export WINEPREFIX="$HOME/.config/linuxhammerlauncher/prefix"
export DISPLAY="${DISPLAY:-:0}"

# Use the resolved Steam path: the Source tools refuse the .steam/steam symlink.
WIN_SDK='Z:\home\hyper\.steam\debian-installation\steamapps\common\Source SDK Base 2013 Singleplayer'
WIN_MOD='Z:\home\hyper\.steam\debian-installation\steamapps\sourcemods\HLShattered'

# 1. make sure the config entry exists and is the active one
python3 - "$CFG" "$WIN_SDK" "$WIN_MOD" <<'PY'
import re, sys

cfg, sdk, mod = sys.argv[1], sys.argv[2], sys.argv[3]
bw = sdk + r"\binwin"
name = "HLShattered"

raw = open(cfg, "rb").read().decode()
if '"%s"' % name not in raw:
    block = f'''\t\t"{name}"
\t\t{{
\t\t\t"GameDir"\t\t"{mod}"
\t\t\t"Hammer"
\t\t\t{{
\t\t\t\t"TextureFormat"\t\t"5"
\t\t\t\t"MapFormat"\t\t"4"
\t\t\t\t"DefaultTextureScale"\t\t"0.250000"
\t\t\t\t"DefaultLightmapScale"\t\t"16"
\t\t\t\t"DefaultSolidEntity"\t\t"func_detail"
\t\t\t\t"DefaultPointEntity"\t\t"info_player_start"
\t\t\t\t"GameExeDir"\t\t"{sdk}"
\t\t\t\t"MapDir"\t\t"{mod}\\maps"
\t\t\t\t"CordonTexture"\t\t"tools\\\\toolsskybox"
\t\t\t\t"MaterialExcludeCount"\t\t"0"
\t\t\t\t"GameExe"\t\t"{bw}\\hls_rungame.bat"
\t\t\t\t"BSP"\t\t"{bw}\\vbsp.exe"
\t\t\t\t"Vis"\t\t"{bw}\\vvis.exe"
\t\t\t\t"Light"\t\t"{bw}\\vrad.exe"
\t\t\t\t"BSPDir"\t\t"{mod}\\maps"
\t\t\t\t"GameData0"\t\t"{bw}\\portal.fgd"
\t\t\t\t"MDL"\t\t"{bw}\\studiomdl.exe"
\t\t\t}}
\t\t}}
'''.replace("\n", "\r\n")
    anchor = '\t}\r\n\t"SDKVersion"'
    if anchor in raw:
        raw = raw.replace(anchor, block + anchor)
    else:
        sys.exit("could not find the end of the Games block in " + cfg)

# mark HLShattered active, clear the others
for m in re.finditer(r'^\t\t"([^"\r\n]+)"\r\n\t\t\{', raw, re.M):
    gname = m.group(1)
    blk = re.search(r'(\t\t"' + re.escape(gname) + r'"\r\n\t\t\{.*?)(\t\t\}\r\n)', raw, re.S)
    if not blk:
        continue
    val = "1" if gname == name else "0"
    body = blk.group(1)
    if '"Previous"' in body:
        body = re.sub(r'"Previous"\t+"[^"]*"', '"Previous"\t\t"' + val + '"', body)
    else:
        body = body.rstrip("\r\n") + '\r\n\t\t\t\t"Previous"\t\t"' + val + '"\r\n'
    raw = raw[:blk.start(1)] + body + raw[blk.end(1):]

open(cfg, "wb").write(raw.encode())
PY

# 2. launch, optionally with a map
cd "$SDK/binwin" || exit 1
if [ $# -ge 1 ]; then
    map="$1"
    case "$map" in
        /*) map="Z:$(printf '%s' "$map" | tr '/' '\\')" ;;
    esac
    nohup wine hammerplusplus.exe "$map" > /tmp/hammer_hls.log 2>&1 &
else
    nohup wine hammerplusplus.exe > /tmp/hammer_hls.log 2>&1 &
fi
echo "Hammer++ starting (HLShattered config). Log: /tmp/hammer_hls.log"
echo "Maps folder: $MOD/maps   (also in the file dialog's Favorites)"
