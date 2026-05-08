// audio-tap — captures macOS system audio output via ScreenCaptureKit and
// writes 16 kHz mono int16 PCM to stdout. Status / errors go to stderr as
// line-delimited JSON so the Rust parent can consume them without parsing
// the binary stdout stream.
//
// Wire protocol:
//   stdout: raw int16 little-endian PCM, 16 kHz mono, no header
//   stderr: one JSON object per line, e.g.
//             {"type":"ready"}
//             {"type":"error","kind":"permission_denied","message":"..."}
//             {"type":"info","message":"..."}
//
// Lifecycle:
//   - Read stdin: any line containing "stop" → graceful shutdown.
//   - SIGTERM / SIGINT → graceful shutdown.
//
// Why a separate binary:
//   - ScreenCaptureKit pulls in heavy macOS frameworks; isolating it from
//     the Tauri/Rust process keeps the main bundle lean and lets us crash
//     the helper without taking the app down.
//   - Permission prompts are surfaced exactly when the helper starts,
//     which is the moment the user pressed "use system audio" — clearest
//     UX.

import AVFoundation
import CoreGraphics
import CoreMedia
import Foundation
import ScreenCaptureKit

// ---------------------------------------------------------------------------
// JSON status output
// ---------------------------------------------------------------------------

@inline(__always)
func emit(_ obj: [String: Any]) {
    guard let data = try? JSONSerialization.data(withJSONObject: obj, options: []) else { return }
    var line = data
    line.append(0x0A)  // newline
    FileHandle.standardError.write(line)
}

func fatalEmit(_ kind: String, _ message: String) -> Never {
    emit(["type": "error", "kind": kind, "message": message])
    exit(1)
}

// ---------------------------------------------------------------------------
// Resampler — 48 kHz stereo float32 → 16 kHz mono int16
// ---------------------------------------------------------------------------

final class Resampler {
    private let inputFormat: AVAudioFormat
    private let outputFormat: AVAudioFormat
    private let converter: AVAudioConverter

    init(inputSampleRate: Double, inputChannels: AVAudioChannelCount) {
        // ScreenCaptureKit emits non-interleaved float32 audio.
        guard
            let input = AVAudioFormat(
                commonFormat: .pcmFormatFloat32,
                sampleRate: inputSampleRate,
                channels: inputChannels,
                interleaved: false
            ),
            let output = AVAudioFormat(
                commonFormat: .pcmFormatInt16,
                sampleRate: 16_000,
                channels: 1,
                interleaved: true
            ),
            let converter = AVAudioConverter(from: input, to: output)
        else {
            fatalEmit("init", "could not build AVAudioConverter")
        }
        self.inputFormat = input
        self.outputFormat = output
        self.converter = converter
    }

    /// Convert one CMSampleBuffer's audio to int16 mono 16 kHz PCM bytes.
    func convert(_ sampleBuffer: CMSampleBuffer) -> Data? {
        guard let inBuf = pcmBuffer(from: sampleBuffer) else { return nil }

        // Output capacity: input frames × (16000 / inputSR) + slack
        let inFrames = Double(inBuf.frameLength)
        let ratio = 16_000.0 / inputFormat.sampleRate
        let outCapacity = AVAudioFrameCount((inFrames * ratio).rounded(.up) + 32)

        guard
            let outBuf = AVAudioPCMBuffer(
                pcmFormat: outputFormat,
                frameCapacity: outCapacity
            )
        else {
            return nil
        }

        var consumed = false
        var convError: NSError?
        let status = converter.convert(to: outBuf, error: &convError) { _, outStatus in
            if consumed {
                outStatus.pointee = .noDataNow
                return nil
            }
            consumed = true
            outStatus.pointee = .haveData
            return inBuf
        }

        if status == .error || convError != nil {
            return nil
        }

        guard let int16 = outBuf.int16ChannelData?.pointee else { return nil }
        let frameCount = Int(outBuf.frameLength)
        let byteCount = frameCount * MemoryLayout<Int16>.size
        return Data(bytes: int16, count: byteCount)
    }

    private func pcmBuffer(from sb: CMSampleBuffer) -> AVAudioPCMBuffer? {
        guard let formatDesc = CMSampleBufferGetFormatDescription(sb) else { return nil }
        guard let asbdPtr = CMAudioFormatDescriptionGetStreamBasicDescription(formatDesc) else {
            return nil
        }
        var asbd = asbdPtr.pointee
        guard let avFormat = AVAudioFormat(streamDescription: &asbd) else {
            return nil
        }
        let frames = AVAudioFrameCount(CMSampleBufferGetNumSamples(sb))
        guard
            let pcm = AVAudioPCMBuffer(pcmFormat: avFormat, frameCapacity: frames)
        else {
            return nil
        }
        pcm.frameLength = frames

        // Copy CMSampleBuffer audio into our AVAudioPCMBuffer.
        var blockBuffer: CMBlockBuffer?
        var audioBufferList = AudioBufferList()
        let listSize = MemoryLayout<AudioBufferList>.size
        let result = CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
            sb,
            bufferListSizeNeededOut: nil,
            bufferListOut: &audioBufferList,
            bufferListSize: listSize,
            blockBufferAllocator: nil,
            blockBufferMemoryAllocator: nil,
            flags: kCMSampleBufferFlag_AudioBufferList_Assure16ByteAlignment,
            blockBufferOut: &blockBuffer
        )
        guard result == noErr else { return nil }

        let abl = UnsafeMutableAudioBufferListPointer(&audioBufferList)
        for i in 0..<min(abl.count, Int(pcm.format.channelCount)) {
            guard
                let src = abl[i].mData?.assumingMemoryBound(to: Float.self),
                let dst = pcm.floatChannelData?[i]
            else { continue }
            let n = Int(abl[i].mDataByteSize) / MemoryLayout<Float>.size
            dst.update(from: src, count: min(n, Int(frames)))
        }
        return pcm
    }
}

// ---------------------------------------------------------------------------
// SCStream output handler
// ---------------------------------------------------------------------------

final class AudioTap: NSObject, SCStreamOutput, SCStreamDelegate {
    private var resampler: Resampler?
    private let stdout = FileHandle.standardOutput
    private let writeQueue = DispatchQueue(label: "audio-tap.write", qos: .userInitiated)

    func stream(
        _ stream: SCStream,
        didOutputSampleBuffer sampleBuffer: CMSampleBuffer,
        of type: SCStreamOutputType
    ) {
        guard type == .audio, sampleBuffer.isValid else { return }

        if resampler == nil {
            // Lazily build resampler from the first sample buffer's format.
            guard
                let fmt = CMSampleBufferGetFormatDescription(sampleBuffer),
                let asbd = CMAudioFormatDescriptionGetStreamBasicDescription(fmt)?.pointee
            else { return }
            resampler = Resampler(
                inputSampleRate: asbd.mSampleRate,
                inputChannels: AVAudioChannelCount(asbd.mChannelsPerFrame)
            )
            emit([
                "type": "info",
                "message": "audio format: sr=\(asbd.mSampleRate) ch=\(asbd.mChannelsPerFrame)"
            ])
        }

        guard let pcm = resampler?.convert(sampleBuffer), !pcm.isEmpty else { return }
        writeQueue.async { [stdout] in
            stdout.write(pcm)
        }
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        emit([
            "type": "error",
            "kind": classifyError(error),
            "message": (error as NSError).localizedDescription
        ])
        exit(2)
    }
}

/// Map an arbitrary error to one of the wire-protocol error kinds. Apple's
/// exact error codes for "user declined Screen Recording" have varied across
/// macOS versions, so we accept several signals.
func classifyError(_ error: Error) -> String {
    let ns = error as NSError
    // Known historical codes for user-declined / permission denied.
    let permissionCodes: Set<Int> = [-3801, -3812, 3, -16981]
    let permissionDomains: Set<String> = [
        "SCStreamErrorDomain",
        "com.apple.ScreenCaptureKit",
        "com.apple.coregraphics",
    ]
    if permissionDomains.contains(ns.domain) && permissionCodes.contains(ns.code) {
        return "permission_denied"
    }
    let msg = ns.localizedDescription.lowercased()
    if msg.contains("permission") || msg.contains("declined") || msg.contains("not authorized") {
        return "permission_denied"
    }
    return "stream_error"
}

// ---------------------------------------------------------------------------
// Capture lifecycle
// ---------------------------------------------------------------------------

func startCapture() async {
    // Proactive permission preflight. CGPreflightScreenCaptureAccess returns
    // false if our process has not been granted Screen Recording. Calling
    // CGRequestScreenCaptureAccess triggers the system prompt deterministically
    // so we don't have to rely on SCShareableContent's implicit prompt.
    if !CGPreflightScreenCaptureAccess() {
        emit(["type": "info", "message": "requesting screen recording access"])
        let granted = CGRequestScreenCaptureAccess()
        if !granted {
            fatalEmit(
                "permission_denied",
                "Screen Recording is not granted. Open System Settings → Privacy & Security → Screen Recording."
            )
        }
    }

    // SCShareableContent fires the prompt as a fallback if preflight missed.
    let content: SCShareableContent
    do {
        content = try await SCShareableContent.excludingDesktopWindows(
            false, onScreenWindowsOnly: true
        )
    } catch {
        let kind = classifyError(error)
        if kind == "permission_denied" {
            fatalEmit("permission_denied", (error as NSError).localizedDescription)
        }
        fatalEmit("init", (error as NSError).localizedDescription)
    }

    guard let display = content.displays.first else {
        fatalEmit("init", "no display available")
    }

    // We need a content filter, even though we only care about audio.
    // Excluding the current process avoids capturing our own output if any.
    let pid = ProcessInfo.processInfo.processIdentifier
    let excluded = content.applications.filter { $0.processID == pid }
    let filter = SCContentFilter(
        display: display, excludingApplications: excluded, exceptingWindows: []
    )

    let cfg = SCStreamConfiguration()
    cfg.capturesAudio = true
    cfg.excludesCurrentProcessAudio = true
    cfg.sampleRate = 48_000
    cfg.channelCount = 2
    // Minimal video config — we don't read video frames, but SCStream still
    // requires a sane configuration.
    cfg.width = 2
    cfg.height = 2
    cfg.minimumFrameInterval = CMTime(value: 1, timescale: 1)
    cfg.queueDepth = 6

    let tap = AudioTap()
    let stream = SCStream(filter: filter, configuration: cfg, delegate: tap)
    do {
        try stream.addStreamOutput(tap, type: .audio, sampleHandlerQueue: .global(qos: .userInitiated))
        try await stream.startCapture()
        emit(["type": "ready"])
    } catch {
        let ns = error as NSError
        fatalEmit("start_failed", ns.localizedDescription)
    }

    // Hold open until stdin closes or "stop" arrives.
    let stdin = FileHandle.standardInput
    stdin.readabilityHandler = { handle in
        let data = handle.availableData
        if data.isEmpty {
            // EOF
            Task { try? await stream.stopCapture(); exit(0) }
            return
        }
        if let s = String(data: data, encoding: .utf8), s.lowercased().contains("stop") {
            Task { try? await stream.stopCapture(); exit(0) }
        }
    }

    // Park the main thread.
    dispatchMain()
}

// ---------------------------------------------------------------------------
// Entry
// ---------------------------------------------------------------------------

signal(SIGTERM) { _ in exit(0) }
signal(SIGINT) { _ in exit(0) }

Task { await startCapture() }
RunLoop.main.run()
