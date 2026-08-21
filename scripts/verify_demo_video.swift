#!/usr/bin/env swift

import AppKit
import AVFoundation
import CoreMedia
import Foundation

func fourCC(_ value: FourCharCode) -> String {
    let bytes: [UInt8] = [
        UInt8((value >> 24) & 0xff),
        UInt8((value >> 16) & 0xff),
        UInt8((value >> 8) & 0xff),
        UInt8(value & 0xff),
    ]
    return String(bytes: bytes, encoding: .ascii) ?? "unknown"
}

func fail(_ message: String) -> Never {
    FileHandle.standardError.write(Data("MEDIA_VERIFY_FAIL: \(message)\n".utf8))
    exit(2)
}

guard CommandLine.arguments.count >= 2 && CommandLine.arguments.count <= 4 else {
    fail("Usage: verify_demo_video.swift VIDEO_MP4 [PREVIEW_PNG] [PREVIEW_SECOND]")
}

let url = URL(fileURLWithPath: CommandLine.arguments[1])
guard FileManager.default.fileExists(atPath: url.path) else {
    fail("video file does not exist")
}

let asset = AVURLAsset(url: url)
let videoTracks = asset.tracks(withMediaType: .video)
let audioTracks = asset.tracks(withMediaType: .audio)
guard let video = videoTracks.first else { fail("missing video track") }
guard let audio = audioTracks.first else { fail("missing English narration track") }

let transformed = video.naturalSize.applying(video.preferredTransform)
let outputWidth = Int(abs(transformed.width).rounded())
let outputHeight = Int(abs(transformed.height).rounded())
let duration = asset.duration.seconds
let audioDuration = audio.timeRange.duration.seconds
let codec = video.formatDescriptions.first.map {
    fourCC(CMFormatDescriptionGetMediaSubType($0 as! CMFormatDescription))
} ?? "unknown"
let fileSize = (try? FileManager.default.attributesOfItem(atPath: url.path)[.size] as? NSNumber)?.int64Value ?? 0

print(String(format: "duration_seconds=%.3f", duration))
print(String(format: "audio_duration_seconds=%.3f", audioDuration))
print("resolution=\(outputWidth)x\(outputHeight)")
print("video_tracks=\(videoTracks.count)")
print("audio_tracks=\(audioTracks.count)")
print(String(format: "nominal_frame_rate=%.3f", video.nominalFrameRate))
print("video_codec=\(codec)")
print("file_size_bytes=\(fileSize)")

guard duration >= 105, duration <= 115 else { fail("duration must be 105–115 seconds") }
guard outputWidth == 1920, outputHeight == 1080 else { fail("resolution must be 1920x1080") }
guard videoTracks.count == 1, audioTracks.count >= 1 else { fail("expected one video track and at least one audio track") }
guard video.nominalFrameRate >= 29, video.nominalFrameRate <= 31 else { fail("frame rate must be approximately 30 fps") }
guard audioDuration >= 90, audioDuration <= duration + 0.1 else { fail("narration duration is incomplete or longer than the video") }
guard codec == "avc1" || codec == "h264" else { fail("video codec must be H.264") }
guard fileSize >= 1_000_000 else { fail("video file is unexpectedly small") }

if CommandLine.arguments.count >= 3 {
    let previewURL = URL(fileURLWithPath: CommandLine.arguments[2])
    let requestedSecond = CommandLine.arguments.count == 4
        ? (Double(CommandLine.arguments[3]) ?? duration / 2)
        : duration / 2
    let previewSecond = max(0.1, min(duration - 0.1, requestedSecond))
    let generator = AVAssetImageGenerator(asset: asset)
    generator.appliesPreferredTrackTransform = true
    generator.requestedTimeToleranceBefore = CMTime(seconds: 0.2, preferredTimescale: 600)
    generator.requestedTimeToleranceAfter = CMTime(seconds: 0.2, preferredTimescale: 600)
    var actualTime = CMTime.zero
    do {
        let frame = try generator.copyCGImage(
            at: CMTime(seconds: previewSecond, preferredTimescale: 600),
            actualTime: &actualTime
        )
        let bitmap = NSBitmapImageRep(cgImage: frame)
        guard let png = bitmap.representation(using: .png, properties: [:]) else {
            fail("could not encode preview PNG")
        }
        try FileManager.default.createDirectory(
            at: previewURL.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try png.write(to: previewURL)
        print("preview_png=\(previewURL.path)")
    } catch {
        fail("could not extract preview PNG: \(error)")
    }
}

print("MEDIA_VERIFY_OK")
