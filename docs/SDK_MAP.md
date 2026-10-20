# ThorImageCAM — Cartographie du SDK (reverse engineering)

> But : piloter la caméra ThorLabs depuis Python/macOS sans l'IHM ThorImageCAM.
> Méthode : décompilation .NET (ilspycmd 8.2, net6.0) des assemblies managées +
> extraction de l'ABI C des DLLs natives.

## 1. Architecture en couches

```
┌─────────────────────────────────────────────────────────────┐
│ CameraControl.dll          IHM WPF (boutons Live/Snap/Capture)│  managé
│   └─ DataContext = MVMManager["CameraControlViewModel"]       │
├─────────────────────────────────────────────────────────────┤
│ CameraControlMVM.dll       CameraControlViewModel (commandes) │  managé
│   └─ CameraControlModel (static) ─ façade                     │
├─────────────────────────────────────────────────────────────┤
│ ThorImageCAMShared.dll     ★ cœur ★                           │  managé
│   ├─ ThorlabsCamera (singleton)  → wrap de CameraLib.dll      │
│   ├─ CaptureService (singleton)  → orchestration acquisition  │
│   └─ P/Invoke : 93× SMNC_* + 52× p2d_*                        │
├─────────────────────────────────────────────────────────────┤
│ CameraLib.dll   (NATIF)    ★ le vrai SDK caméra ★  préfixe SMNC_
│ p2d_lib.dll     (NATIF)    traitement/buffers d'image (p2d_*) │
└─────────────────────────────────────────────────────────────┘
```

**Conséquence clé** : pour piloter depuis Python, on cible directement
`CameraLib.dll` (ABI C, cdecl) via `ctypes`. La couche .NET n'est qu'un wrapper ;
elle sert de *documentation vivante* des signatures et des séquences d'appel.

## 2. CameraControl.dll (ce qui était demandé)

Pur composant d'IHM WPF. Deux UserControls (`CameraControlUC`, `CameraControlSimple`)
+ ressources d'icônes (BAML). Aucune logique matérielle : tout est délégué au
ViewModel récupéré par nom :

```csharp
base.DataContext = MVMManager.Instance["CameraControlViewModel", null];
```

Paramètres exposés dans l'IHM : Exposure, FrameRate, Gain, DiscreteGain, BinX, BinY, Manual.

## 3. CameraControlViewModel (CameraControlMVM.dll)

Commandes (Prism `DelegateCommand`) et ce qu'elles appellent :

| Commande UI          | Handler            | Appel réel                                   |
|----------------------|--------------------|----------------------------------------------|
| `LiveCommand`        | OnLiveExecute      | `CaptureService.LiveImages(false)` / `StopLive()` |
| `SnapshotCommand`    | OnSnapshotExecute  | `CaptureService.Snapshot()` / `StopSnapshot()`    |
| `CaptureCommand`     | OnCaptureExecute   | `CaptureService.StartCapture(cb)` / `StopCapture()` |
| `OriginalROICommand` | OnOriginalROIExecute | `ThorlabsCamera.CameraOrignalROI` → UpdateROI    |
| `RegionFromROICommand`| OnRegionFromROIExecute | `UpdateROI(roi)`                           |

Propriétés (bindées) : `ExposureTime`, `Gain`, `BinX/BinY`, `SelectedDataRate`,
`FrameRateControlValue`, `IsAutoExposure`, `PolarImageType`, `ObjectiveValue`,
`IsLiveCommandExecuting`, `IsCaptureCommandExecuting`, `PhysicalResolution`…

`CameraControlModel` (static) relaie tout vers `ThorlabsCamera.Instance` et
`CaptureService.Instance`.

## 4. ThorlabsCamera (ThorImageCAMShared.dll) — wrapper managé de CameraLib.dll

Singleton. API publique principale :
- Découverte / connexion : `ListCameras()`, `OpenCamera(CameraInfo)`, `CloseCamera()`, `ResetCurrentCamera()`
- Exposition : `SetExposureTime(double)`, `GetExposureTime()`, `ExposureTimeRange`
- Auto-exposition : `SwitchAutoExposureStatus()`, `Set/GetAutoExposureTargetIntensity()`,
  `...MaxSaturatedPixels()`, `...IsUseGain()`, `...UpperLimit()`, `AutoExposureMode`
- Gain : `Gain`, `GainRange`, `IsGainContinuous`, `DiscreteGainValues`
- Binning / ROI : `BinX/BinY` (+ Range), `CameraROI`, `CameraOrignalROI`, `CameraROIRange`
- Capteur : `SensorPixelWidth/Height`, `BitDepth`, `ImageWidth/Height`, `UsedValidBits`
- Trigger : `TriggerMode`, `FramesPerTrigger`, `HardwareTriggerPolarity`, `IsHardwareTriggerSupported`
- Débit : `SupportedDataRates`, `CurrentDataRate`
- Couleur/polar : `IsColorCamera`, `IsPolarCamera`, `PolarImageType`, `CameraPolarPhase`, `GainR/G/B`
- Options : LED, HotPixelCorrection, EEP (exposition pulsée), refroidissement (Cooling)

## 5. ★ CameraLib.dll — ABI C native (le SDK réutilisable) ★

93 fonctions exportées, préfixe **`SMNC_`**, `cdecl` (sauf couleur = `stdcall`).
Convention : chaque fonction retourne un `int` (code de statut, 0 = OK — cf. `ThorCamStatus`),
les valeurs sortent par pointeurs `out`. Liste complète : `CameraLib_SMNC_pinvoke.txt`.

Cycle de vie minimal :
```
SMNC_List(buf, size)                 → énumère les caméras (IDs séparés)
SMNC_Open(sn)                        → ouvre par numéro de série
SMNC_SetCallback(img, disc, ae, perf)→ enregistre les callbacks (frames via img)
SMNC_SetExposureTime(us)             → exposition en microsecondes (long)
SMNC_SetROI(x,y,w,h) / SMNC_SetBinX/Y
SMNC_StartPreview(LiveInfo)          → live ; frames livrées à ImageCallback
   ... ImageCallback(p2dImageHdl, frameCount, frameClock, needGamma, colorSpace,
                     frameNumber, tsHigh, tsLow) ...
SMNC_StopPreview()
SMNC_Close() / SMNC_Release()
```
Snapshot : `SMNC_StartSnapshot(SnapshotInfo)` / `SMNC_StopSnapshot()`.
Capture (séries vers disque) : `SMNC_StartCapture(CaptureInfo, PreparedCallback)` / `SMNC_StopCapture(bool)`.

Groupes fonctionnels (extraits) :
- Exposition : `SMNC_Set/GetExposureTime`, `SMNC_GetExposureTimeRange`, auto-exp (`SMNC_*AutoExposure*`)
- Gain : `SMNC_Set/GetGain`, `SMNC_GetGainRange`, `SMNC_GetGainFromIndex`, `SMNC_GetIsGainContinuous`
- ROI/Bin : `SMNC_Set/GetROI`, `SMNC_GetROIRange`, `SMNC_Set/GetBinX`, `SMNC_Set/GetBinY`
- Trigger : `SMNC_GetIsOperationModeSupported`, EEP (`SMNC_*EEP*`), `SMNC_GetSensorReadoutTime`
- Débit : `SMNC_Get/SetDataRate`, `SMNC_GetIsDataRateSupported`, framerate (`SMNC_*FrameRateControl*`)
- Capteur : `SMNC_GetBitDepth`, `SMNC_GetSensorPixelWidth/Height`, `SMNC_GetImageWidthAndHeight`
- Couleur/polar : `SMNC_GetColorMode`, `SMNC_Get/SetColorSpaceType`, `SMNC_ColorTransform48to24`,
  `SMNC_GetDefaultColorMatrix`, `SMNC_*PolarizationImageType`, `SMNC_GetPolarPhaseAngle`
- Divers : LED (`SMNC_*LED*`), HotPixel (`SMNC_*HotPixelCorrection*`), cooling (`SMNC_GetIsCooling*`)
- Fichiers/images : `SMNC_GetImageCount/Data/CloseImage` (TIFF), `SMNC_GetJpegData`, `SMNC_CreateP2DImage`

## 6. Récupérer les pixels : p2d_lib.dll

L'`ImageCallback` ne livre pas un buffer brut mais un **handle `p2dImageHdl`** (int)
vers une image gérée par `p2d_lib.dll`. Pour lire les pixels :
```
p2d_get_info(hdl, &P2dInfo)   → dimensions, format, canaux, bits valides
p2d_get_buf(hdl)              → IntPtr vers les données pixel  (EntryPoint SMNC côté .NET: GetIntPtr)
```
52 fonctions `p2d_*` (création, conversion couleur, histogramme, profils, min/max, resize…).
Liste : `p2d_lib_pinvoke.txt`. Structs associées : `P2dInfo`, `P2dRect`, `P2dPoint`,
enums `P2dDataFormat`, `P2dChannels`.

## 7. Types de support (pour le mapping ctypes)

**Callbacks** (tous `UnmanagedFunctionPointer(Cdecl)`) :
```c
void PreparedCallback(void);
void ImageCallback(int p2dImageHdl, uint frameCount, long frameClock,
                   bool needGammaCorrection, int colorSpace, long frameNumber,
                   long timestampHighBits, long timestampLowBits);
void DisconnectCallback(void);
void AutoExposureCallback(bool is_stable, double exposure, double gain);
void ImagePerformanceCallback(uint frameCount, long frameClock, uint dropedFrameCount);
```

**Enums** :
- `TriggerMode` : None=0, HardwareTriggerFirst=1, HardwareTriggerEach=2
- `HardwareTriggerPolarity` : ActiveHigh=0, ActiveLow=1
- `DataRate` : DATA_RATE_FPS_30=2, DATA_RATE_FPS_50=3
- `AutoExposureMode` : TARGET_DYNAMIC_RANGE=0, MAX_SATURATED_PIXELS=1
- `ColorFormat` : BGR_PLANAR=0, BGR_PIXEL=1, RGB_PIXEL=2, RGB_PLANAR=3
- `PolarImageTypes` : UNPROCESSED=0, TOTAL_OPTICAL_POWER=1, AZIMUTH=2, DEGREE_OF_LINEAR_POLARIZATION=3, QUAD_VIEW=4
- `CameraTriggerMode` : SoftwareTrigger=0, HardwareTrigger=1
- `CameraEEPStatus` : Disabled, EnabledActive, EnabledInactive, EnabledBulb
- `ThorCamStatus` : codes de retour (0 = succès)

**Structs d'acquisition** (LayoutKind.Sequential) — voir §5 du .cs décompilé pour l'ordre exact :
- `LiveInfo(trigMode, hwTrigPolarity, isBulbMode, framesPerTrigger, isAutoExposure, framesToAverage)`
- `SnapshotInfo(trigMode, hwTrigPolarity, fullFileName[Unicode], saveType, channelGains[3], min[3], max[3], gamma[3], isCapturingWithoutCorrection, isBulbMode)`
- `CaptureInfo(trigMode, hwTrigPolarity, framesPerTrigger, fullFileNameWithoutExtension[Unicode], saveType, channelGains[3], min[3], max[3], gamma[3], frameCount, interval_ms, captureMode, duration_ms, isUpdateDisplay, isCapturingWithoutCorrection, isBulbMode, isDurationTimedSeries, framesToAverage)`

## 8. Note d'identité du SDK

Le préfixe `SMNC_` et la mécanique (p2d, callbacks image + perf + autoexposure)
correspondent au SDK caméra scientifique ThorLabs (famille "Scientific Camera" /
Kiralux/Zelux — cf. les DLLs `thorlabs_tsi_*.dll` également présentes dans Bin).
`CameraLib.dll` est vraisemblablement une surcouche maison au-dessus du TSI SDK.
→ Piste alternative : le **TSI SDK** (`thorlabs_tsi_camera_sdk.dll`) est documenté
publiquement par ThorLabs et possède déjà un binding Python officiel.

## 9. Fichiers produits

- `src/CameraControl/`        — projet C# décompilé (IHM)
- `src/CameraControlMVM/`      — ViewModel décompilé
- `src/ThorImageCAMShared/`    — cœur décompilé (17k lignes, ThorlabsCamera + CaptureService)
- `src/CameraLib/`             — (native, non décompilable en C#)
- `docs/CameraLib_SMNC_pinvoke.txt` — 93 signatures SMNC_
- `docs/p2d_lib_pinvoke.txt`        — 52 signatures p2d_
- `tools/`                     — infra VM (affichage image, lanceur session, ilspy)
