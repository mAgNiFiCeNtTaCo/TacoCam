import Foundation
import AVFoundation
import CoreMedia
import UIKit

/// What one camera can do (STATE `cameras.back` / `cameras.front`).
struct CameraCaps {
    var available = false
    var name = ""
    var minZoom: Double = 1
    var maxZoom: Double = 1
    var lensZooms: [Double] = []
    var hasTorch = false
    var resolutions: [String] = []
    var fps: [String: [Int]] = [:]
    var isoRange: [Double] = []
    var shutterRange: [Double] = []
    var focusManual = false
    var focusLock = false        // can at least hold the focus where it is (combined back camera)
    var exposureManual = false   // ISO + shutter can be set
    var wbManual = false         // temperature + tint can be set
    var antiFlicker = false      // fixed-shutter auto exposure possible
    var hdr = false
    var stabilization: [String] = ["off"]

    func toDict() -> [String: Any] {
        return [
            "available": available,
            "name": name,
            "min_zoom": PhoneSettings.json(minZoom),
            "max_zoom": PhoneSettings.json(maxZoom),
            "lens_zooms": lensZooms,
            "has_torch": hasTorch,
            "resolutions": resolutions,
            "fps": fps,
            "iso_range": isoRange.map { PhoneSettings.json($0) },
            "shutter_range_s": shutterRange,
            "focus_manual": focusManual,
            "focus_lock": focusLock,
            "exposure_manual": exposureManual,
            "wb_manual": wbManual,
            "anti_flicker": antiFlicker,
            "hdr": hdr,
            "stabilization": stabilization,
        ]
    }
}

/// Result of applying settings to the camera: the values actually in effect.
struct CameraApplied {
    var settings: PhoneSettings
    var streamWidth: Int
    var streamHeight: Int
    var back: CameraCaps
    var front: CameraCaps
    var device: AVCaptureDevice?
    var error: String?

    var current: CameraCaps { return settings.camera == "front" ? front : back }
}

/// AVFoundation side: picks devices and formats per CONTRACT section 4, applies every setting with
/// clamping, delivers landscape, unmirrored frames on its video queue.
final class CameraController: NSObject, AVCaptureVideoDataOutputSampleBufferDelegate {
    let session = AVCaptureSession()
    let sessionQueue = DispatchQueue(label: "tacocam.camera.session")
    private let videoQueue = DispatchQueue(label: "tacocam.camera.video", qos: .userInteractive)
    private let videoOutput = AVCaptureVideoDataOutput()

    private var input: AVCaptureDeviceInput?
    private(set) var device: AVCaptureDevice?
    private var configuredKey = ""
    private var outputAdded = false
    private var backCapsCache: CameraCaps?
    private var frontCapsCache: CameraCaps?
    private var backDev: AVCaptureDevice?
    private var frontDev: AVCaptureDevice?
    private var devicesLooked = false
    /// Anti-flicker: fixed flicker-safe shutter, ISO steered by the meter (session queue only).
    private var flickerDuration: CMTime?
    private var flickerTimer: DispatchSourceTimer?

    /// Called on the video queue for every frame.
    var onSampleBuffer: ((CMSampleBuffer) -> Void)?
    /// Called on the session queue (runtime errors, interruptions).
    var onEvent: ((String) -> Void)?

    // Raw names: the Swift spellings of these constants differ between SDK versions.
    override init() {
        super.init()
        NotificationCenter.default.addObserver(self, selector: #selector(runtimeError(_:)),
                                               name: Notification.Name("AVCaptureSessionRuntimeErrorNotification"),
                                               object: session)
        NotificationCenter.default.addObserver(self, selector: #selector(interrupted(_:)),
                                               name: Notification.Name("AVCaptureSessionWasInterruptedNotification"),
                                               object: session)
    }

    @objc private func runtimeError(_ n: Notification) {
        let err = n.userInfo?["AVCaptureSessionErrorKey"] as? NSError
        onEvent?("Camera error: \(err?.localizedDescription ?? "unknown")")
    }

    @objc private func interrupted(_ n: Notification) {
        var why = "unknown"
        if let raw = n.userInfo?["AVCaptureSessionInterruptionReasonKey"] as? Int,
           let reason = AVCaptureSession.InterruptionReason(rawValue: raw) {
            switch reason {
            case .videoDeviceNotAvailableInBackground: why = "app in background"
            case .audioDeviceInUseByAnotherClient, .videoDeviceInUseByAnotherClient: why = "camera used by another app"
            case .videoDeviceNotAvailableWithMultipleForegroundApps: why = "split screen"
            case .videoDeviceNotAvailableDueToSystemPressure: why = "phone too hot"
            @unknown default: why = "reason \(raw)"
            }
        }
        onEvent?("Camera interrupted: \(why)")
    }

    // MARK: devices

    static func backDevice() -> AVCaptureDevice? {
        let types: [AVCaptureDevice.DeviceType] = [.builtInTripleCamera, .builtInDualWideCamera,
                                                   .builtInDualCamera, .builtInWideAngleCamera]
        for t in types {
            if let d = AVCaptureDevice.default(t, for: .video, position: .back) { return d }
        }
        return nil
    }

    static func frontDevice() -> AVCaptureDevice? {
        return AVCaptureDevice.default(.builtInTrueDepthCamera, for: .video, position: .front)
            ?? AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .front)
    }

    /// Displayed zoom = videoZoomFactor * m (CONTRACT section 4).
    static func zoomMultiplier(_ d: AVCaptureDevice) -> Double {
        if #available(iOS 18.0, *) {
            let m = Double(d.displayVideoZoomFactorMultiplier)
            if m > 0 { return m }
        }
        let hasUltraWide = d.constituentDevices.contains { $0.deviceType == .builtInUltraWideCamera }
        if hasUltraWide, let first = d.virtualDeviceSwitchOverVideoZoomFactors.first, first.doubleValue > 0 {
            return 1.0 / first.doubleValue
        }
        return 1.0
    }

    static func round1(_ x: Double) -> Double { return (x * 10).rounded() / 10 }
    static func round2(_ x: Double) -> Double { return (x * 100).rounded() / 100 }

    static func lensZooms(_ d: AVCaptureDevice) -> [Double] {
        let m = zoomMultiplier(d)
        var out = [round1(1.0 * m)]
        for f in d.virtualDeviceSwitchOverVideoZoomFactors {
            let z = round1(f.doubleValue * m)
            if !out.contains(z) { out.append(z) }
        }
        return out
    }

    /// Displayed zoom range for the device's active format.
    static func zoomRange(_ d: AVCaptureDevice, front: Bool) -> (min: Double, max: Double) {
        let m = zoomMultiplier(d)
        var lo = Double(d.minAvailableVideoZoomFactor) * m
        if front { lo = max(lo, 1.0) }
        let lensMax = lensZooms(d).max() ?? 1
        var hi = min(Double(d.maxAvailableVideoZoomFactor) * m, max(lensMax * 5, 5))
        if hi < lo { hi = lo }
        return (round2(lo), round2(hi))
    }

    // MARK: formats

    private static let pixelRank: [FourCharCode: Int] = [
        kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange: 0,
        kCVPixelFormatType_420YpCbCr8BiPlanarFullRange: 1,
        kCVPixelFormatType_420YpCbCr10BiPlanarVideoRange: 2,
    ]

    static func formats(_ d: AVCaptureDevice, resolution: String) -> [AVCaptureDevice.Format] {
        let size = PhoneSettings.size(of: resolution)
        return d.formats.filter { f in
            let dims = CMVideoFormatDescriptionGetDimensions(f.formatDescription)
            let sub = CMFormatDescriptionGetMediaSubType(f.formatDescription)
            return Int(dims.width) == size.width && Int(dims.height) == size.height && pixelRank[sub] != nil
        }
    }

    static func supports(_ f: AVCaptureDevice.Format, fps: Int) -> Bool {
        let x = Double(fps)
        return f.videoSupportedFrameRateRanges.contains { $0.minFrameRate <= x + 0.01 && $0.maxFrameRate >= x - 0.01 }
    }

    static func maxFps(_ f: AVCaptureDevice.Format) -> Double {
        return f.videoSupportedFrameRateRanges.map { $0.maxFrameRate }.max() ?? 0
    }

    static func fpsList(_ d: AVCaptureDevice, resolution: String) -> [Int] {
        let fs = formats(d, resolution: resolution)
        return PhoneSettings.fpsChoices.filter { fps in fs.contains { supports($0, fps: fps) } }
    }

    /// Shutter time that matches the mains light flicker (lights pulse at 2x the mains frequency, so any
    /// multiple of 1/120 s or 1/100 s is band-free) and fits in one frame. nil if the format can't do it.
    static func flickerSafeDuration(_ mode: String, fps: Int, format f: AVCaptureDevice.Format) -> CMTime? {
        let frame = 1.0 / Double(max(fps, 1))
        let secs: Double
        switch mode {
        case "60hz": secs = 1.0 / 60 <= frame + 1e-6 ? 1.0 / 60 : 1.0 / 120
        case "50hz": secs = 1.0 / 50 <= frame + 1e-6 ? 1.0 / 50 : 1.0 / 100
        default: return nil
        }
        let lo = CMTimeGetSeconds(f.minExposureDuration)
        let hi = CMTimeGetSeconds(f.maxExposureDuration)
        if secs < lo - 1e-9 || secs > hi + 1e-9 { return nil }
        return CMTimeMakeWithSeconds(secs, preferredTimescale: 1_000_000)
    }

    /// What the camera is really using right now (STATE `live`), for "lock at the current values".
    static func liveValues(_ d: AVCaptureDevice) -> [String: Any] {
        var out: [String: Any] = [
            "lens_position": (Double(d.lensPosition) * 1000).rounded() / 1000,
            "iso": round1(Double(d.iso)),
            "shutter_s": (CMTimeGetSeconds(d.exposureDuration) * 1_000_000).rounded() / 1_000_000,
        ]
        let tt = d.temperatureAndTintValues(for: d.deviceWhiteBalanceGains)
        if tt.temperature.isFinite && tt.tint.isFinite {
            out["temperature"] = Int(min(max(Double(tt.temperature), 2500), 8000).rounded())
            out["tint"] = Int(min(max(Double(tt.tint), -150), 150).rounded())
        }
        return out
    }

    static func stabMode(_ name: String) -> AVCaptureVideoStabilizationMode {
        switch name {
        case "standard": return .standard
        case "cinematic": return .cinematic
        default: return .off
        }
    }

    /// Best format for resolution + fps: not binned, 420v first, HDR / stabilization if asked, max fps
    /// closest to the wanted fps. Returns the fps actually usable.
    static func chooseFormat(_ d: AVCaptureDevice, resolution: String, fps: Int, hdr: Bool,
                             stabilization: String) -> (format: AVCaptureDevice.Format, fps: Int)? {
        let candidates = formats(d, resolution: resolution)
        if candidates.isEmpty { return nil }
        let supported = PhoneSettings.fpsChoices.filter { f in candidates.contains { supports($0, fps: f) } }
        var eff = fps
        if !supported.contains(fps) {
            eff = supported.filter { $0 < fps }.max() ?? supported.min() ?? fps
        }
        var pool = candidates.filter { supports($0, fps: eff) }
        if pool.isEmpty { pool = candidates }
        let stab = stabMode(stabilization)
        func score(_ f: AVCaptureDevice.Format) -> [Double] {
            let sub = CMFormatDescriptionGetMediaSubType(f.formatDescription)
            return [
                f.isVideoBinned ? 1 : 0,
                (hdr && !f.isVideoHDRSupported) ? 1 : 0,
                (stab != .off && !f.isVideoStabilizationModeSupported(stab)) ? 1 : 0,
                Double(pixelRank[sub] ?? 9),
                abs(maxFps(f) - Double(eff)),
            ]
        }
        func less(_ a: [Double], _ b: [Double]) -> Bool {
            for i in 0..<min(a.count, b.count) where a[i] != b[i] {
                return a[i] < b[i]
            }
            return false
        }
        let best = pool.min { less(score($0), score($1)) }!
        return (best, eff)
    }

    // MARK: capabilities (STATE cameras)

    static func capabilities(_ dev: AVCaptureDevice?, front: Bool, fps: Int) -> CameraCaps {
        var c = CameraCaps()
        guard let d = dev else { return c }
        c.available = true
        c.name = d.localizedName
        for r in PhoneSettings.resolutions {
            let list = fpsList(d, resolution: r)
            if !list.isEmpty {
                c.resolutions.append(r)
                c.fps[r] = list
            }
        }
        let f = d.activeFormat
        let zr = zoomRange(d, front: front)
        c.minZoom = zr.min
        c.maxZoom = zr.max
        c.lensZooms = front ? [1.0] : lensZooms(d)
        c.hasTorch = d.hasTorch
        if f.isVideoStabilizationModeSupported(.standard) { c.stabilization.append("standard") }
        if f.isVideoStabilizationModeSupported(.cinematic) { c.stabilization.append("cinematic") }
        let minShutter = CMTimeGetSeconds(f.minExposureDuration)
        var maxShutter = CMTimeGetSeconds(f.maxExposureDuration)
        if fps > 0 { maxShutter = min(maxShutter, 1.0 / Double(fps)) }
        c.isoRange = [round1(Double(f.minISO)), round1(Double(f.maxISO))]
        c.shutterRange = [(minShutter * 1_000_000).rounded() / 1_000_000, (maxShutter * 1_000_000).rounded() / 1_000_000]
        c.focusManual = d.isLockingFocusWithCustomLensPositionSupported
        c.focusLock = c.focusManual || d.isFocusModeSupported(.autoFocus) || d.isFocusModeSupported(.locked)
        c.exposureManual = d.isExposureModeSupported(.custom)
        c.wbManual = d.isLockingWhiteBalanceWithCustomDeviceGainsSupported
        c.antiFlicker = d.isExposureModeSupported(.custom)
        c.hdr = f.isVideoHDRSupported
        return c
    }

    // MARK: running

    var isRunning: Bool { return session.isRunning }

    func start(_ done: (() -> Void)? = nil) {
        sessionQueue.async {
            if !self.session.isRunning && self.input != nil {
                self.session.startRunning()
            }
            done?()
        }
    }

    func stop() {
        sessionQueue.async {
            if self.session.isRunning {
                self.session.stopRunning()
            }
        }
    }

    /// Focus + exposure point of interest in sensor coordinates (landscape, unrotated, unmirrored),
    /// then continuous auto around it.
    func focus(at p: CGPoint) {
        sessionQueue.async {
            guard let d = self.device else { return }
            let pt = CGPoint(x: min(max(p.x, 0), 1), y: min(max(p.y, 0), 1))
            do {
                try d.lockForConfiguration()
                if d.isFocusPointOfInterestSupported {
                    d.focusPointOfInterest = pt
                    if d.isFocusModeSupported(.continuousAutoFocus) { d.focusMode = .continuousAutoFocus }
                    else if d.isFocusModeSupported(.autoFocus) { d.focusMode = .autoFocus }
                }
                if d.isExposurePointOfInterestSupported && d.exposureMode != .custom {
                    d.exposurePointOfInterest = pt
                    if d.isExposureModeSupported(.continuousAutoExposure) { d.exposureMode = .continuousAutoExposure }
                }
                d.unlockForConfiguration()
            } catch {
                self.onEvent?("Focus point failed: \(error.localizedDescription)")
            }
        }
    }

    /// Applies the wanted settings (on the session queue) and reports what is in effect (on main).
    func apply(_ want: PhoneSettings, fpsCap: Int, completion: @escaping (CameraApplied) -> Void) {
        sessionQueue.async {
            let applied = self.applyNow(want, fpsCap: fpsCap)
            DispatchQueue.main.async { completion(applied) }
        }
    }

    private func applyNow(_ want: PhoneSettings, fpsCap: Int) -> CameraApplied {
        var eff = want
        var errors: [String] = []

        // 1. Device.
        if !devicesLooked {
            backDev = CameraController.backDevice()
            frontDev = CameraController.frontDevice()
            devicesLooked = backDev != nil || frontDev != nil
        }
        let back = backDev
        let front = frontDev
        var useFront = want.camera == "front"
        if useFront && front == nil {
            useFront = false
            errors.append("No front camera")
        }
        guard let d = useFront ? front : back else {
            eff.camera = useFront ? "front" : "back"
            return CameraApplied(settings: eff, streamWidth: 0, streamHeight: 0,
                                 back: CameraCaps(), front: CameraCaps(), device: nil,
                                 error: "No camera found (or camera access not allowed)")
        }
        eff.camera = useFront ? "front" : "back"

        // 2. Format + fps.
        let wantFps = min(want.fps, fpsCap)
        var res = want.resolution
        var choice = CameraController.chooseFormat(d, resolution: res, fps: wantFps, hdr: want.hdr,
                                                   stabilization: want.stabilization)
        if choice == nil {
            for r in ["1080p", "720p", "4k"] where r != want.resolution {
                if let c = CameraController.chooseFormat(d, resolution: r, fps: wantFps, hdr: want.hdr,
                                                         stabilization: want.stabilization) {
                    choice = c
                    res = r
                    errors.append("\(want.resolution) not available on this camera, using \(r)")
                    break
                }
            }
        }
        eff.resolution = res
        if let c = choice { eff.fps = c.fps }

        let key = "\(d.uniqueID)|\(res)|\(eff.fps)|\(want.hdr)|\(want.stabilization)"
        if key != configuredKey || input?.device.uniqueID != d.uniqueID {
            if let err = configure(d, format: choice?.format, fps: eff.fps, hdr: want.hdr,
                                   stabilization: want.stabilization) {
                errors.append(err)
            } else {
                configuredKey = key
            }
        }

        // 3. Live parameters.
        var flicker: CMTime? = nil
        do {
            try d.lockForConfiguration()
            applyFrameRate(d, fps: eff.fps)

            // Zoom (displayed units).
            let m = CameraController.zoomMultiplier(d)
            let zr = CameraController.zoomRange(d, front: useFront)
            let disp = PhoneSettings.clamp(want.zoom, zr.min, zr.max)
            var vzf = CGFloat(disp / m)
            vzf = min(max(vzf, d.minAvailableVideoZoomFactor), d.maxAvailableVideoZoomFactor)
            vzf = min(max(vzf, 1.0), d.activeFormat.videoMaxZoomFactor)
            if abs(d.videoZoomFactor - vzf) > 0.001 {
                if d.isRampingVideoZoom { d.cancelVideoZoomRamp() }
                d.videoZoomFactor = vzf
            }
            eff.zoom = CameraController.round2(Double(vzf) * m)

            // Focus.
            if want.focusMode == "manual" && d.isLockingFocusWithCustomLensPositionSupported
                && d.isFocusModeSupported(.locked) {
                let pos = Float(PhoneSettings.clamp(want.focusPosition, 0, 1))
                if d.focusMode != .locked || abs(d.lensPosition - pos) > 0.001 {
                    d.setFocusModeLocked(lensPosition: pos, completionHandler: nil)
                }
                eff.focusMode = "manual"
                eff.focusPosition = Double(pos)
            } else if want.focusMode == "manual" && (d.isFocusModeSupported(.autoFocus) || d.isFocusModeSupported(.locked)) {
                // The combined back camera (0.5x-1x) can't take a lens position: focus once on the middle of
                // the picture, then hold it there (autoFocus locks by itself when done).
                if d.focusMode == .continuousAutoFocus {
                    if d.isFocusPointOfInterestSupported { d.focusPointOfInterest = CGPoint(x: 0.5, y: 0.5) }
                    d.focusMode = d.isFocusModeSupported(.autoFocus) ? .autoFocus : .locked
                }
                eff.focusMode = "manual"
                eff.focusPosition = (Double(d.lensPosition) * 1000).rounded() / 1000
            } else {
                if want.focusMode == "manual" { errors.append("Manual focus not supported on this camera") }
                if d.isFocusModeSupported(.continuousAutoFocus) && d.focusMode != .continuousAutoFocus {
                    d.focusMode = .continuousAutoFocus
                }
                eff.focusMode = "auto"
            }

            // Exposure.
            let f = d.activeFormat
            if want.exposureMode == "manual" && d.isExposureModeSupported(.custom) {
                flicker = nil
                let iso = Float(want.exposureISO ?? Double(d.iso))
                let isoC = min(max(iso, f.minISO), f.maxISO)
                var maxDur = f.maxExposureDuration
                if eff.fps > 0 {
                    maxDur = CMTimeMinimum(maxDur, CMTimeMake(value: 1, timescale: Int32(eff.fps)))
                }
                let wantDur = want.exposureShutter.map { CMTimeMakeWithSeconds($0, preferredTimescale: 1_000_000) }
                    ?? d.exposureDuration
                var dur = CMTimeMaximum(CMTimeMinimum(wantDur, maxDur), f.minExposureDuration)
                if !dur.isValid { dur = f.minExposureDuration }
                d.setExposureModeCustom(duration: dur, iso: isoC, completionHandler: nil)
                eff.exposureMode = "manual"
                eff.exposureISO = CameraController.round1(Double(isoC))
                eff.exposureShutter = (CMTimeGetSeconds(dur) * 1_000_000).rounded() / 1_000_000
            } else if want.exposureMode == "manual" && d.isExposureModeSupported(.locked) {
                // Combined back camera: no ISO/shutter values, but the current brightness can be held.
                flicker = nil
                if d.exposureMode != .locked { d.exposureMode = .locked }
                eff.exposureMode = "manual"
                eff.exposureISO = CameraController.round1(Double(d.iso))
                eff.exposureShutter = (CMTimeGetSeconds(d.exposureDuration) * 1_000_000).rounded() / 1_000_000
            } else {
                if want.exposureMode == "manual" { errors.append("Manual exposure not supported on this camera") }
                if want.antiFlicker != "off" && d.isExposureModeSupported(.custom),
                   let dur = CameraController.flickerSafeDuration(want.antiFlicker, fps: eff.fps, format: f) {
                    // Auto brightness with a fixed shutter: flickerTick() steers ISO from the meter.
                    flicker = dur
                    if d.exposureMode != .custom
                        || abs(CMTimeGetSeconds(d.exposureDuration) - CMTimeGetSeconds(dur)) > 0.00002 {
                        let iso = min(max(d.iso, f.minISO), f.maxISO)
                        d.setExposureModeCustom(duration: dur, iso: iso, completionHandler: nil)
                    }
                } else {
                    flicker = nil
                    if want.antiFlicker != "off" {
                        errors.append(d.isExposureModeSupported(.custom)
                            ? "Anti-flicker is not possible at this frame rate"
                            : "Anti-flicker needs a single-lens camera: the back camera's combined 0.5x-1x mode doesn't allow it")
                        eff.antiFlicker = "off"
                    }
                    if d.exposureMode != .continuousAutoExposure && d.isExposureModeSupported(.continuousAutoExposure) {
                        d.exposureMode = .continuousAutoExposure
                    }
                }
                eff.exposureMode = "auto"
            }
            let lo = max(Double(d.minExposureTargetBias), -3)
            let hi = min(Double(d.maxExposureTargetBias), 3)
            let bias = Float(PhoneSettings.clamp(want.exposureBias, lo, hi))
            if abs(d.exposureTargetBias - bias) > 0.001 {
                d.setExposureTargetBias(bias, completionHandler: nil)
            }
            eff.exposureBias = CameraController.round2(Double(bias))

            // White balance.
            if want.wbMode == "manual" && d.isLockingWhiteBalanceWithCustomDeviceGainsSupported
                && d.isWhiteBalanceModeSupported(.locked) {
                let t = Float(PhoneSettings.clamp(want.wbTemperature, 2500, 8000))
                let tint = Float(PhoneSettings.clamp(want.wbTint, -150, 150))
                let tt = AVCaptureDevice.WhiteBalanceTemperatureAndTintValues(temperature: t, tint: tint)
                var g = d.deviceWhiteBalanceGains(for: tt)
                let mx = d.maxWhiteBalanceGain
                g.redGain = min(max(g.redGain, 1), mx)
                g.greenGain = min(max(g.greenGain, 1), mx)
                g.blueGain = min(max(g.blueGain, 1), mx)
                d.setWhiteBalanceModeLocked(with: g, completionHandler: nil)
                eff.wbMode = "manual"
                eff.wbTemperature = Double(t).rounded()
                eff.wbTint = Double(tint).rounded()
            } else if want.wbMode == "manual" && d.isWhiteBalanceModeSupported(.locked) {
                // Combined back camera: no temperature/tint values, but the current colors can be held.
                if d.whiteBalanceMode != .locked { d.whiteBalanceMode = .locked }
                eff.wbMode = "manual"
                let tt = d.temperatureAndTintValues(for: d.deviceWhiteBalanceGains)
                if tt.temperature.isFinite && tt.tint.isFinite {
                    eff.wbTemperature = PhoneSettings.clamp(Double(tt.temperature), 2500, 8000).rounded()
                    eff.wbTint = PhoneSettings.clamp(Double(tt.tint), -150, 150).rounded()
                }
            } else {
                if want.wbMode == "manual" { errors.append("Manual white balance not supported on this camera") }
                if d.isWhiteBalanceModeSupported(.continuousAutoWhiteBalance)
                    && d.whiteBalanceMode != .continuousAutoWhiteBalance {
                    d.whiteBalanceMode = .continuousAutoWhiteBalance
                }
                eff.wbMode = "auto"
            }

            // Torch.
            eff.torch = 0
            if d.hasTorch {
                if want.torch > 0 && d.isTorchAvailable {
                    let level = Float(min(max(want.torch, 0.01), Double(AVCaptureDevice.maxAvailableTorchLevel)))
                    do {
                        try d.setTorchModeOn(level: level)
                        eff.torch = CameraController.round2(Double(level))
                    } catch {
                        errors.append("Torch failed: \(error.localizedDescription)")
                    }
                } else if d.torchMode != .off && d.isTorchModeSupported(.off) {
                    d.torchMode = .off
                }
                if want.torch > 0 && !d.isTorchAvailable { errors.append("Torch not available right now") }
            }

            d.unlockForConfiguration()
        } catch {
            errors.append("Could not change camera settings: \(error.localizedDescription)")
        }
        setFlicker(flicker)

        // Stabilization + HDR in effect.
        if let conn = videoOutput.connection(with: .video), conn.isVideoStabilizationSupported {
            let mode = conn.preferredVideoStabilizationMode
            eff.stabilization = mode == .cinematic ? "cinematic" : (mode == .standard ? "standard" : "off")
        } else {
            eff.stabilization = "off"
        }
        eff.hdr = d.activeFormat.isVideoHDRSupported && d.isVideoHDREnabled

        // Capabilities of both cameras.
        let backCaps: CameraCaps
        let frontCaps: CameraCaps
        if useFront {
            frontCaps = CameraController.capabilities(d, front: true, fps: eff.fps)
            backCaps = backCapsCache ?? CameraController.capabilities(back, front: false, fps: 30)
            frontCapsCache = frontCaps
            backCapsCache = backCaps
        } else {
            backCaps = CameraController.capabilities(d, front: false, fps: eff.fps)
            frontCaps = frontCapsCache ?? CameraController.capabilities(front, front: true, fps: 30)
            backCapsCache = backCaps
            frontCapsCache = frontCaps
        }

        let dims = CMVideoFormatDescriptionGetDimensions(d.activeFormat.formatDescription)
        return CameraApplied(settings: eff,
                             streamWidth: Int(dims.width), streamHeight: Int(dims.height),
                             back: backCaps, front: frontCaps, device: d,
                             error: errors.isEmpty ? nil : errors.joined(separator: "; "))
    }

    // MARK: anti-flicker (session queue)

    private func setFlicker(_ dur: CMTime?) {
        flickerDuration = dur
        if dur != nil && flickerTimer == nil {
            let t = DispatchSource.makeTimerSource(queue: sessionQueue)
            t.schedule(deadline: .now() + 0.25, repeating: 0.25)
            t.setEventHandler { [weak self] in self?.flickerTick() }
            t.resume()
            flickerTimer = t
        } else if dur == nil, let t = flickerTimer {
            t.cancel()
            flickerTimer = nil
        }
    }

    /// Keeps the fixed-shutter picture at the auto brightness target: the meter's offset (EV, includes the
    /// brightness bias) is turned into an ISO change, in damped steps so the picture doesn't pump.
    private func flickerTick() {
        guard let dur = flickerDuration, let d = device, d.exposureMode == .custom, !d.isAdjustingExposure else { return }
        let off = d.exposureTargetOffset
        if !off.isFinite || abs(off) < 0.15 { return }
        let step = max(-1, min(1, -off)) * 0.6
        let f = d.activeFormat
        let iso = min(max(d.iso * powf(2, step), f.minISO), f.maxISO)
        if abs(iso - d.iso) < 0.5 { return }
        do {
            try d.lockForConfiguration()
            d.setExposureModeCustom(duration: dur, iso: iso, completionHandler: nil)
            d.unlockForConfiguration()
        } catch {
            // try again next tick
        }
    }

    private func applyFrameRate(_ d: AVCaptureDevice, fps: Int) {
        guard fps > 0, CameraController.supports(d.activeFormat, fps: fps) else { return }
        let dur = CMTimeMake(value: 1, timescale: Int32(fps))
        if d.activeVideoMinFrameDuration != dur { d.activeVideoMinFrameDuration = dur }
        if d.activeVideoMaxFrameDuration != dur { d.activeVideoMaxFrameDuration = dur }
    }

    /// Session reconfiguration: input, output, format, fps, HDR, stabilization, rotation 0, no mirror.
    private func configure(_ d: AVCaptureDevice, format: AVCaptureDevice.Format?, fps: Int, hdr: Bool,
                           stabilization: String) -> String? {
        var problem: String? = nil
        session.beginConfiguration()
        defer { session.commitConfiguration() }
        // Without this the session preset can overwrite the activeFormat chosen below on commit.
        if session.sessionPreset != .inputPriority && session.canSetSessionPreset(.inputPriority) {
            session.sessionPreset = .inputPriority
        }

        if input?.device.uniqueID != d.uniqueID {
            if let old = input {
                session.removeInput(old)
                input = nil
            }
            do {
                let newInput = try AVCaptureDeviceInput(device: d)
                if session.canAddInput(newInput) {
                    session.addInput(newInput)
                    input = newInput
                    device = d
                    backCapsCache = nil
                    frontCapsCache = nil
                } else {
                    return "Camera could not be added to the capture session"
                }
            } catch {
                return "Camera could not start: \(error.localizedDescription)"
            }
        }

        if !outputAdded {
            videoOutput.alwaysDiscardsLateVideoFrames = true
            videoOutput.videoSettings = [
                kCVPixelBufferPixelFormatTypeKey as String: NSNumber(value: kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange)
            ]
            videoOutput.setSampleBufferDelegate(self, queue: videoQueue)
            if session.canAddOutput(videoOutput) {
                session.addOutput(videoOutput)
                outputAdded = true
            } else {
                return "Video output could not be added"
            }
        }

        do {
            try d.lockForConfiguration()
            if let f = format, d.activeFormat != f {
                d.activeFormat = f
            }
            applyFrameRate(d, fps: fps)
            if d.activeFormat.isVideoHDRSupported {
                d.automaticallyAdjustsVideoHDREnabled = false
                d.isVideoHDREnabled = hdr
            }
            d.unlockForConfiguration()
        } catch {
            problem = "Could not set the camera format: \(error.localizedDescription)"
        }

        if let conn = videoOutput.connection(with: .video) {
            if #available(iOS 17.0, *) {
                if conn.isVideoRotationAngleSupported(0) { conn.videoRotationAngle = 0 }
            } else {
                if conn.isVideoOrientationSupported { conn.videoOrientation = .landscapeRight }
            }
            if conn.isVideoMirroringSupported {
                conn.automaticallyAdjustsVideoMirroring = false
                conn.isVideoMirrored = false
            }
            if conn.isVideoStabilizationSupported {
                let wantMode = CameraController.stabMode(stabilization)
                let mode: AVCaptureVideoStabilizationMode =
                    d.activeFormat.isVideoStabilizationModeSupported(wantMode) ? wantMode : .off
                conn.preferredVideoStabilizationMode = mode
            }
        }
        return problem
    }

    // MARK: AVCaptureVideoDataOutputSampleBufferDelegate

    func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer,
                       from connection: AVCaptureConnection) {
        onSampleBuffer?(sampleBuffer)
    }
}
