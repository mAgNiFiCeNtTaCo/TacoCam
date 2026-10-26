import Foundation
import SwiftUI
import UIKit

/// The same controls the PC has. Every change goes to the camera and a STATE to the PC.
struct SettingsView: View {
    @ObservedObject var model: AppModel
    @Environment(\.dismiss) private var dismiss

    private var caps: CameraCaps { return model.caps }

    private func range(_ values: [Double], fallback: ClosedRange<Double>) -> ClosedRange<Double> {
        guard values.count == 2, values[0] < values[1] else { return fallback }
        return values[0]...values[1]
    }

    private var zoomRange: ClosedRange<Double> {
        let lo = caps.available ? caps.minZoom : 0.5
        let hi = caps.available ? caps.maxZoom : 10
        return lo...max(hi, lo + 0.1)
    }

    private var isoRange: ClosedRange<Double> { return range(caps.isoRange, fallback: 25...3200) }

    private var shutterLogRange: ClosedRange<Double> {
        let r = range(caps.shutterRange, fallback: 0.0001...(1.0 / 30))
        return log10(r.lowerBound)...log10(r.upperBound)
    }

    private func shutterText(_ s: Double) -> String {
        if s <= 0 { return "-" }
        if s >= 0.5 { return String(format: "%.1f s", s) }
        return "1/\(Int((1 / s).rounded())) s"
    }

    private var zoomBinding: Binding<Double> {
        return Binding(get: { model.desired.zoom }, set: { model.setZoom($0) })
    }

    private var isoBinding: Binding<Double> {
        return Binding(get: {
            let r = isoRange
            return min(max(model.desired.exposureISO ?? (r.lowerBound + r.upperBound) / 4, r.lowerBound), r.upperBound)
        }, set: { v in
            model.update { $0.exposureISO = v.rounded() }
        })
    }

    private var shutterBinding: Binding<Double> {
        return Binding(get: {
            let r = shutterLogRange
            return min(max(log10(model.desired.exposureShutter ?? (1.0 / 60)), r.lowerBound), r.upperBound)
        }, set: { v in
            model.update { $0.exposureShutter = pow(10, v) }
        })
    }

    private var resolutionChoices: [String] {
        return caps.resolutions.isEmpty ? PhoneSettings.resolutions : caps.resolutions
    }

    private var fpsChoices: [Int] {
        let list = caps.fps[model.desired.resolution] ?? []
        return list.isEmpty ? PhoneSettings.fpsChoices : list
    }

    private var stabilizationChoices: [String] {
        return caps.stabilization.isEmpty ? ["off"] : caps.stabilization
    }

    private var cameraSection: some View {
        Section(header: Text("Camera")) {
            Picker("Camera", selection: model.binding(\.camera)) {
                Text("Back").tag("back")
                Text("Front").tag("front")
            }
            .pickerStyle(.segmented)
            VStack(alignment: .leading) {
                Text("Zoom \(String(format: "%.1f", model.effective.zoom))x")
                Slider(value: zoomBinding, in: zoomRange)
            }
        }
    }

    private var videoSection: some View {
        Section(header: Text("Video")) {
            Picker("Resolution", selection: model.binding(\.resolution)) {
                ForEach(resolutionChoices, id: \.self) { r in
                    Text(r).tag(r)
                }
            }
            Picker("Frame rate", selection: model.binding(\.fps)) {
                ForEach(fpsChoices, id: \.self) { f in
                    Text("\(f) fps").tag(f)
                }
            }
            Picker("Codec", selection: model.binding(\.codec)) {
                Text("H.264").tag("h264")
                Text("HEVC").tag("hevc")
            }
            .pickerStyle(.segmented)
            VStack(alignment: .leading) {
                Text("Bitrate \(Int(model.desired.bitrateMbps.rounded())) Mbps")
                Slider(value: model.binding(\.bitrateMbps), in: 2...80, step: 1)
            }
            Picker("Stabilization", selection: model.binding(\.stabilization)) {
                ForEach(stabilizationChoices, id: \.self) { s in
                    Text(s.capitalized).tag(s)
                }
            }
            Toggle("HDR", isOn: model.binding(\.hdr))
                .disabled(!caps.hdr)
        }
    }

    private var focusSection: some View {
        Section(header: Text("Focus")) {
            Picker("Focus", selection: model.binding(\.focusMode)) {
                Text("Auto").tag("auto")
                Text("Manual").tag("manual")
            }
            .pickerStyle(.segmented)
            if model.desired.focusMode == "manual" {
                if caps.focusManual {
                    VStack(alignment: .leading) {
                        Text("Near  \u{2190}  lens position \(String(format: "%.2f", model.desired.focusPosition))  \u{2192}  far")
                            .font(.caption)
                        Slider(value: model.binding(\.focusPosition), in: 0...1)
                    }
                } else {
                    Text("This camera does not allow manual focus.")
                        .font(.caption)
                }
            }
        }
    }

    private var exposureSection: some View {
        Section(header: Text("Exposure")) {
            Picker("Exposure", selection: model.binding(\.exposureMode)) {
                Text("Auto").tag("auto")
                Text("Manual").tag("manual")
            }
            .pickerStyle(.segmented)
            if model.desired.exposureMode == "manual" {
                VStack(alignment: .leading) {
                    Text("ISO \(Int(model.effective.exposureISO ?? isoBinding.wrappedValue))")
                    Slider(value: isoBinding, in: isoRange)
                }
                VStack(alignment: .leading) {
                    Text("Shutter \(shutterText(model.effective.exposureShutter ?? pow(10, shutterBinding.wrappedValue)))")
                    Slider(value: shutterBinding, in: shutterLogRange)
                }
            } else {
                VStack(alignment: .leading) {
                    Text("Brightness \(String(format: "%+.1f", model.desired.exposureBias)) EV")
                    Slider(value: model.binding(\.exposureBias), in: -3...3, step: 0.1)
                }
                Picker("Anti-flicker", selection: model.binding(\.antiFlicker)) {
                    Text("Off").tag("off")
                    Text("60 Hz (US)").tag("60hz")
                    Text("50 Hz").tag("50hz")
                }
            }
        }
    }

    private var wbSection: some View {
        Section(header: Text("White balance")) {
            Picker("White balance", selection: model.binding(\.wbMode)) {
                Text("Auto").tag("auto")
                Text("Manual").tag("manual")
            }
            .pickerStyle(.segmented)
            if model.desired.wbMode == "manual" {
                VStack(alignment: .leading) {
                    Text("Temperature \(Int(model.desired.wbTemperature)) K")
                    Slider(value: model.binding(\.wbTemperature), in: 2500...8000, step: 50)
                }
                VStack(alignment: .leading) {
                    Text("Tint \(Int(model.desired.wbTint))")
                    Slider(value: model.binding(\.wbTint), in: -150...150, step: 1)
                }
            }
        }
    }

    private var lightSection: some View {
        Section(header: Text("Light and screen")) {
            if caps.hasTorch && model.effective.camera == "back" {
                VStack(alignment: .leading) {
                    Text(model.desired.torch > 0 ? "Light \(Int((model.desired.torch * 100).rounded()))%" : "Light off")
                    Slider(value: model.binding(\.torch), in: 0...1, step: 0.05)
                }
            } else {
                Text("No light on this camera").font(.caption)
            }
            Button("Dim screen (tap the black screen to wake it)") {
                model.update { $0.screen = "dim" }
                dismiss()
            }
        }
    }

    private var aboutSection: some View {
        Section(header: Text("About")) {
            Text("\(DeviceInfo.modelName), iOS \(UIDevice.current.systemVersion)")
            Text("Camera: \(caps.name.isEmpty ? "-" : caps.name)")
            if let exp = DeviceInfo.appExpires {
                Text("This copy stops opening: \(exp.formatted(date: .abbreviated, time: .shortened)) (reinstall with iloader)")
                    .font(.caption)
            }
            Text("USB port 47777. Wi-Fi mode: \(model.addresses.isEmpty ? "no Wi-Fi address" : model.addresses.joined(separator: ", "))")
                .font(.caption)
        }
    }

    var body: some View {
        NavigationView {
            Form {
                cameraSection
                videoSection
                focusSection
                exposureSection
                wbSection
                lightSection
                aboutSection
            }
            .navigationTitle("Taco Cam settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }
}
