import Foundation

/// Message types, CONTRACT section 2.
enum MsgType: UInt8 {
    case hello = 0x01
    case set = 0x02
    case state = 0x03
    case keyframe = 0x04
    case focusPoint = 0x05
    case video = 0x10
    case ping = 0x20
    case pong = 0x21
    case log = 0x30
}

enum FramingError: Error, Equatable {
    case badLength(UInt32)
}

/// Framing: u32 big-endian N (type byte + payload) + u8 type + N-1 bytes payload.
enum Framing {
    static let maxLength: UInt32 = 16_777_216

    static func appendU32BE(_ v: UInt32, to d: inout Data) {
        d.append(UInt8((v >> 24) & 0xff))
        d.append(UInt8((v >> 16) & 0xff))
        d.append(UInt8((v >> 8) & 0xff))
        d.append(UInt8(v & 0xff))
    }

    static func appendU64BE(_ v: UInt64, to d: inout Data) {
        for shift in stride(from: 56, through: 0, by: -8) {
            d.append(UInt8((v >> UInt64(shift)) & 0xff))
        }
    }

    static func encode(type: UInt8, payload: Data) -> Data {
        var d = Data()
        d.reserveCapacity(5 + payload.count)
        appendU32BE(UInt32(payload.count + 1), to: &d)
        d.append(type)
        d.append(payload)
        return d
    }

    static func encode(_ type: MsgType, payload: Data = Data()) -> Data {
        return encode(type: type.rawValue, payload: payload)
    }

    /// JSON objects only (CONTRACT section 2).
    static func encodeJSON(_ type: MsgType, _ object: [String: Any]) -> Data? {
        guard JSONSerialization.isValidJSONObject(object),
              let body = try? JSONSerialization.data(withJSONObject: object, options: []) else { return nil }
        return encode(type, payload: body)
    }

    static func encodeLog(_ line: String) -> Data {
        return encode(.log, payload: Data(line.utf8))
    }

    /// VIDEO message: u8 flags + u64 BE pts_us + Annex-B bitstream, all framed.
    static func encodeVideo(flags: UInt8, ptsUs: UInt64, annexB: Data) -> Data {
        var d = Data()
        d.reserveCapacity(5 + 9 + annexB.count)
        appendU32BE(UInt32(1 + 9 + annexB.count), to: &d)
        d.append(MsgType.video.rawValue)
        d.append(flags)
        appendU64BE(ptsUs, to: &d)
        d.append(annexB)
        return d
    }

    static let flagKeyframe: UInt8 = 0x01
    static let flagFormatChanged: UInt8 = 0x02
}

/// Incremental parser for the byte stream from the PC.
struct FrameParser {
    private var buffer: [UInt8] = []

    var bufferedCount: Int { return buffer.count }

    /// Returns every complete message in the buffer. Throws on a length outside 1...16_777_216
    /// (the caller then drops the connection).
    mutating func feed(_ data: Data) throws -> [(type: UInt8, payload: Data)] {
        buffer.append(contentsOf: data)
        var out: [(type: UInt8, payload: Data)] = []
        var offset = 0
        while buffer.count - offset >= 4 {
            let n = (UInt32(buffer[offset]) << 24) | (UInt32(buffer[offset + 1]) << 16)
                | (UInt32(buffer[offset + 2]) << 8) | UInt32(buffer[offset + 3])
            if n < 1 || n > Framing.maxLength {
                buffer.removeAll()
                throw FramingError.badLength(n)
            }
            let total = 4 + Int(n)
            if buffer.count - offset < total { break }
            let type = buffer[offset + 4]
            let payload = Data(buffer[(offset + 5)..<(offset + total)])
            out.append((type: type, payload: payload))
            offset += total
        }
        if offset > 0 {
            buffer.removeFirst(offset)
        }
        return out
    }

    static func jsonObject(_ payload: Data) -> [String: Any]? {
        guard let obj = try? JSONSerialization.jsonObject(with: payload, options: []) else { return nil }
        return obj as? [String: Any]
    }
}
