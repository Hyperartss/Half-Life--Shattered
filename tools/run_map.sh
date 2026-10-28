#!/bin/bash
# Compile a map for HLShattered and (optionally) load it in the game.
#
#   tools/run_map.sh maps/my_map.vmf     # vbsp + vvis + vrad, then launch
#   tools/run_map.sh maps/my_map -nolan  # compile only
#
# Compiles with the SDK's own tools through Wine, exactly like Hammer's
# Run Map does, and drops the .bsp in HLShattered/maps.
set -u

SDK="$HOME/.steam/steam/steamapps/common/Source SDK Base 2013 Singleplayer"
MOD="$HOME/.steam/steam/steamapps/sourcemods/HLShattered"
export WINEPREFIX="$HOME/.config/linuxhammerlauncher/prefix"

G='Z:\home\hyper\.steam\debian-installation\steamapps\sourcemods\HLShattered'

if [ $# -lt 1 ]; then
    echo "usage: $0 <map.vmf|mapname> [-nolan]" >&2
    exit 2
fi

arg="$1"
case "$arg" in
    *.vmf) src="$arg" ;;
    *)     src="$MOD/maps/$arg.vmf" ;;
esac
[ -f "$src" ] || { echo "no such map: $src" >&2; exit 1; }

name="$(basename "$src" .vmf)"
cd "$SDK/binwin" || exit 1

run() { timeout "${2:-400}" wine "$1" -game "$G" "$3" 2>&1; }

echo "== vbsp $name"
run vbsp.exe 180 "$G\\maps\\$name.vmf" | tail -3
echo "== vvis $name"
run vvis.exe 180 "$G\\maps\\$name" | tail -3
echo "== vrad $name"
run vrad.exe 400 "$G\\maps\\$name" | tail -3

bsp="$MOD/maps/$name.bsp"
[ -f "$bsp" ] || { echo "compile produced no bsp" >&2; exit 1; }
echo "== built $bsp ($(stat -c %s "$bsp") bytes)"

if [ "${2:-}" = "-nolan" ]; then
    exit 0
fi

# launch through the native Steam client (the game runs under Proton, not in
# Hammer's Wine prefix, so this is the only way to actually play the map)
echo "== launching $name in HLShattered"
exec steam -applaunch 243730 -game "$G" +map "$name"
