# ThorImageCAM — SDK map (reverse engineering)

> Goal: drive the ThorLabs camera from Python/macOS without the ThorImageCAM GUI.
> Method: .NET decompilation (ilspycmd 8.2, net6.0) of the managed assemblies +
> extraction of the C ABI of the native DLLs.

## 1. Layered architecture

```
┌─────────────────────────────────────────────────────────────┐
│ CameraControl.dll          WPF GUI (Live/Snap/Capture buttons)│  managed
│   └─ DataContext = MVMManager["CameraControlViewModel"]       │
├─────────────────────────────────────────────────────────────┤
│ CameraControlMVM.dll       CameraControlViewModel (commands)  │  managed
│   └─ CameraControlModel (static) ─ facade                     │
├─────────────────────────────────────────────────────────────┤
│ ThorImageCAMShared.dll     ★ core ★                           │  managed
│   ├─ ThorlabsCamera (singleton)  → wraps CameraLib.dll        │
│   ├─ CaptureService (singleton)  → acquisition orchestration  │
│   └─ P/Invoke : 93× SMNC_* + 52× p2d_*                        │
├─────────────────────────────────────────────────────────────┤
│ CameraLib.dll   (NATIVE)   ★ the real camera SDK ★  SMNC_ prefix
│ p2d_lib.dll     (NATIVE)   image processing/buffers (p2d_*)   │
└─────────────────────────────────────────────────────────────┘
```

**Key consequence**: to drive from Python, we target directly
`CameraLib.dll` (C ABI, cdecl) via `ctypes`. The .NET layer is only a wrapper;
it serves as *living documentation* of the signatures and call sequences.

## 2. CameraControl.dll (what was requested)

Pure WPF GUI component. Two UserControls (`CameraControlUC`, `CameraControlSimple`)
+ icon resources (BAML). No hardware logic: everything is delegated to the
ViewModel retrieved by name:

```csharp
base.DataContext = MVMManager.Instance["CameraControlViewModel", null];
```

Parameters exposed in the GUI: Exposure, FrameRate, Gain, DiscreteGain, BinX, BinY, Manual.

## 3. CameraControlViewModel (CameraControlMVM.dll)

Commands (Prism `DelegateCommand`) and what they call:

| UI command           | Handler            | Actual call                                  |
|----------------------|--------------------|----------------------------------------------|
| `LiveCommand`        | OnLiveExecute      | `CaptureService.LiveImages(false)` / `StopLive()` |
| `SnapshotCommand`    | OnSnapshotExecute  | `CaptureService.Snapshot()` / `StopSnapshot()`    |
| `CaptureCommand`     | OnCaptureExecute   | `CaptureService.StartCapture(cb)` / `StopCapture()` |
| `OriginalROICommand` | OnOriginalROIExecute | `ThorlabsCamera.CameraOrignalROI` → UpdateROI    |
| `RegionFromROICommand`| OnRegionFromROIExecute | `UpdateROI(roi)`                           |

Properties (bound): `ExposureTime`, `Gain`, `BinX/BinY`, `SelectedDataRate`,
`FrameRateControlValue`, `IsAutoExposure`, `PolarImageType`, `ObjectiveValue`,
`IsLiveCommandExecuting`, `IsCaptureCommandExecuting`, `PhysicalResolution`…

`CameraControlModel` (static) relays everything to `ThorlabsCamera.Instance` and
`CaptureService.Instance`.

## 4. ThorlabsCamera (ThorImageCAMShared.dll) — managed wrapper of CameraLib.dll

Singleton. Main public API:
- Discovery / connection: `ListCameras()`, `OpenCamera(CameraInfo)`, `CloseCamera()`, `ResetCurrentCamera()`
- Exposure: `SetExposureTime(double)`, `GetExposureTime()`, `ExposureTimeRange`
- Auto-exposure: `SwitchAutoExposureStatus()`, `Set/GetAutoExposureTargetIntensity()`,
  `...MaxSaturatedPixels()`, `...IsUseGain()`, `...UpperLimit()`, `AutoExposureMode`
- Gain: `Gain`, `GainRange`, `IsGainContinuous`, `DiscreteGainValues`
- Binning / ROI: `BinX/BinY` (+ Range), `CameraROI`, `CameraOrignalROI`, `CameraROIRange`
- Sensor: `SensorPixelWidth/Height`, `BitDepth`, `ImageWidth/Height`, `UsedValidBits`
- Trigger: `TriggerMode`, `FramesPerTrigger`, `HardwareTriggerPolarity`, `IsHardwareTriggerSupported`
- Throughput: `SupportedDataRates`, `CurrentDataRate`
- Color/polar: `IsColorCamera`, `IsPolarCamera`, `PolarImageType`, `CameraPolarPhase`, `GainR/G/B`
- Options: LED, HotPixelCorrection, EEP (pulsed exposure), Cooling

## 5. ★ CameraLib.dll — native C ABI (the reusable SDK) ★

93 exported functions, prefix **`SMNC_`**, `cdecl` (except color = `stdcall`).
Convention: each function returns an `int` (status code, 0 = OK — cf. `ThorCamStatus`),
the values come out through `out` pointers. Complete list: `CameraLib_SMNC_pinvoke.txt`.

Minimal life cycle:
```
SMNC_List(buf, size)                 → enumerates the cameras (separated IDs)
SMNC_Open(sn)                        → opens by serial number
SMNC_SetCallback(img, disc, ae, perf)→ registers the callbacks (frames via img)
SMNC_SetExposureTime(us)             → exposure in microseconds (long)
SMNC_SetROI(x,y,w,h) / SMNC_SetBinX/Y
SMNC_StartPreview(LiveInfo)          → live; frames delivered to ImageCallback
   ... ImageCallback(p2dImageHdl, frameCount, frameClock, needGamma, colorSpace,
                     frameNumber, tsHigh, tsLow) ...
SMNC_StopPreview()
SMNC_Close() / SMNC_Release()
```
Snapshot: `SMNC_StartSnapshot(SnapshotInfo)` / `SMNC_StopSnapshot()`.
Capture (series to disk): `SMNC_StartCapture(CaptureInfo, PreparedCallback)` / `SMNC_StopCapture(bool)`.

Functional groups (excerpts):
- Exposure: `SMNC_Set/GetExposureTime`, `SMNC_GetExposureTimeRange`, auto-exp (`SMNC_*AutoExposure*`)
- Gain: `SMNC_Set/GetGain`, `SMNC_GetGainRange`, `SMNC_GetGainFromIndex`, `SMNC_GetIsGainContinuous`
- ROI/Bin: `SMNC_Set/GetROI`, `SMNC_GetROIRange`, `SMNC_Set/GetBinX`, `SMNC_Set/GetBinY`
- Trigger: `SMNC_GetIsOperationModeSupported`, EEP (`SMNC_*EEP*`), `SMNC_GetSensorReadoutTime`
- Throughput: `SMNC_Get/SetDataRate`, `SMNC_GetIsDataRateSupported`, framerate (`SMNC_*FrameRateControl*`)
- Sensor: `SMNC_GetBitDepth`, `SMNC_GetSensorPixelWidth/Height`, `SMNC_GetImageWidthAndHeight`
- Color/polar: `SMNC_GetColorMode`, `SMNC_Get/SetColorSpaceType`, `SMNC_ColorTransform48to24`,
  `SMNC_GetDefaultColorMatrix`, `SMNC_*PolarizationImageType`, `SMNC_GetPolarPhaseAngle`
- Misc: LED (`SMNC_*LED*`), HotPixel (`SMNC_*HotPixelCorrection*`), cooling (`SMNC_GetIsCooling*`)
- Files/images: `SMNC_GetImageCount/Data/CloseImage` (TIFF), `SMNC_GetJpegData`, `SMNC_CreateP2DImage`

## 6. Retrieving the pixels: p2d_lib.dll

The `ImageCallback` does not deliver a raw buffer but a **handle `p2dImageHdl`** (int)
to an image managed by `p2d_lib.dll`. To read the pixels:
```
p2d_get_info(hdl, &P2dInfo)   → dimensions, format, channels, valid bits
p2d_get_buf(hdl)              → IntPtr to the pixel data  (EntryPoint SMNC on the .NET side: GetIntPtr)
```
52 `p2d_*` functions (creation, color conversion, histogram, profiles, min/max, resize…).
List: `p2d_lib_pinvoke.txt`. Associated structs: `P2dInfo`, `P2dRect`, `P2dPoint`,
enums `P2dDataFormat`, `P2dChannels`.

## 7. Supporting types (for the ctypes mapping)

**Callbacks** (all `UnmanagedFunctionPointer(Cdecl)`):
```c
void PreparedCallback(void);
void ImageCallback(int p2dImageHdl, uint frameCount, long frameClock,
                   bool needGammaCorrection, int colorSpace, long frameNumber,
                   long timestampHighBits, long timestampLowBits);
void DisconnectCallback(void);
void AutoExposureCallback(bool is_stable, double exposure, double gain);
void ImagePerformanceCallback(uint frameCount, long frameClock, uint dropedFrameCount);
```

**Enums**:
- `TriggerMode` : None=0, HardwareTriggerFirst=1, HardwareTriggerEach=2
- `HardwareTriggerPolarity` : ActiveHigh=0, ActiveLow=1
- `DataRate` : DATA_RATE_FPS_30=2, DATA_RATE_FPS_50=3
- `AutoExposureMode` : TARGET_DYNAMIC_RANGE=0, MAX_SATURATED_PIXELS=1
- `ColorFormat` : BGR_PLANAR=0, BGR_PIXEL=1, RGB_PIXEL=2, RGB_PLANAR=3
- `PolarImageTypes` : UNPROCESSED=0, TOTAL_OPTICAL_POWER=1, AZIMUTH=2, DEGREE_OF_LINEAR_POLARIZATION=3, QUAD_VIEW=4
- `CameraTriggerMode` : SoftwareTrigger=0, HardwareTrigger=1
- `CameraEEPStatus` : Disabled, EnabledActive, EnabledInactive, EnabledBulb
- `ThorCamStatus` : return codes (0 = success)

**Acquisition structs** (LayoutKind.Sequential) — see §5 of the decompiled .cs for the exact order:
- `LiveInfo(trigMode, hwTrigPolarity, isBulbMode, framesPerTrigger, isAutoExposure, framesToAverage)`
- `SnapshotInfo(trigMode, hwTrigPolarity, fullFileName[Unicode], saveType, channelGains[3], min[3], max[3], gamma[3], isCapturingWithoutCorrection, isBulbMode)`
- `CaptureInfo(trigMode, hwTrigPolarity, framesPerTrigger, fullFileNameWithoutExtension[Unicode], saveType, channelGains[3], min[3], max[3], gamma[3], frameCount, interval_ms, captureMode, duration_ms, isUpdateDisplay, isCapturingWithoutCorrection, isBulbMode, isDurationTimedSeries, framesToAverage)`

## 8. SDK identity note

The `SMNC_` prefix and the mechanics (p2d, image + perf + autoexposure callbacks)
correspond to the ThorLabs scientific camera SDK ("Scientific Camera" family /
Kiralux/Zelux — cf. the `thorlabs_tsi_*.dll` DLLs also present in Bin).
`CameraLib.dll` is likely an in-house layer on top of the TSI SDK.
→ Alternative lead: the **TSI SDK** (`thorlabs_tsi_camera_sdk.dll`) is publicly
documented by ThorLabs and already has an official Python binding.

## 9. Produced files

- `src/CameraControl/`        — decompiled C# project (GUI)
- `src/CameraControlMVM/`      — decompiled ViewModel
- `src/ThorImageCAMShared/`    — decompiled core (17k lines, ThorlabsCamera + CaptureService)
- `src/CameraLib/`             — (native, not decompilable to C#)
- `docs/CameraLib_SMNC_pinvoke.txt` — 93 SMNC_ signatures
- `docs/p2d_lib_pinvoke.txt`        — 52 p2d_ signatures
- `tools/`                     — VM infra (image display, session launcher, ilspy)
