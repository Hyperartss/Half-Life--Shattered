// Shattered Life - Combine Organic Rifle viewmodel
// Arms: Adrian Shephard (HECU), rigid on the HL2 AR2 viewmodel's Base bone. Animations from HL2 v_irifle via $includemodel.
$modelname "weapons/v_ar2_organic.mdl"
$cdmaterials "models/weapons/v_ar2_organic/"
$cdmaterials "models/weapons/v_wrench/"
$surfaceprop "metal"
$model "organic" "v_ar2_organic_ref.smd"
$attachment "muzzle" "Base" 0 0 20 rotate -90 0 0
$sequence "ref" "v_ar2_organic_ref.smd" fps 1
$includemodel "weapons/v_irifle.mdl"
