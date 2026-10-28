// Shattered Life - Desert Eagle viewmodel
// Arms: Adrian Shephard (HECU), posed rigidly onto the HL2 .357 viewmodel skeleton.
// Animations come from HL2's v_357 via $includemodel.
$modelname "weapons/v_deagle.mdl"
$cdmaterials "models/weapons/v_deagle/"
$cdmaterials "models/weapons/v_wrench/"
$surfaceprop "metal"
$model "deagle" "v_deagle_ref.smd"
$attachment "muzzle" "Python" -0.0260 0.6726 7.7857 rotate -90.000 90.000 0.000
$sequence "ref" "v_deagle_ref.smd" fps 1
$includemodel "weapons/v_357.mdl"
