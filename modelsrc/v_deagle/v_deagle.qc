// Shattered Life - Desert Eagle viewmodel
// Built on HL2's v_pistol skeleton by tools/build_deagle_on_pistol.py:
// Adrian Shephard's arms on the pistol's arm bones, the deagle's slide on
// ValveBiped.square, hammer on ValveBiped.hammer, magazine on ValveBiped.clip,
// frame on ValveBiped.base. Animations come from HL2's v_pistol via $includemodel.
// (The .357-based version is modelsrc/v_deagle/v_deagle_ref.357.smd.)
$modelname "weapons/v_deagle.mdl"
$cdmaterials "models/weapons/v_deagle/"
$cdmaterials "models/weapons/v_wrench/"
$surfaceprop "metal"
$model "deagle" "v_deagle_ref.smd"
// barrel tip of the deagle, on the pistol's muzzle bone (its X points down the bore)
$attachment "muzzle" "ValveBiped.muzzle" 1.5419 0.7216 -0.1578
$attachment "eject" "ValveBiped.eject" 0 0 0
$sequence "ref" "v_deagle_ref.smd" fps 1
$includemodel "weapons/v_pistol.mdl"
