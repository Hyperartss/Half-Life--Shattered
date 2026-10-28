// Shattered Life - Combine Organic Rifle viewmodel
// Arms: Adrian Shephard (HECU), rigged with his own arm + finger bones (tools/fit_shephard_arms.py). Animations from HL2 v_irifle via $includemodel.
$modelname "weapons/v_ar2_organic.mdl"
$cdmaterials "models/weapons/v_ar2_organic/"
$cdmaterials "models/weapons/v_wrench/"
$surfaceprop "metal"
$model "organic" "v_ar2_organic_ref.smd"
// muzzle rides the Gun bone (child of Base, identical to it in every stock
// sequence) so muzzle flash follows gun animation authored in Blender
$attachment "muzzle" "Gun" 0 0 20 rotate -90 0 0
$sequence "ref" "v_ar2_organic_ref.smd" fps 1
$includemodel "weapons/v_irifle.mdl"
