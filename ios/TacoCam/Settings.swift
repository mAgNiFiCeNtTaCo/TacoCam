import Foundation

/// Phone settings, CONTRACT section 4. `merge` takes a (partial) SET payload, `toDict` gives the
/// STATE `settings` object.
struct PhoneSettings: Equatable {
    var camera = "back"
    var zoom: Double = 1.0
    var zoomGlide: Double = 0       // seconds a zoom change takes (0 = jump)
    var resolution = "1080p"
    var fps = 30
    var codec = "h264"
    var bitrateMbps: Double = 16
    var focusMode = "auto"
    var focusPosition: Double = 0.5
    var exposureMode = "auto"
    var exposureBias: Double = 0
    var exposureISO: Double? = nil
    var exposureShutter: Double? = nil
    var wbMode = "auto"
    var wbTemperature: Double = 5000
    var wbTint: Double = 0
    var torch: Double = 0
    var stabilization = "off"
    var hdr = false
    var screen = "normal"
    var antiFlicker = "off"

    static let resolutions = ["720p", "1080p", "4k"]
    static let antiFlickers = ["off", "60hz", "50hz"]
    static let fpsChoices = [24, 25, 30, 60]
    static let codecs = ["h264", "hevc"]
    static let stabilizations = ["off", "standard", "cinematic"]

    static func size(of resolution: String) -> (width: Int, height: Int) {
        switch resolution {
        case "720p": return (1280, 720)
        case "4k": return (3840, 2160)
        default: return (1920, 1080)
        }
    }

    static func clamp(_ v: Double, _ lo: Double, _ hi: Double) -> Double {
        if v.isNaN { return lo }
        return min(max(v, lo), hi)
    }

    private static func number(_ v: Any?) -> Double? {
        guard let v = v, !(v is NSNull) else { return nil }
        if let n = v as? NSNumber { return n.doubleValue }
        if let s = v as? String { return Double(s) }
        return nil
    }

    /// Applies a partial settings object; unknown keys and bad values are ignored.
    mutating func merge(_ d: [String: Any]) {
        if let v = d["camera"] as? String, v == "back" || v == "front" { camera = v }
        if let v = PhoneSettings.number(d["zoom"]) { zoom = PhoneSettings.clamp(v, 0.5, 100) }
        if let v = PhoneSettings.number(d["zoom_glide_s"]) { zoomGlide = PhoneSettings.clamp(v, 0, 3) }
        if let v = d["resolution"] as? String, PhoneSettings.resolutions.contains(v) { resolution = v }
        if let v = PhoneSettings.number(d["fps"]) {
            fps = PhoneSettings.fpsChoices.min(by: { abs(Double($0) - v) < abs(Double($1) - v) }) ?? 30
        }
        if let v = d["codec"] as? String, PhoneSettings.codecs.contains(v) { codec = v }
        if let v = PhoneSettings.number(d["bitrate_mbps"]) { bitrateMbps = PhoneSettings.clamp(v, 2, 80) }
        if let f = d["focus"] as? [String: Any] {
            if let m = f["mode"] as? String, m == "auto" || m == "manual" { focusMode = m }
            if let p = PhoneSettings.number(f["position"]) { focusPosition = PhoneSettings.clamp(p, 0, 1) }
        }
        if let e = d["exposure"] as? [String: Any] {
            if let m = e["mode"] as? String, m == "auto" || m == "manual" { exposureMode = m }
            if let b = PhoneSettings.number(e["bias"]) { exposureBias = PhoneSettings.clamp(b, -3, 3) }
            if let iso = e["iso"] {
                if iso is NSNull { exposureISO = nil } else if let n = PhoneSettings.number(iso), n > 0 { exposureISO = n }
            }
            if let sh = e["shutter_s"] {
                if sh is NSNull { exposureShutter = nil } else if let n = PhoneSettings.number(sh), n > 0 { exposureShutter = n }
            }
        }
        if let w = d["white_balance"] as? [String: Any] {
            if let m = w["mode"] as? String, m == "auto" || m == "manual" { wbMode = m }
            if let t = PhoneSettings.number(w["temperature"]) { wbTemperature = PhoneSettings.clamp(t, 2500, 8000) }
            if let t = PhoneSettings.number(w["tint"]) { wbTint = PhoneSettings.clamp(t, -150, 150) }
        }
        if let v = PhoneSettings.number(d["torch"]) {
            let t = PhoneSettings.clamp(v, 0, 1)
            torch = (t > 0 && t < 0.01) ? 0.01 : t
        }
        if let v = d["stabilization"] as? String, PhoneSettings.stabilizations.contains(v) { stabilization = v }
        if let v = d["hdr"] as? Bool { hdr = v }
        if let v = d["screen"] as? String, v == "normal" || v == "dim" { screen = v }
        if let v = d["anti_flicker"] as? String, PhoneSettings.antiFlickers.contains(v) { antiFlicker = v }
    }

    /// Whole numbers go out as JSON integers (5000, not 5000.0), others rounded to 6 decimals.
    static func json(_ x: Double) -> Any {
        if x.isNaN || x.isInfinite { return 0 }
        if x == x.rounded() && abs(x) < 1e12 { return Int(x) }
        return (x * 1_000_000).rounded() / 1_000_000
    }

    static func jsonOptional(_ x: Double?) -> Any {
        guard let x = x else { return NSNull() }
        return json(x)
    }

    func toDict() -> [String: Any] {
        return [
            "camera": camera,
            "zoom": PhoneSettings.json(zoom),
            "zoom_glide_s": PhoneSettings.json(zoomGlide),
            "resolution": resolution,
            "fps": fps,
            "codec": codec,
            "bitrate_mbps": PhoneSettings.json(bitrateMbps),
            "focus": ["mode": focusMode, "position": PhoneSettings.json(focusPosition)] as [String: Any],
            "exposure": [
                "mode": exposureMode,
                "bias": PhoneSettings.json(exposureBias),
                "iso": PhoneSettings.jsonOptional(exposureISO),
                "shutter_s": PhoneSettings.jsonOptional(exposureShutter),
            ] as [String: Any],
            "white_balance": [
                "mode": wbMode,
                "temperature": PhoneSettings.json(wbTemperature),
                "tint": PhoneSettings.json(wbTint),
            ] as [String: Any],
            "torch": PhoneSettings.json(torch),
            "stabilization": stabilization,
            "hdr": hdr,
            "screen": screen,
            "anti_flicker": antiFlicker,
        ]
    }

    // MARK: remembered settings

    private static let defaultsKey = "TacoCamSettings"

    static func load() -> PhoneSettings {
        var s = PhoneSettings()
        if let data = UserDefaults.standard.data(forKey: defaultsKey),
           let obj = FrameParser.jsonObject(data) {
            s.merge(obj)
        }
        s.screen = "normal"
        return s
    }

    func save() {
        if let data = try? JSONSerialization.data(withJSONObject: toDict(), options: []) {
            UserDefaults.standard.set(data, forKey: PhoneSettings.defaultsKey)
        }
    }
}
