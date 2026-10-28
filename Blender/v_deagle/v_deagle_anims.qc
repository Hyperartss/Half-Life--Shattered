// Deagle on HL2's v_pistol skeleton (tools/build_deagle_on_pistol.py).
// Compiles to models/sl_animtest/v_deagle.mdl, not to models/weapons/v_deagle.mdl
// Import in Blender with Blender Source Tools
// (File > Import > Source Engine QC) for the rig plus one action per sequence.
$modelname "sl_animtest/v_deagle.mdl"
$cdmaterials "models/weapons/v_deagle/"
$cdmaterials "models/weapons/v_wrench/"
$model "v_deagle" "anims/ref.smd"

$sequence "idle01" "anims/idle01.smd" fps 30 ACT_VM_IDLE 1 loop
$sequence "idle01empty" "anims/idle01empty.smd" fps 30 ACT_VM_IDLE_EMPTY 1 loop
$sequence "fire" "anims/fire.smd" fps 30 ACT_VM_PRIMARYATTACK 1
$sequence "fire1" "anims/fire1.smd" fps 30 ACT_VM_RECOIL1 1
$sequence "fire2" "anims/fire2.smd" fps 30 ACT_VM_RECOIL2 1
$sequence "fire3" "anims/fire3.smd" fps 30 ACT_VM_RECOIL3 1
$sequence "fireempty" "anims/fireempty.smd" fps 30 ACT_VM_DRYFIRE 1
$sequence "draw" "anims/draw.smd" fps 30 ACT_VM_DRAW 1
$sequence "drawempty" "anims/drawempty.smd" fps 30
$sequence "reload" "anims/reload.smd" fps 30 ACT_VM_RELOAD 1
$sequence "holster" "anims/holster.smd" fps 30 ACT_VM_HOLSTER 1
$sequence "holsterempty" "anims/holsterempty.smd" fps 30 ACT_VM_HOLSTER 1
$sequence "idletolow" "anims/idletolow.smd" fps 30 ACT_VM_LOWERED_TO_IDLE 1
$sequence "lowtoidle" "anims/lowtoidle.smd" fps 30 ACT_VM_IDLE_TO_LOWERED 1
$sequence "lowidle" "anims/lowidle.smd" fps 30 ACT_VM_IDLE_LOWERED 1 loop
