import Foundation
import CoreMedia
import CoreVideo
import VideoToolbox

struct EncodedFrame {
    let data: Data          // Annex-B, parameter sets in front of every keyframe
    let isKeyframe: Bool
    let ptsUs: UInt64
    let codec: String
    let width: Int
    let height: Int
}

/// VTCompressionSession wrapper: H.264 High / HEVC Main, real-time, no frame reordering,
/// keyframe every 2 s and on request, Annex-B output.
final class VideoEncoder {
    struct Config: Equatable {
        var codec: String
        var width: Int
        var height: Int
        var fps: Int
        var bitrateMbps: Double
    }

    /// Called on a VideoToolbox thread.
    var onFrame: ((EncodedFrame) -> Void)?
    /// Called on any thread, rate-limited.
    var onError: ((String) -> Void)?

    private let lock = NSLock()
    private var session: VTCompressionSession?
    private var current: Config?
    private var forceKey = true
    private var lastErrorAt: TimeInterval = 0

    func requestKeyframe() {
        lock.lock()
        forceKey = true
        lock.unlock()
    }

    func invalidate() {
        lock.lock()
        teardownLocked()
        lock.unlock()
    }

    /// Called on the camera's video queue for every captured frame while a PC is connected.
    func encode(_ sampleBuffer: CMSampleBuffer, codec: String, fps: Int, bitrateMbps: Double) {
        guard let imageBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        let want = Config(codec: codec,
                          width: CVPixelBufferGetWidth(imageBuffer),
                          height: CVPixelBufferGetHeight(imageBuffer),
                          fps: fps,
                          bitrateMbps: bitrateMbps)
        lock.lock()
        if let cur = current, session != nil, cur.codec == want.codec, cur.width == want.width,
           cur.height == want.height, cur.fps == want.fps {
            if cur.bitrateMbps != want.bitrateMbps, let s = session {
                VideoEncoder.applyBitrate(s, mbps: want.bitrateMbps)
                current = want
            }
        } else {
            teardownLocked()
            createLocked(want)
        }
        guard let s = session, let cfg = current else {
            lock.unlock()
            return
        }
        let key = forceKey
        forceKey = false
        lock.unlock()

        let pts = CMSampleBufferGetPresentationTimeStamp(sampleBuffer)
        var props: CFDictionary? = nil
        if key {
            props = [kVTEncodeFrameOptionKey_ForceKeyFrame as String: true] as CFDictionary
        }
        let status = VTCompressionSessionEncodeFrame(s, imageBuffer: imageBuffer, presentationTimeStamp: pts,
                                                     duration: CMTime.invalid, frameProperties: props,
                                                     infoFlagsOut: nil) { [weak self] st, _, sb in
            self?.handleOutput(status: st, sampleBuffer: sb, config: cfg)
        }
        if status != noErr {
            if key { requestKeyframe() }
            reportError("Encoder could not take a frame (error \(status))")
        }
    }

    // MARK: private

    private func reportError(_ text: String) {
        let now = Date().timeIntervalSince1970
        lock.lock()
        let tooSoon = now - lastErrorAt < 5
        if !tooSoon { lastErrorAt = now }
        lock.unlock()
        if !tooSoon { onError?(text) }
    }

    private func teardownLocked() {
        if let s = session {
            VTCompressionSessionInvalidate(s)
        }
        session = nil
        current = nil
    }

    private func createLocked(_ c: Config) {
        var created: VTCompressionSession?
        let codecType: CMVideoCodecType = c.codec == "hevc" ? kCMVideoCodecType_HEVC : kCMVideoCodecType_H264
        let st = VTCompressionSessionCreate(allocator: kCFAllocatorDefault,
                                            width: Int32(c.width),
                                            height: Int32(c.height),
                                            codecType: codecType,
                                            encoderSpecification: nil,
                                            imageBufferAttributes: nil,
                                            compressedDataAllocator: nil,
                                            outputCallback: nil,
                                            refcon: nil,
                                            compressionSessionOut: &created)
        guard st == noErr, let s = created else {
            lock.unlock()
            reportError("Could not start the \(c.codec) encoder at \(c.width)x\(c.height) (error \(st))")
            lock.lock()
            return
        }
        VTSessionSetProperty(s, key: kVTCompressionPropertyKey_RealTime, value: kCFBooleanTrue)
        VTSessionSetProperty(s, key: kVTCompressionPropertyKey_AllowFrameReordering, value: kCFBooleanFalse)
        let profile = c.codec == "hevc" ? kVTProfileLevel_HEVC_Main_AutoLevel : kVTProfileLevel_H264_High_AutoLevel
        VTSessionSetProperty(s, key: kVTCompressionPropertyKey_ProfileLevel, value: profile)
        if c.codec != "hevc" {
            VTSessionSetProperty(s, key: kVTCompressionPropertyKey_H264EntropyMode, value: kVTH264EntropyMode_CABAC)
        }
        VTSessionSetProperty(s, key: kVTCompressionPropertyKey_ExpectedFrameRate, value: NSNumber(value: c.fps))
        VTSessionSetProperty(s, key: kVTCompressionPropertyKey_MaxKeyFrameInterval, value: NSNumber(value: c.fps * 2))
        VTSessionSetProperty(s, key: kVTCompressionPropertyKey_MaxKeyFrameIntervalDuration, value: NSNumber(value: 2.0))
        VideoEncoder.applyBitrate(s, mbps: c.bitrateMbps)
        VTCompressionSessionPrepareToEncodeFrames(s)
        session = s
        current = c
        forceKey = true
    }

    private static func applyBitrate(_ s: VTCompressionSession, mbps: Double) {
        let bps = mbps * 1_000_000
        VTSessionSetProperty(s, key: kVTCompressionPropertyKey_AverageBitRate, value: NSNumber(value: Int(bps)))
        // Hard cap: 1.5x the average over any 1 second (bytes, seconds).
        let limits = [NSNumber(value: Int(bps * 1.5 / 8)), NSNumber(value: 1)] as CFArray
        VTSessionSetProperty(s, key: kVTCompressionPropertyKey_DataRateLimits, value: limits)
    }

    private static func parameterSetInfo(_ fmt: CMFormatDescription, hevc: Bool, wantSets: Bool) -> (sets: [Data], lengthSize: Int)? {
        var count = 0
        var nalLen: Int32 = 4
        let st: OSStatus
        if hevc {
            st = CMVideoFormatDescriptionGetHEVCParameterSetAtIndex(fmt, parameterSetIndex: 0,
                                                                    parameterSetPointerOut: nil,
                                                                    parameterSetSizeOut: nil,
                                                                    parameterSetCountOut: &count,
                                                                    nalUnitHeaderLengthOut: &nalLen)
        } else {
            st = CMVideoFormatDescriptionGetH264ParameterSetAtIndex(fmt, parameterSetIndex: 0,
                                                                    parameterSetPointerOut: nil,
                                                                    parameterSetSizeOut: nil,
                                                                    parameterSetCountOut: &count,
                                                                    nalUnitHeaderLengthOut: &nalLen)
        }
        guard st == noErr else { return nil }
        var sets: [Data] = []
        if wantSets {
            for i in 0..<count {
                var ptr: UnsafePointer<UInt8>? = nil
                var size = 0
                let s2: OSStatus
                if hevc {
                    s2 = CMVideoFormatDescriptionGetHEVCParameterSetAtIndex(fmt, parameterSetIndex: i,
                                                                            parameterSetPointerOut: &ptr,
                                                                            parameterSetSizeOut: &size,
                                                                            parameterSetCountOut: nil,
                                                                            nalUnitHeaderLengthOut: nil)
                } else {
                    s2 = CMVideoFormatDescriptionGetH264ParameterSetAtIndex(fmt, parameterSetIndex: i,
                                                                            parameterSetPointerOut: &ptr,
                                                                            parameterSetSizeOut: &size,
                                                                            parameterSetCountOut: nil,
                                                                            nalUnitHeaderLengthOut: nil)
                }
                if s2 == noErr, let p = ptr, size > 0 {
                    sets.append(Data(bytes: p, count: size))
                }
            }
        }
        return (sets, Int(nalLen))
    }

    private func handleOutput(status: OSStatus, sampleBuffer: CMSampleBuffer?, config: Config) {
        guard status == noErr, let sb = sampleBuffer else {
            if status != noErr {
                requestKeyframe()
                reportError("Encoder error \(status)")
            }
            return
        }
        guard CMSampleBufferDataIsReady(sb),
              let block = CMSampleBufferGetDataBuffer(sb),
              let fmt = CMSampleBufferGetFormatDescription(sb) else { return }
        let total = CMBlockBufferGetDataLength(block)
        guard total > 0 else { return }
        var avcc = Data(count: total)
        let copied = avcc.withUnsafeMutableBytes { (raw: UnsafeMutableRawBufferPointer) -> OSStatus in
            guard let base = raw.baseAddress else { return -1 }
            return CMBlockBufferCopyDataBytes(block, atOffset: 0, dataLength: total, destination: base)
        }
        guard copied == noErr else { return }

        var isKey = true
        if let arr = CMSampleBufferGetSampleAttachmentsArray(sb, createIfNecessary: false) as NSArray?,
           let first = arr.firstObject as? NSDictionary,
           let notSync = first[kCMSampleAttachmentKey_NotSync as String] as? Bool {
            isKey = !notSync
        }

        let hevc = config.codec == "hevc"
        guard let info = VideoEncoder.parameterSetInfo(fmt, hevc: hevc, wantSets: isKey),
              let body = AnnexB.fromLengthPrefixed(avcc, lengthSize: info.lengthSize) else {
            requestKeyframe()
            reportError("Encoder produced a frame that could not be converted")
            return
        }
        let annexB = isKey ? AnnexB.withParameterSets(info.sets, frame: body) : body

        let secs = CMTimeGetSeconds(CMSampleBufferGetPresentationTimeStamp(sb))
        let us: UInt64 = (secs.isFinite && secs > 0) ? UInt64(secs * 1_000_000) : 0
        onFrame?(EncodedFrame(data: annexB, isKeyframe: isKey, ptsUs: us, codec: config.codec,
                              width: config.width, height: config.height))
    }
}
