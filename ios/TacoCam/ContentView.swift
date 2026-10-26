import SwiftUI

let tacoOrange = Color(red: 1.0, green: 0.58, blue: 0.12)

struct ContentView: View {
    @ObservedObject var model: AppModel
    @Environment(\.scenePhase) private var scenePhase
    @State private var pinchBase: Double? = nil

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()

            CameraPreview(session: model.camera.session,
                          onTap: { p in model.focus(at: p) },
                          onPinch: { scale, ended in
                              if pinchBase == nil { pinchBase = model.effective.zoom }
                              model.setZoom((pinchBase ?? 1) * Double(scale))
                              if ended { pinchBase = nil }
                          })
                .ignoresSafeArea()

            VStack(spacing: 10) {
                topInfo
                Spacer()
                zoomButtons
                bottomBar
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)

            if model.effective.screen == "dim" {
                dimOverlay
            }
        }
        .statusBarHidden(true)
        .persistentSystemOverlays(.hidden)
        .sheet(isPresented: $model.showSettings) {
            SettingsView(model: model)
        }
        .onAppear { model.start() }
        .onChange(of: scenePhase) { phase in
            model.scenePhaseChanged(phase)
        }
    }

    // MARK: pieces

    private var topInfo: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(model.statusLine)
                .font(.headline)
                .foregroundColor(model.connected ? .green : .white)
                .fixedSize(horizontal: false, vertical: true)
            if let warn = model.expiryWarning {
                Text(warn)
                    .font(.subheadline)
                    .foregroundColor(tacoOrange)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let paused = model.interruptionText {
                Text(paused)
                    .font(.subheadline)
                    .foregroundColor(tacoOrange)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let err = model.cameraError {
                Text(err)
                    .font(.subheadline)
                    .foregroundColor(.red)
                    .fixedSize(horizontal: false, vertical: true)
            }
            HStack(spacing: 12) {
                Text(model.batteryText)
                Text("Heat: \(model.thermal)")
                    .foregroundColor(model.thermal == "serious" || model.thermal == "critical" ? .orange : .white)
            }
            .font(.caption)
            if !model.addresses.isEmpty {
                Text("Wi-Fi mode: " + model.addresses.joined(separator: "  "))
                    .font(.caption2)
                    .foregroundColor(.white.opacity(0.8))
            }
        }
        .foregroundColor(.white)
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.black.opacity(0.45))
        .cornerRadius(12)
    }

    private func zoomLabel(_ z: Double) -> String {
        if abs(z - z.rounded()) < 0.05 { return "\(Int(z.rounded()))x" }
        let s = String(format: "%.1fx", z)
        return z < 1 && s.hasPrefix("0") ? String(s.dropFirst()) : s
    }

    private var zoomButtons: some View {
        let lenses = model.caps.lensZooms.isEmpty ? [1.0] : model.caps.lensZooms
        let current = model.effective.zoom
        // The button for the lens range the current zoom falls in is highlighted.
        let active = lenses.last(where: { $0 <= current + 0.01 }) ?? lenses[0]
        return HStack(spacing: 12) {
            ForEach(lenses, id: \.self) { z in
                Button(action: { model.setZoom(z) }) {
                    Text(z == active && abs(current - z) > 0.05 ? zoomLabel(current) : zoomLabel(z))
                        .font(.system(size: 14, weight: .bold))
                        .foregroundColor(z == active ? tacoOrange : .white)
                        .frame(width: 48, height: 48)
                        .background(Circle().fill(Color.black.opacity(0.55)))
                }
            }
        }
    }

    private var bottomBar: some View {
        HStack {
            roundButton("arrow.triangle.2.circlepath.camera", label: "Flip") {
                model.update { $0.camera = ($0.camera == "back" ? "front" : "back") }
            }
            Spacer()
            roundButton(model.effective.torch > 0 ? "flashlight.on.fill" : "flashlight.off.fill",
                        label: "Light", tint: model.effective.torch > 0 ? tacoOrange : .white) {
                model.update { $0.torch = ($0.torch > 0 ? 0 : 1) }
            }
            .disabled(!model.caps.hasTorch || model.effective.camera == "front")
            .opacity(!model.caps.hasTorch || model.effective.camera == "front" ? 0.4 : 1)
            Spacer()
            roundButton("moon.fill", label: "Dim") {
                model.update { $0.screen = "dim" }
            }
            Spacer()
            roundButton("gearshape.fill", label: "Settings") {
                model.showSettings = true
            }
        }
    }

    private func roundButton(_ symbol: String, label: String, tint: Color = .white,
                             action: @escaping () -> Void) -> some View {
        Button(action: action) {
            VStack(spacing: 4) {
                Image(systemName: symbol)
                    .font(.system(size: 22, weight: .semibold))
                    .foregroundColor(tint)
                    .frame(width: 56, height: 56)
                    .background(Circle().fill(Color.black.opacity(0.55)))
                Text(label)
                    .font(.caption2)
                    .foregroundColor(.white)
            }
        }
    }

    private var dimOverlay: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            VStack(spacing: 8) {
                Text(model.statusLine)
                    .font(.footnote)
                    .foregroundColor(.white.opacity(0.35))
                    .multilineTextAlignment(.center)
                Text("Screen dimmed. Tap to wake.")
                    .font(.caption2)
                    .foregroundColor(.white.opacity(0.25))
            }
            .padding(24)
        }
        .contentShape(Rectangle())
        .onTapGesture {
            model.update { $0.screen = "normal" }
        }
    }
}
