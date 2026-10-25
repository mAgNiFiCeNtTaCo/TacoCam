import SwiftUI
import UIKit
import AVFoundation

/// Full-screen live preview. The app UI is portrait-only, so the preview is always turned for portrait
/// (the stream to the PC is never rotated). Tap = focus point, pinch = zoom.
final class PreviewUIView: UIView {
    override class var layerClass: AnyClass { return AVCaptureVideoPreviewLayer.self }

    var previewLayer: AVCaptureVideoPreviewLayer {
        return layer as! AVCaptureVideoPreviewLayer
    }

    /// Device point of interest (0..1, sensor coordinates).
    var onTap: ((CGPoint) -> Void)?
    /// Pinch scale relative to the start of the gesture; `ended` true on the last call.
    var onPinch: ((CGFloat, Bool) -> Void)?

    override init(frame: CGRect) {
        super.init(frame: frame)
        backgroundColor = .black
        previewLayer.videoGravity = .resizeAspect
        addGestureRecognizer(UITapGestureRecognizer(target: self, action: #selector(tapped(_:))))
        addGestureRecognizer(UIPinchGestureRecognizer(target: self, action: #selector(pinched(_:))))
    }

    required init?(coder: NSCoder) {
        fatalError("not used")
    }

    override func layoutSubviews() {
        super.layoutSubviews()
        fixRotation()
    }

    func fixRotation() {
        guard let c = previewLayer.connection else { return }
        if #available(iOS 17.0, *) {
            if c.isVideoRotationAngleSupported(90) && c.videoRotationAngle != 90 {
                c.videoRotationAngle = 90
            }
        } else {
            if c.isVideoOrientationSupported && c.videoOrientation != .portrait {
                c.videoOrientation = .portrait
            }
        }
    }

    @objc private func tapped(_ g: UITapGestureRecognizer) {
        let p = g.location(in: self)
        let devicePoint = previewLayer.captureDevicePointConverted(fromLayerPoint: p)
        onTap?(devicePoint)
    }

    @objc private func pinched(_ g: UIPinchGestureRecognizer) {
        switch g.state {
        case .began, .changed:
            onPinch?(g.scale, false)
        case .ended, .cancelled, .failed:
            onPinch?(g.scale, true)
        default:
            break
        }
    }
}

struct CameraPreview: UIViewRepresentable {
    let session: AVCaptureSession
    let onTap: (CGPoint) -> Void
    let onPinch: (CGFloat, Bool) -> Void

    func makeUIView(context: Context) -> PreviewUIView {
        let v = PreviewUIView(frame: .zero)
        v.previewLayer.session = session
        v.onTap = onTap
        v.onPinch = onPinch
        return v
    }

    func updateUIView(_ v: PreviewUIView, context: Context) {
        v.onTap = onTap
        v.onPinch = onPinch
        v.fixRotation()
    }
}
