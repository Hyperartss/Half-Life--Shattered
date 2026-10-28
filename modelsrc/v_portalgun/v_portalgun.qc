// Shattered Life - Portal gun viewmodel
// Gun only: Portal Gun 3 (Sketchfab), hands/arms removed and bound rigidly to
// ValveBiped.Base on the stock Portal 1 viewmodel skeleton.
// Animations are Portal 1's, exported to Blender/v_portalgun/anims.
$modelname "weapons/v_portalgun.mdl"
$cdmaterials "models/weapons/v_portalgun/"
$surfaceprop "metal"
$model "portalgun" "v_portalgun_ref.smd"
$attachment "muzzle" "ValveBiped.Base" -0.020 -0.340 31.563 rotate 0 0 0

$sequence "idle" "../../Blender/v_portalgun/anims/idle.smd" fps 30 ACT_VM_IDLE 1 loop
$sequence "fire1" "../../Blender/v_portalgun/anims/fire1.smd" fps 30 ACT_VM_PRIMARYATTACK 1
$sequence "fizzle" "../../Blender/v_portalgun/anims/fizzle.smd" fps 30 ACT_VM_FIZZLE 1
$sequence "draw" "../../Blender/v_portalgun/anims/draw.smd" fps 30 ACT_VM_DRAW 1
$sequence "holster" "../../Blender/v_portalgun/anims/holster.smd" fps 30 ACT_VM_HOLSTER 1
$sequence "idletolow" "../../Blender/v_portalgun/anims/idletolow.smd" fps 30 ACT_VM_LOWERED_TO_IDLE 1
$sequence "lowtoidle" "../../Blender/v_portalgun/anims/lowtoidle.smd" fps 30 ACT_VM_IDLE_TO_LOWERED 1
$sequence "lowidle" "../../Blender/v_portalgun/anims/lowidle.smd" fps 30 ACT_VM_IDLE_LOWERED 1 loop
$sequence "pickup" "../../Blender/v_portalgun/anims/pickup.smd" fps 30 ACT_VM_PICKUP 1
$sequence "release" "../../Blender/v_portalgun/anims/release.smd" fps 30 ACT_VM_RELEASE 1
