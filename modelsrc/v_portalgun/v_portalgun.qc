// Shattered Life - Portal gun viewmodel
// Gun only: Portal Gun 3 (Sketchfab), hands/arms removed and bound rigidly to
// ValveBiped.Base on the stock Portal 1 viewmodel skeleton.
// Animations are Portal 1's, exported to Blender/v_portalgun/anims.
$modelname "weapons/v_portalgun.mdl"
$cdmaterials "models/weapons/v_portalgun/"
$surfaceprop "metal"
$model "portalgun" "v_portalgun_ref.smd"

// Attachments. The client's portal gun effect looks these up on the viewmodel
// by name (C_WeaponPortalgun::StartEffects): Body_light for the body glow
// sprite, Inside_effects for the barrel effect, Beam_point1-5 for the beam and
// Arm{1,2,3}_attach{1,2,3} for the prong glows/flares. Without them those
// effects draw at a stale position, which is the stray particle that shows up
// when the viewmodel swings.
//
// Everything is on ValveBiped.Base because this model has no Front_Cover/arm
// detail bones - the gun is rigid to Base. QC `rotate` is in degrees, as
// pitch/yaw/roll; the sprite and beam points don't use their rotation.
//
// The positions are NOT the stock Portal 1 coordinates: this gun has a
// different body and its own three prongs, and the stock numbers left the body
// light hanging 2.2 units off the shell and the three prong flares ~4 units in
// front of it (three lights floating in the air). Each point was instead
// snapped onto this mesh: Body_light on top of the body, one prong's root/mid/
// tip per Arm (placed 0.1-0.2 units proud of the surface so the glow isn't
// buried), Inside_effects on the barrel face and the beam points just behind
// it on the barrel axis. tools/build_portalgun.py prints these, as does
// `blender -b --python tools/preview_viewmodel.py -- ... att` style renders.
$attachment "Body_light" "ValveBiped.Base" -0.211 3.567 10.567 rotate 0.0000 0.0000 0.0000
$attachment "Inside_effects" "ValveBiped.Base" 0.000 2.200 22.656 rotate 0.0000 0.0000 0.0000
$attachment "Beam_point1" "ValveBiped.Base" 0.005 2.400 19.556 rotate 0.0000 0.0000 0.0000
$attachment "Beam_point2" "ValveBiped.Base" -0.012 2.388 19.256 rotate 0.0000 0.0000 0.0000
$attachment "Beam_point3" "ValveBiped.Base" -0.025 2.375 18.956 rotate 0.0000 0.0000 0.0000
$attachment "Beam_point4" "ValveBiped.Base" -0.037 2.363 18.656 rotate 0.0000 0.0000 0.0000
$attachment "Beam_point5" "ValveBiped.Base" -0.050 2.350 18.356 rotate 0.0000 0.0000 0.0000
$attachment "Arm1_attach1" "ValveBiped.Base" 1.336 1.676 12.463 rotate 0.0000 0.0000 0.0000
$attachment "Arm1_attach2" "ValveBiped.Base" 1.950 2.574 18.160 rotate 0.0000 0.0000 0.0000
$attachment "Arm1_attach3" "ValveBiped.Base" 3.023 4.106 24.983 rotate 0.0000 0.0000 0.0000
$attachment "Arm2_attach1" "ValveBiped.Base" 2.169 -2.906 12.193 rotate 0.0000 0.0000 0.0000
$attachment "Arm2_attach2" "ValveBiped.Base" 3.162 -4.143 17.775 rotate 0.0000 0.0000 0.0000
$attachment "Arm2_attach3" "ValveBiped.Base" 4.805 -5.939 24.439 rotate 0.0000 0.0000 0.0000
$attachment "Arm3_attach1" "ValveBiped.Base" -3.092 1.036 12.187 rotate 0.0000 0.0000 0.0000
$attachment "Arm3_attach2" "ValveBiped.Base" -4.644 1.539 17.755 rotate 0.0000 0.0000 0.0000
$attachment "Arm3_attach3" "ValveBiped.Base" -6.951 2.470 24.403 rotate 0.0000 0.0000 0.0000
$attachment "muzzle" "ValveBiped.Base" -0.020 2.200 23.250 rotate -90.00 0.00 0.00

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
