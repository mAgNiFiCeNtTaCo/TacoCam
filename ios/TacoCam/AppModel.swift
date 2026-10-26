import Foundation
import AVFoundation
import SwiftUI
import UIKit

/// Ties camera, encoder and server together. Lives on the main thread.
final class AppModel: ObservableObject {
    /// What the PC / the phone screen asked for (remembered in UserDefaults).
    @Published private(set) var desired: PhoneSettings
    /// What is in effect after clamping (STATE `settings`).
    @Published private(set) var effective: PhoneSettings
    @Published private(set) var caps = CameraCaps()
    @Published private(set) var connected = false
    @Published private(set) var streaming = false
    @Published private(set) var fpsOut: Double = 0
    @Published private(set) var mbpsOut: Double = 0
    @Published private(set) var cameraError: String?
    @Published private(set) var addresses: [String] = []
    @Published private(set) var battery: Float = -1
    @Published private(set) var charging = false
    @Published private(set) var thermal = "nominal"
    /// Why iOS paused the camera (STATE `interrupted`): "background" | "other_app" | "split_screen" | "too_hot" | "other".
    @Published private(set) var interruption: String?
    @Published var showSettings = false

    let camera = CameraController()
    let encoder = VideoEncoder()
    let server = StreamServer()

    private struct EncodeParams {
        var codec: String
        var fps: Int
        var bitrateMbps: Double
    }

    private let streamFlag = Locked(false)
    private let encodeParams = Locked(EncodeParams(codec: "h264", fps: 30, bitrateMbps: 16))
    private var backCaps = CameraCaps()
    private var frontCaps = CameraCaps()
    private var streamSize = (width: 1920, height: 1080)
    private var appActive = true
    private var started = false
    private var authorized = false
    private var cameraRunning = false
    private var applyInFlight = false
    private var applyAgain = false
    private var videoStartPending = false
    private var stateScheduled = false
    private var fpsCap = 60
    private var lastLoggedError: String?
    private var heartbeat: Timer?
    private var tickCount = 0
    private var rotationCoordinator: AnyObject?
    private var coordinatorDeviceID: String?
    private var currentDevice: AVCaptureDevice?
    private var lastUprightOrientation: UIDeviceOrientation = .portrait
    private var bgTask = UIBackgroundTaskIdentifier.invalid

    init() {
        let s = PhoneSettings.load()
        desired = s
        effective = s
    }

    // MARK: start-up

    func start() {
        guard !started else { return }
        started = true

        UIDevice.current.isBatteryMonitoringEnabled = true
        UIDevice.current.beginGeneratingDeviceOrientationNotifications()
        let nc = NotificationCenter.default
        nc.addObserver(forName: UIDevice.orientationDidChangeNotification, object: nil, queue: .main) { [weak self] _ in
            self?.orientationChanged()
        }
        nc.addObserver(forName: ProcessInfo.thermalStateDidChangeNotification, object: nil, queue: .main) { [weak self] _ in
            self?.thermalChanged()
        }
        nc.addObserver(forName: UIDevice.batteryStateDidChangeNotification, object: nil, queue: .main) { [weak self] _ in
            self?.readBattery()
        }

        wireUp()
        readBattery()
        thermalChanged()
        addresses = DeviceInfo.addresses()
        server.start()
        updateIdleTimer()

        heartbeat = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] _ in
            self?.heartbeatTick()
        }

        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized:
            cameraAllowed()
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .video) { granted in
                DispatchQueue.main.async {
                    if granted { self.cameraAllowed() } else { self.cameraDenied() }
                }
            }
        default:
            cameraDenied()
        }
    }

    private func cameraAllowed() {
        authorized = true
        applySettings()
        updateCameraRunning()
    }

    private func cameraDenied() {
        authorized = false
        cameraError = "Camera access is off. Turn it on in Settings > Taco Cam > Camera."
        scheduleState()
    }

    private func wireUp() {
        let server = self.server
        let encoder = self.encoder
        let streamFlag = self.streamFlag
        let encodeParams = self.encodeParams

        camera.onSampleBuffer = { sb in
            guard streamFlag.get() else { return }
            let p = encodeParams.get()
            encoder.encode(sb, codec: p.codec, fps: p.fps, bitrateMbps: p.bitrateMbps)
        }
        camera.onEvent = { text in
            server.sendLog(text)
        }
        camera.onInterruption = { [weak self] reason in
            DispatchQueue.main.async {
                guard let self = self else { return }
                if self.interruption != reason { self.interruption = reason }
                self.scheduleState()
            }
        }
        encoder.onFrame = { frame in
            server.sendVideo(frame)
        }
        encoder.onError = { text in
            server.sendLog(text)
        }
        server.onKeyframeRequest = {
            encoder.requestKeyframe()
        }
        server.onConnected = { [weak self] in
            guard let self = self else { return }
            self.connected = true
            self.updateIdleTimer()
            self.updateCameraRunning()
        }
        server.onDisconnected = { [weak self] in
            guard let self = self else { return }
            self.connected = false
            self.streaming = false
            self.videoStartPending = false
            streamFlag.set(false)
            encoder.invalidate()
            self.fpsOut = 0
            self.mbpsOut = 0
            self.updateIdleTimer()
            self.updateCameraRunning()
        }
        server.onHello = { [weak self] _ in
            guard let self = self else { return }
            // Handshake: phone HELLO, then a STATE, then the PC's SET, then VIDEO.
            server.send(.hello, json: [
                "proto": 1,
                "app": "TacoCam",
                "version": "1.0",
                "device": DeviceInfo.modelName,
                "ios": UIDevice.current.systemVersion,
            ])
            self.sendStateNow()
        }
        server.onSet = { [weak self] obj in
            guard let self = self else { return }
            self.desired.merge(obj)
            self.desired.save()
            if !self.streaming { self.videoStartPending = true }
            self.applySettings()
            self.updateCameraRunning()
        }
        server.onFocusPoint = { [weak self] p in
            self?.focus(at: p)
        }
        server.onVideoStart = { [weak self] in
            guard let self = self else { return }
            self.streaming = true
            self.videoStartPending = false
            encoder.requestKeyframe()
            streamFlag.set(true)
        }
        server.onStats = { [weak self] fps, mbps, _ in
            guard let self = self else { return }
            if abs(self.fpsOut - fps) > 0.05 { self.fpsOut = fps }
            if abs(self.mbpsOut - mbps) > 0.05 { self.mbpsOut = mbps }
        }
    }

    // MARK: settings

    /// Changes from the phone screen.
    func update(_ change: (inout PhoneSettings) -> Void) {
        var s = desired
        change(&s)
        guard s != desired else { return }
        let screenChanged = s.screen != desired.screen
        desired = s
        desired.save()
        if screenChanged {
            effective.screen = s.screen
            updateCameraRunning()
            scheduleState()
        }
        applySettings()
    }

    func binding<T>(_ kp: WritableKeyPath<PhoneSettings, T>) -> Binding<T> {
        return Binding(get: { self.desired[keyPath: kp] },
                       set: { v in self.update { $0[keyPath: kp] = v } })
    }

    func setZoom(_ z: Double) {
        let lo = caps.available ? caps.minZoom : 0.5
        let hi = caps.available ? caps.maxZoom : 10
        let v = CameraController.round2(PhoneSettings.clamp(z, lo, hi))
        update { $0.zoom = v }
    }

    func focus(at p: CGPoint) {
        if desired.focusMode != "auto" {
            desired.focusMode = "auto"
            desired.save()
        }
        applySettings()
        camera.focus(at: p)
    }

    /// Applies `desired` to the camera; while one apply runs, later changes are folded into one more.
    func applySettings() {
        guard authorized else {
            scheduleState()
            return
        }
        if applyInFlight {
            applyAgain = true
            return
        }
        applyInFlight = true
        camera.apply(desired, fpsCap: fpsCap) { [weak self] r in
            self?.applied(r)
        }
    }

    private func applied(_ r: CameraApplied) {
        applyInFlight = false
        var eff = r.settings
        eff.screen = desired.screen
        effective = eff
        backCaps = r.back
        frontCaps = r.front
        caps = r.current
        streamSize = (r.streamWidth, r.streamHeight)
        encodeParams.set(EncodeParams(codec: eff.codec, fps: eff.fps, bitrateMbps: eff.bitrateMbps))
        cameraError = r.error
        if let e = r.error, e != lastLoggedError {
            server.sendLog(e)
        }
        lastLoggedError = r.error
        currentDevice = r.device
        if let d = r.device, d.uniqueID != coordinatorDeviceID {
            coordinatorDeviceID = d.uniqueID
            if #available(iOS 17.0, *) {
                rotationCoordinator = AVCaptureDevice.RotationCoordinator(device: d, previewLayer: nil)
            }
        }
        scheduleState()
        if r.glideSeconds > 0 {
            // Holds wait for the zoom glide to end (CameraController); apply once more when it has.
            DispatchQueue.main.asyncAfter(deadline: .now() + r.glideSeconds + 0.15) { [weak self] in
                self?.applySettings()
            }
        }
        if applyAgain {
            applyAgain = false
            applySettings()
            return
        }
        if videoStartPending && connected {
            videoStartPending = false
            server.startVideo()
        }
    }

    // MARK: camera running

    private func updateCameraRunning() {
        let shouldRun = authorized && appActive && (connected || desired.screen == "normal")
        if shouldRun && !cameraRunning {
            cameraRunning = true
            camera.start { [weak self] in
                // Torch and some locks only stick once the session runs.
                DispatchQueue.main.async { self?.applySettings() }
            }
        } else if !shouldRun && cameraRunning {
            cameraRunning = false
            camera.stop()
        }
    }

    private func updateIdleTimer() {
        // Keep the screen on while the app is open: if the phone locks, iOS stops the camera and listener.
        UIApplication.shared.isIdleTimerDisabled = appActive
    }

    func scenePhaseChanged(_ phase: ScenePhase) {
        switch phase {
        case .active:
            if !appActive {
                appActive = true
                if interruption == "background" { interruption = nil }
                server.restartIfNeeded()
                cameraRunning = false  // iOS stopped it; start again
                updateCameraRunning()
                addresses = DeviceInfo.addresses()
                updateIdleTimer()
                scheduleState()
            }
        case .background:
            guard appActive else { return }
            appActive = false
            // Tell the PC first: iOS stops the camera in the background.
            endBackgroundTask()
            bgTask = UIApplication.shared.beginBackgroundTask(withName: "TacoCamState") { [weak self] in
                self?.endBackgroundTask()
            }
            sendStateNow()
            server.sendLog("Taco Cam on the iPhone went to the background: open it again to continue")
            streamFlag.set(false)
            updateCameraRunning()
            updateIdleTimer()
            DispatchQueue.main.asyncAfter(deadline: .now() + 2) { [weak self] in
                self?.endBackgroundTask()
            }
        default:
            break
        }
    }

    private func endBackgroundTask() {
        if bgTask != .invalid {
            UIApplication.shared.endBackgroundTask(bgTask)
            bgTask = .invalid
        }
    }

    // MARK: STATE

    func scheduleState() {
        guard !stateScheduled else { return }
        stateScheduled = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.05) { [weak self] in
            guard let self = self else { return }
            self.stateScheduled = false
            self.sendStateNow()
        }
    }

    func sendStateNow() {
        guard connected else { return }
        server.send(.state, json: buildState())
    }

    func buildState() -> [String: Any] {
        return [
            "settings": effective.toDict(),
            "stream": [
                "codec": effective.codec,
                "width": streamSize.width,
                "height": streamSize.height,
                "fps": effective.fps,
            ] as [String: Any],
            "cameras": ["back": backCaps.toDict(), "front": frontCaps.toDict()] as [String: Any],
            "rotation_hint": rotationHint(),
            "orientation": orientationName(UIDevice.current.orientation),
            "battery": CameraController.round2(Double(max(battery, 0))),
            "charging": charging,
            "thermal": thermal,
            "app_active": appActive,
            "interrupted": interruption.map { $0 as Any } ?? NSNull(),
            "error": cameraError.map { $0 as Any } ?? NSNull(),
            "live": currentDevice.map { CameraController.liveValues($0) as Any } ?? NSNull(),
            "app_expires": DeviceInfo.appExpiresISO.map { $0 as Any } ?? NSNull(),
        ]
    }

    /// Phone-screen warning when the sideloaded copy runs out within 2 days (free Apple ID: 7 days).
    var expiryWarning: String? {
        guard let exp = DeviceInfo.appExpires else { return nil }
        let hours = exp.timeIntervalSinceNow / 3600
        if hours > 48 { return nil }
        if hours <= 0 { return "This copy of Taco Cam has expired: reinstall it with iloader on the PC" }
        if hours < 24 { return "Taco Cam stops opening in \(Int(hours.rounded(.up))) h: reinstall it with iloader" }
        return "Taco Cam stops opening in 2 days: reinstall it with iloader"
    }

    private func orientationName(_ o: UIDeviceOrientation) -> String {
        switch o {
        case .portrait: return "portrait"
        case .portraitUpsideDown: return "portrait_upside_down"
        case .landscapeLeft: return "landscape_port_right"   // home button / port on the right
        case .landscapeRight: return "landscape_port_left"
        case .faceUp, .faceDown: return "flat"
        default: return "unknown"
        }
    }

    /// Clockwise degrees the PC turns the frame so the scene is upright (CONTRACT section 3).
    func rotationHint() -> Int {
        if #available(iOS 17.0, *) {
            if let rc = rotationCoordinator as? AVCaptureDevice.RotationCoordinator {
                let a = Int((Double(rc.videoRotationAngleForHorizonLevelCapture) / 90).rounded()) * 90
                return ((a % 360) + 360) % 360
            }
        }
        // Same table for both cameras: AVFoundation's rotation angles (and AVCam's orientation mapping)
        // are camera-independent, and the front frames are sent unmirrored.
        switch lastUprightOrientation {
        case .landscapeLeft: return 0
        case .portraitUpsideDown: return 270
        case .landscapeRight: return 180
        default: return 90
        }
    }

    private func orientationChanged() {
        let o = UIDevice.current.orientation
        if o == .portrait || o == .portraitUpsideDown || o == .landscapeLeft || o == .landscapeRight {
            lastUprightOrientation = o
        }
        scheduleState()
        // The rotation coordinator can settle a moment after the orientation notification.
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [weak self] in self?.scheduleState() }
    }

    private func readBattery() {
        let level = UIDevice.current.batteryLevel
        if level != battery { battery = level }
        let st = UIDevice.current.batteryState
        let ch = st == .charging || st == .full
        if ch != charging { charging = ch }
    }

    private func thermalChanged() {
        let name: String
        let cap: Int
        switch ProcessInfo.processInfo.thermalState {
        case .nominal: name = "nominal"; cap = 60
        case .fair: name = "fair"; cap = 60
        case .serious: name = "serious"; cap = 30
        case .critical: name = "critical"; cap = 24
        @unknown default: name = "nominal"; cap = 60
        }
        if name != thermal { thermal = name }
        if cap != fpsCap {
            let wasCapped = fpsCap < 60
            fpsCap = cap
            if cap < 60 {
                server.sendLog("iPhone is \(name == "critical" ? "very hot" : "hot"): lowering to \(cap) fps at most")
            } else if wasCapped {
                server.sendLog("iPhone cooled down: full frame rate allowed again")
            }
            applySettings()
        }
        scheduleState()
    }

    private func heartbeatTick() {
        tickCount += 1
        readBattery()
        // iOS doesn't always say an interruption ended (e.g. the session was stopped meanwhile).
        if interruption != nil && camera.session.isRunning && !camera.session.isInterrupted {
            interruption = nil
        }
        if tickCount % 3 == 0 {
            let a = DeviceInfo.addresses()
            if a != addresses { addresses = a }
        }
        sendStateNow()
    }

    // MARK: text for the phone screen

    var statusLine: String {
        if !connected {
            return "Plug into the PC with the USB cable and open Taco Cam on the PC"
        }
        if !streaming {
            return "Connected: starting video..."
        }
        return String(format: "Connected: %.0f fps, %.1f Mbps", fpsOut, mbpsOut)
    }

    var interruptionText: String? {
        switch interruption ?? "" {
        case "", "background": return nil
        case "other_app": return "Camera paused: another app (FaceTime, a call) is using it"
        case "split_screen": return "Camera paused: close split screen / slide over"
        case "too_hot": return "Camera paused: the iPhone is too hot"
        default: return "Camera paused by iOS"
        }
    }

    var batteryText: String {
        if battery < 0 { return "Battery ?" }
        return "Battery \(Int((battery * 100).rounded()))%\(charging ? " charging" : "")"
    }
}
