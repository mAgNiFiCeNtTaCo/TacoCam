import Foundation

/// AVCC/HVCC (length-prefixed NAL units, as VideoToolbox writes them) -> Annex-B (00 00 00 01 start codes).
enum AnnexB {
    static let startCode = Data([0x00, 0x00, 0x00, 0x01])

    /// Converts length-prefixed NAL units to Annex-B. Returns nil if a length runs past the end
    /// or the prefix size is not 1, 2 or 4.
    static func fromLengthPrefixed(_ data: Data, lengthSize: Int = 4) -> Data? {
        guard lengthSize == 1 || lengthSize == 2 || lengthSize == 4 else { return nil }
        let bytes = [UInt8](data)
        var out = Data()
        out.reserveCapacity(bytes.count + 16)
        var i = 0
        while i < bytes.count {
            if bytes.count - i < lengthSize { return nil }
            var len = 0
            for k in 0..<lengthSize {
                len = (len << 8) | Int(bytes[i + k])
            }
            i += lengthSize
            if len > bytes.count - i { return nil }
            if len > 0 {
                out.append(startCode)
                out.append(contentsOf: bytes[i..<(i + len)])
            }
            i += len
        }
        return out
    }

    /// Parameter sets (each without a start code) in front of the frame's NAL units.
    static func withParameterSets(_ parameterSets: [Data], frame: Data) -> Data {
        var out = Data()
        out.reserveCapacity(frame.count + parameterSets.reduce(0) { $0 + $1.count + 4 })
        for ps in parameterSets {
            out.append(startCode)
            out.append(ps)
        }
        out.append(frame)
        return out
    }
}
