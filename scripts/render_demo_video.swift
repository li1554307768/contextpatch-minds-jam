#!/usr/bin/env swift

import AppKit
import AVFoundation
import CoreGraphics
import CoreVideo
import Foundation

struct Manifest: Decodable {
    let schemaVersion: String
    let brand: String
    let datasetLabel: String
    let liveEvidenceLabel: String
    let width: Int
    let height: Int
    let fps: Int32
    let duration: Double
    let scenes: [Scene]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case brand
        case datasetLabel = "dataset_label"
        case liveEvidenceLabel = "live_evidence_label"
        case width, height, fps, duration, scenes
    }
}

struct Scene: Decodable {
    let duration: Double
    let style: String
    let eyebrow: String
    let title: String
    let subtitle: String
}

enum RenderError: Error, CustomStringConvertible {
    case usage
    case invalidManifest(String)
    case pixelBuffer(String)
    case writer(String)
    case missingTrack(String)
    case export(String)

    var description: String {
        switch self {
        case .usage:
            return "Usage: render_demo_video.swift MANIFEST NARRATION SILENT_MOV FINAL_MP4"
        case .invalidManifest(let message), .pixelBuffer(let message), .writer(let message),
             .missingTrack(let message), .export(let message):
            return message
        }
    }
}

let backgroundTop = NSColor(calibratedRed: 0.055, green: 0.047, blue: 0.105, alpha: 1)
let backgroundBottom = NSColor(calibratedRed: 0.102, green: 0.071, blue: 0.157, alpha: 1)
let surface = NSColor(calibratedRed: 0.105, green: 0.094, blue: 0.165, alpha: 1)
let surfaceRaised = NSColor(calibratedRed: 0.143, green: 0.122, blue: 0.215, alpha: 1)
let border = NSColor(calibratedRed: 0.294, green: 0.259, blue: 0.404, alpha: 1)
let ivory = NSColor(calibratedRed: 0.975, green: 0.961, blue: 0.925, alpha: 1)
let muted = NSColor(calibratedRed: 0.719, green: 0.690, blue: 0.765, alpha: 1)
let pink = NSColor(calibratedRed: 0.957, green: 0.447, blue: 0.714, alpha: 1)
let violet = NSColor(calibratedRed: 0.655, green: 0.545, blue: 0.980, alpha: 1)
let teal = NSColor(calibratedRed: 0.176, green: 0.831, blue: 0.749, alpha: 1)
let amber = NSColor(calibratedRed: 0.984, green: 0.749, blue: 0.141, alpha: 1)
let red = NSColor(calibratedRed: 0.984, green: 0.353, blue: 0.420, alpha: 1)

func paragraph(alignment: NSTextAlignment = .left, lineBreak: NSLineBreakMode = .byWordWrapping) -> NSMutableParagraphStyle {
    let style = NSMutableParagraphStyle()
    style.alignment = alignment
    style.lineBreakMode = lineBreak
    style.lineSpacing = 4
    return style
}

func drawText(
    _ text: String,
    in rect: NSRect,
    size: CGFloat,
    color: NSColor = ivory,
    weight: NSFont.Weight = .regular,
    alignment: NSTextAlignment = .left,
    lineBreak: NSLineBreakMode = .byWordWrapping
) {
    let attributes: [NSAttributedString.Key: Any] = [
        .font: NSFont.systemFont(ofSize: size, weight: weight),
        .foregroundColor: color,
        .paragraphStyle: paragraph(alignment: alignment, lineBreak: lineBreak),
    ]
    (text as NSString).draw(in: rect, withAttributes: attributes)
}

func roundedRect(
    _ rect: NSRect,
    radius: CGFloat,
    fill: NSColor,
    stroke: NSColor? = nil,
    width: CGFloat = 1
) {
    let path = NSBezierPath(roundedRect: rect, xRadius: radius, yRadius: radius)
    fill.setFill()
    path.fill()
    if let stroke {
        stroke.setStroke()
        path.lineWidth = width
        path.stroke()
    }
}

func pill(_ rect: NSRect, text: String, color: NSColor, fillAlpha: CGFloat = 0.13) {
    roundedRect(rect, radius: rect.height / 2, fill: color.withAlphaComponent(fillAlpha), stroke: color, width: 2)
    drawText(text, in: NSRect(x: rect.minX + 12, y: rect.minY + 11, width: rect.width - 24, height: rect.height - 18), size: 18, color: color, weight: .bold, alignment: .center, lineBreak: .byTruncatingTail)
}

func card(_ rect: NSRect, title: String, body: String, accent: NSColor = violet, bodySize: CGFloat = 25) {
    roundedRect(rect, radius: 24, fill: surfaceRaised, stroke: border, width: 2)
    roundedRect(NSRect(x: rect.minX + 24, y: rect.minY + 24, width: 9, height: 46), radius: 4, fill: accent)
    drawText(title, in: NSRect(x: rect.minX + 54, y: rect.minY + 22, width: rect.width - 78, height: 54), size: 27, color: accent, weight: .semibold)
    drawText(body, in: NSRect(x: rect.minX + 30, y: rect.minY + 91, width: rect.width - 60, height: rect.height - 115), size: bodySize, color: ivory)
}

func line(from start: NSPoint, to end: NSPoint, color: NSColor, width: CGFloat = 4, dashed: Bool = false) {
    let path = NSBezierPath()
    path.move(to: start)
    path.line(to: end)
    path.lineWidth = width
    if dashed { path.setLineDash([12, 10], count: 2, phase: 0) }
    color.setStroke()
    path.stroke()
}

func arrow(from start: NSPoint, to end: NSPoint, color: NSColor) {
    line(from: start, to: end, color: color, width: 5)
    let angle = atan2(end.y - start.y, end.x - start.x)
    let wing: CGFloat = 17
    let left = NSPoint(x: end.x - wing * cos(angle - .pi / 6), y: end.y - wing * sin(angle - .pi / 6))
    let right = NSPoint(x: end.x - wing * cos(angle + .pi / 6), y: end.y - wing * sin(angle + .pi / 6))
    let head = NSBezierPath()
    head.move(to: end)
    head.line(to: left)
    head.line(to: right)
    head.close()
    color.setFill()
    head.fill()
}

func patchMark(center: NSPoint, scale: CGFloat = 1) {
    let size = 70 * scale
    let rect = NSRect(x: center.x - size / 2, y: center.y - size / 2, width: size, height: size)
    roundedRect(rect, radius: 18 * scale, fill: violet, stroke: pink, width: 3 * scale)
    roundedRect(NSRect(x: rect.minX + 17 * scale, y: rect.minY + 17 * scale, width: 36 * scale, height: 36 * scale), radius: 9 * scale, fill: backgroundTop)
    for offset in stride(from: CGFloat(8), through: size - 8, by: 12 * scale) {
        let dot = NSRect(x: rect.minX + offset - 2 * scale, y: rect.minY - 3 * scale, width: 4 * scale, height: 6 * scale)
        roundedRect(dot, radius: 2 * scale, fill: pink)
    }
}

func drawHeader(scene: Scene, manifest: Manifest, index: Int) {
    patchMark(center: NSPoint(x: 78, y: 67), scale: 0.62)
    drawText(manifest.brand.uppercased(), in: NSRect(x: 124, y: 42, width: 400, height: 42), size: 23, color: ivory, weight: .bold)
    pill(NSRect(x: 1510, y: 40, width: 330, height: 45), text: "SYNTHETIC DEMO", color: teal)
    drawText(scene.eyebrow, in: NSRect(x: 80, y: 112, width: 1500, height: 36), size: 21, color: pink, weight: .bold)
    drawText(scene.title, in: NSRect(x: 80, y: 153, width: 1690, height: 75), size: 48, color: ivory, weight: .bold)
    let progressWidth = 1760 * CGFloat(index + 1) / CGFloat(manifest.scenes.count)
    roundedRect(NSRect(x: 80, y: 1017, width: 1760, height: 5), radius: 2.5, fill: border)
    roundedRect(NSRect(x: 80, y: 1017, width: progressWidth, height: 5), radius: 2.5, fill: pink)
}

func drawSubtitle(_ text: String) {
    roundedRect(NSRect(x: 80, y: 833, width: 1760, height: 158), radius: 26, fill: NSColor(calibratedWhite: 0.035, alpha: 0.86), stroke: border, width: 2)
    drawText("NARRATION", in: NSRect(x: 116, y: 858, width: 200, height: 30), size: 17, color: teal, weight: .bold)
    drawText(text, in: NSRect(x: 116, y: 891, width: 1688, height: 80), size: 29, color: ivory, weight: .medium, alignment: .center)
}

func drawTitleScene() {
    patchMark(center: NSPoint(x: 960, y: 397), scale: 1.7)
    drawText("PATCH FACTS. NOT FEEDS.", in: NSRect(x: 250, y: 535, width: 1420, height: 86), size: 63, color: ivory, weight: .heavy, alignment: .center)
    drawText("Find stale copies → recall approved policy → review bounded corrections", in: NSRect(x: 300, y: 626, width: 1320, height: 55), size: 28, color: muted, weight: .medium, alignment: .center)
    pill(NSRect(x: 305, y: 714, width: 390, height: 55), text: "PERSISTENT POLICY", color: violet)
    pill(NSRect(x: 765, y: 714, width: 390, height: 55), text: "HUMAN REVIEW", color: teal)
    pill(NSRect(x: 1225, y: 714, width: 390, height: 55), text: "NO AUTO-PUBLISH", color: amber)
}

func drawBranchScene() {
    card(NSRect(x: 100, y: 300, width: 550, height: 390), title: "SOURCE LAUNCH NOTE", body: "LAUNCH: SEP 30\n\nSix live sessions\n$149\n12-month recording access", accent: ivory, bodySize: 29)
    let platforms = [("X", 270.0), ("LINKEDIN", 455.0), ("YOUTUBE", 640.0)]
    for (platform, y) in platforms {
        let rect = NSRect(x: 1130, y: y, width: 620, height: 130)
        roundedRect(rect, radius: 22, fill: surfaceRaised, stroke: border, width: 2)
        drawText(platform, in: NSRect(x: rect.minX + 30, y: rect.minY + 23, width: 210, height: 40), size: 26, color: violet, weight: .bold)
        drawText("Contains 4 tracked facts", in: NSRect(x: rect.minX + 30, y: rect.minY + 70, width: 350, height: 36), size: 22, color: muted)
        pill(NSRect(x: rect.maxX - 190, y: rect.minY + 40, width: 155, height: 47), text: "STALE", color: red)
        arrow(from: NSPoint(x: 680, y: 492), to: NSPoint(x: 1100, y: rect.midY), color: pink)
    }
}

func drawTruthScene() {
    drawText("LAUNCH_DATE", in: NSRect(x: 130, y: 318, width: 280, height: 46), size: 27, color: muted, weight: .bold)
    roundedRect(NSRect(x: 390, y: 285, width: 500, height: 118), radius: 24, fill: red.withAlphaComponent(0.10), stroke: red, width: 3)
    drawText("SEPTEMBER 30", in: NSRect(x: 430, y: 322, width: 420, height: 52), size: 34, color: red, weight: .heavy, alignment: .center)
    arrow(from: NSPoint(x: 920, y: 344), to: NSPoint(x: 1030, y: 344), color: violet)
    roundedRect(NSRect(x: 1060, y: 285, width: 650, height: 118), radius: 24, fill: violet.withAlphaComponent(0.12), stroke: violet, width: 3)
    drawText("OCTOBER 7", in: NSRect(x: 1100, y: 322, width: 570, height: 52), size: 34, color: violet, weight: .heavy, alignment: .center)

    drawText("UNCHANGED CONTEXT", in: NSRect(x: 120, y: 500, width: 500, height: 42), size: 24, color: teal, weight: .bold)
    pill(NSRect(x: 120, y: 565, width: 480, height: 68), text: "$149 • UNCHANGED", color: teal)
    pill(NSRect(x: 720, y: 565, width: 480, height: 68), text: "SIX SESSIONS • UNCHANGED", color: teal)
    pill(NSRect(x: 1320, y: 565, width: 480, height: 68), text: "12-MONTH ACCESS • UNCHANGED", color: teal)
    pill(NSRect(x: 550, y: 706, width: 820, height: 58), text: "VISIBLE CORRECTION • NEVER SILENTLY EDIT", color: amber)
}

func drawScanScene() {
    pill(NSRect(x: 100, y: 300, width: 430, height: 64), text: "launch_date", color: pink)
    roundedRect(NSRect(x: 100, y: 410, width: 430, height: 120), radius: 22, fill: surfaceRaised, stroke: violet, width: 2)
    drawText("DECLARED KEY MATCH", in: NSRect(x: 130, y: 444, width: 370, height: 38), size: 22, color: violet, weight: .bold, alignment: .center)
    drawText("fact_keys contains launch_date", in: NSRect(x: 130, y: 486, width: 370, height: 32), size: 19, color: muted, alignment: .center)
    roundedRect(NSRect(x: 100, y: 570, width: 430, height: 120), radius: 22, fill: surfaceRaised, stroke: pink, width: 2)
    drawText("EXACT OLD-DATE MATCH", in: NSRect(x: 130, y: 604, width: 370, height: 38), size: 22, color: pink, weight: .bold, alignment: .center)
    drawText("“September 30”", in: NSRect(x: 130, y: 646, width: 370, height: 32), size: 20, color: muted, alignment: .center)
    roundedRect(NSRect(x: 690, y: 340, width: 360, height: 300), radius: 44, fill: violet.withAlphaComponent(0.15), stroke: violet, width: 3)
    drawText("LOCAL", in: NSRect(x: 730, y: 402, width: 280, height: 42), size: 27, color: muted, weight: .bold, alignment: .center)
    drawText("IMPACT\nSCAN", in: NSRect(x: 730, y: 463, width: 280, height: 110), size: 42, color: ivory, weight: .heavy, alignment: .center)
    drawText("0 model calls", in: NSRect(x: 730, y: 587, width: 280, height: 36), size: 22, color: teal, weight: .bold, alignment: .center)
    let variants = ["X • AFFECTED", "LINKEDIN • AFFECTED", "YOUTUBE • AFFECTED"]
    for (index, label) in variants.enumerated() {
        let y = 310 + CGFloat(index) * 145
        roundedRect(NSRect(x: 1210, y: y, width: 550, height: 92), radius: 20, fill: surfaceRaised, stroke: teal, width: 2)
        drawText(label, in: NSRect(x: 1240, y: y + 29, width: 490, height: 38), size: 24, color: teal, weight: .bold, alignment: .center)
        arrow(from: NSPoint(x: 1070, y: 490), to: NSPoint(x: 1180, y: y + 46), color: teal)
    }
    pill(NSRect(x: 1195, y: 728, width: 575, height: 54), text: "BLOCKED UNTIL FACT APPROVAL", color: amber)
}

func drawMemoryScene(liveLabel: String) {
    card(NSRect(x: 100, y: 298, width: 570, height: 390), title: "LOCAL + HUMAN", body: "Approved date change\nSep 30 → Oct 7\n\nPublic correction principle\nNever silently edit", accent: teal, bodySize: 27)
    roundedRect(NSRect(x: 755, y: 385, width: 410, height: 210), radius: 28, fill: pink.withAlphaComponent(0.12), stroke: pink, width: 3)
    drawText("AUTHORIZED REQUEST", in: NSRect(x: 790, y: 420, width: 340, height: 42), size: 24, color: pink, weight: .bold, alignment: .center)
    drawText("natural wording\nmemory key\napproved principle", in: NSRect(x: 805, y: 475, width: 310, height: 98), size: 23, color: ivory, alignment: .center)
    arrow(from: NSPoint(x: 690, y: 490), to: NSPoint(x: 735, y: 490), color: pink)
    arrow(from: NSPoint(x: 1185, y: 490), to: NSPoint(x: 1230, y: 490), color: pink)
    card(NSRect(x: 1250, y: 298, width: 570, height: 390), title: "MINDS", body: "Remember:\nvisible public correction\nname both dates\npreserve context\nnever silently edit", accent: violet, bodySize: 25)
    pill(NSRect(x: 590, y: 730, width: 740, height: 54), text: liveLabel, color: amber)
}

func drawSessionsScene(liveLabel: String) {
    card(NSRect(x: 110, y: 290, width: 690, height: 390), title: "SESSION A • STORE", body: "Creator-approved policy\n\nName old + new date\nPreserve platform context\nNever silently edit", accent: teal, bodySize: 28)
    card(NSRect(x: 1120, y: 290, width: 690, height: 390), title: "SESSION B • RECALL", body: "Date change + 3 originals\n\nPrior policy omitted\nReturn 3 patches + WHY NOW\nRemain review-only", accent: violet, bodySize: 27)
    arrow(from: NSPoint(x: 820, y: 488), to: NSPoint(x: 1100, y: 488), color: pink)
    pill(NSRect(x: 770, y: 452, width: 360, height: 72), text: "OPAQUE MEMORY KEY", color: pink)
    pill(NSRect(x: 590, y: 730, width: 740, height: 54), text: liveLabel, color: amber)
}

func drawPatchesScene() {
    let columns: [(String, String, NSColor)] = [
        ("X", "Correction:\nOpens Oct 7, not Sep 30.\nSix sessions remain $149.\n12-month access remains.", pink),
        ("LINKEDIN", "Correction to my launch:\nNow begins Oct 7,\nnot Sep 30. The $149\ncohort context is unchanged.", violet),
        ("YOUTUBE", "Description update:\nOpens Oct 7, not Sep 30.\nSix sessions, $149, and\n12-month access remain.", teal),
    ]
    for (index, column) in columns.enumerated() {
        card(NSRect(x: 100 + CGFloat(index) * 590, y: 280, width: 540, height: 445), title: column.0, body: column.1, accent: column.2, bodySize: 27)
        pill(NSRect(x: 175 + CGFloat(index) * 590, y: 742, width: 390, height: 50), text: "PENDING REVIEW", color: amber)
    }
}

func drawReviewScene() {
    card(NSRect(x: 100, y: 285, width: 780, height: 455), title: "PATCH DIFF • LINKEDIN", body: "− begins September 30\n+ now begins October 7, not September 30\n\nUNCHANGED:\n$149 • six sessions • 12-month access", accent: pink, bodySize: 29)
    roundedRect(NSRect(x: 970, y: 285, width: 850, height: 230), radius: 24, fill: surfaceRaised, stroke: border, width: 2)
    drawText("WHY NOW", in: NSRect(x: 1010, y: 320, width: 250, height: 42), size: 24, color: amber, weight: .bold)
    drawText("Three published variants still name September 30. The approved policy requires a visible correction, not a silent edit.", in: NSRect(x: 1010, y: 375, width: 770, height: 100), size: 28, color: ivory)
    pill(NSRect(x: 1010, y: 570, width: 340, height: 70), text: "APPROVE DRAFT", color: teal)
    pill(NSRect(x: 1430, y: 570, width: 340, height: 70), text: "REJECT", color: red)
    drawText("No publish action exists", in: NSRect(x: 1060, y: 675, width: 660, height: 42), size: 24, color: muted, weight: .bold, alignment: .center)
}

func drawPauseScene() {
    roundedRect(NSRect(x: 120, y: 310, width: 710, height: 360), radius: 40, fill: amber.withAlphaComponent(0.11), stroke: amber, width: 3)
    drawText("PAUSE", in: NSRect(x: 170, y: 365, width: 610, height: 60), size: 47, color: ivory, weight: .heavy, alignment: .center)
    roundedRect(NSRect(x: 255, y: 460, width: 440, height: 125), radius: 62, fill: amber)
    let knob = NSBezierPath(ovalIn: NSRect(x: 575, y: 475, width: 95, height: 95))
    ivory.setFill()
    knob.fill()
    drawText("ON", in: NSRect(x: 315, y: 497, width: 190, height: 46), size: 31, color: backgroundTop, weight: .heavy, alignment: .center)
    card(NSRect(x: 980, y: 310, width: 800, height: 360), title: "OUTBOUND CONTROLS", body: "0 new follow-ups\n0 automatic posts\nUNCERTAIN send → history check\nNo blind retry", accent: red, bodySize: 30)
    line(from: NSPoint(x: 1040, y: 370), to: NSPoint(x: 1710, y: 620), color: red, width: 10)
    line(from: NSPoint(x: 1710, y: 370), to: NSPoint(x: 1040, y: 620), color: red, width: 10)
}

func drawAuditScene() {
    let events: [(String, String, NSColor)] = [
        ("01", "LOCAL SCAN", pink),
        ("02", "HUMAN FACT APPROVAL", teal),
        ("03", "VERIFIED MINDS EXCHANGE", violet),
        ("04", "DRAFT REVIEW", amber),
    ]
    let y: CGFloat = 490
    line(from: NSPoint(x: 220, y: y), to: NSPoint(x: 1700, y: y), color: border, width: 7)
    for (index, event) in events.enumerated() {
        let x = 260 + CGFloat(index) * 460
        let circle = NSBezierPath(ovalIn: NSRect(x: x - 35, y: y - 35, width: 70, height: 70))
        event.2.setFill()
        circle.fill()
        drawText(event.0, in: NSRect(x: x - 28, y: y - 14, width: 56, height: 34), size: 20, color: backgroundTop, weight: .heavy, alignment: .center)
        roundedRect(NSRect(x: x - 165, y: 590, width: 330, height: 100), radius: 22, fill: surfaceRaised, stroke: event.2, width: 2)
        drawText(event.1, in: NSRect(x: x - 145, y: 622, width: 290, height: 46), size: 22, color: event.2, weight: .bold, alignment: .center)
    }
    pill(NSRect(x: 535, y: 286, width: 850, height: 62), text: "MOCK ≠ LIVE • APPROVED ≠ PUBLISHED", color: amber)
}

func drawCloseScene() {
    patchMark(center: NSPoint(x: 960, y: 400), scale: 1.9)
    drawText("CONTEXTPATCH", in: NSRect(x: 380, y: 548, width: 1160, height: 84), size: 72, color: ivory, weight: .heavy, alignment: .center)
    drawText("Human review. No auto-publish.", in: NSRect(x: 430, y: 650, width: 1060, height: 56), size: 32, color: teal, weight: .semibold, alignment: .center)
    pill(NSRect(x: 650, y: 738, width: 620, height: 52), text: "CONTENT REPURPOSING • TRACK 2", color: pink)
}

func drawScene(_ scene: Scene, manifest: Manifest, index: Int) {
    let bounds = NSRect(x: 0, y: 0, width: manifest.width, height: manifest.height)
    if let gradient = NSGradient(colors: [backgroundTop, backgroundBottom]) {
        gradient.draw(in: bounds, angle: -90)
    } else {
        backgroundTop.setFill()
        bounds.fill()
    }
    roundedRect(NSRect(x: 34, y: 28, width: CGFloat(manifest.width) - 68, height: CGFloat(manifest.height) - 56), radius: 34, fill: NSColor.clear, stroke: border, width: 2)
    drawHeader(scene: scene, manifest: manifest, index: index)
    switch scene.style {
    case "title": drawTitleScene()
    case "branch": drawBranchScene()
    case "truth": drawTruthScene()
    case "scan": drawScanScene()
    case "memory": drawMemoryScene(liveLabel: manifest.liveEvidenceLabel)
    case "sessions": drawSessionsScene(liveLabel: manifest.liveEvidenceLabel)
    case "patches": drawPatchesScene()
    case "review": drawReviewScene()
    case "pause": drawPauseScene()
    case "audit": drawAuditScene()
    case "close": drawCloseScene()
    default: break
    }
    drawSubtitle(scene.subtitle)
}

func pixelBuffer(scene: Scene, manifest: Manifest, index: Int) throws -> CVPixelBuffer {
    let attributes: [CFString: Any] = [
        kCVPixelBufferCGImageCompatibilityKey: true,
        kCVPixelBufferCGBitmapContextCompatibilityKey: true,
        kCVPixelBufferIOSurfacePropertiesKey: [:],
    ]
    var optionalBuffer: CVPixelBuffer?
    let status = CVPixelBufferCreate(
        kCFAllocatorDefault,
        manifest.width,
        manifest.height,
        kCVPixelFormatType_32BGRA,
        attributes as CFDictionary,
        &optionalBuffer
    )
    guard status == kCVReturnSuccess, let buffer = optionalBuffer else {
        throw RenderError.pixelBuffer("CVPixelBufferCreate failed with status \(status)")
    }
    CVPixelBufferLockBaseAddress(buffer, [])
    defer { CVPixelBufferUnlockBaseAddress(buffer, []) }
    guard let address = CVPixelBufferGetBaseAddress(buffer) else {
        throw RenderError.pixelBuffer("Pixel buffer has no base address")
    }
    let bitmapInfo = CGBitmapInfo.byteOrder32Little.rawValue | CGImageAlphaInfo.premultipliedFirst.rawValue
    guard let context = CGContext(
        data: address,
        width: manifest.width,
        height: manifest.height,
        bitsPerComponent: 8,
        bytesPerRow: CVPixelBufferGetBytesPerRow(buffer),
        space: CGColorSpaceCreateDeviceRGB(),
        bitmapInfo: bitmapInfo
    ) else {
        throw RenderError.pixelBuffer("Could not create bitmap drawing context")
    }
    // AVFoundation treats the first pixel-buffer row as the top of the frame while
    // Core Graphics starts at the lower-left. Flip once so our layout coordinates
    // and AppKit text both use a normal top-left origin in the encoded video.
    context.translateBy(x: 0, y: CGFloat(manifest.height))
    context.scaleBy(x: 1, y: -1)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(cgContext: context, flipped: true)
    drawScene(scene, manifest: manifest, index: index)
    NSGraphicsContext.current?.flushGraphics()
    NSGraphicsContext.restoreGraphicsState()
    return buffer
}

func renderSilentVideo(manifest: Manifest, outputURL: URL) throws {
    try? FileManager.default.removeItem(at: outputURL)
    let writer = try AVAssetWriter(outputURL: outputURL, fileType: .mov)
    let compression: [String: Any] = [
        AVVideoAverageBitRateKey: 5_800_000,
        AVVideoMaxKeyFrameIntervalKey: Int(manifest.fps * 2),
        AVVideoProfileLevelKey: AVVideoProfileLevelH264HighAutoLevel,
    ]
    let settings: [String: Any] = [
        AVVideoCodecKey: AVVideoCodecType.h264,
        AVVideoWidthKey: manifest.width,
        AVVideoHeightKey: manifest.height,
        AVVideoCompressionPropertiesKey: compression,
    ]
    let input = AVAssetWriterInput(mediaType: .video, outputSettings: settings)
    input.expectsMediaDataInRealTime = false
    let adaptor = AVAssetWriterInputPixelBufferAdaptor(
        assetWriterInput: input,
        sourcePixelBufferAttributes: [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
            kCVPixelBufferWidthKey as String: manifest.width,
            kCVPixelBufferHeightKey as String: manifest.height,
        ]
    )
    guard writer.canAdd(input) else {
        throw RenderError.writer("AVAssetWriter cannot add the video input")
    }
    writer.add(input)
    guard writer.startWriting() else {
        throw RenderError.writer(writer.error?.localizedDescription ?? "Writer did not start")
    }
    writer.startSession(atSourceTime: .zero)

    var frameNumber: Int64 = 0
    for (index, scene) in manifest.scenes.enumerated() {
        guard scene.duration > 0 else {
            throw RenderError.invalidManifest("Every scene duration must be positive")
        }
        let buffer = try pixelBuffer(scene: scene, manifest: manifest, index: index)
        let frameCount = Int64((scene.duration * Double(manifest.fps)).rounded())
        for _ in 0..<frameCount {
            while !input.isReadyForMoreMediaData {
                if writer.status == .failed {
                    throw RenderError.writer(writer.error?.localizedDescription ?? "Writer failed")
                }
                Thread.sleep(forTimeInterval: 0.002)
            }
            let time = CMTime(value: frameNumber, timescale: manifest.fps)
            guard adaptor.append(buffer, withPresentationTime: time) else {
                throw RenderError.writer(writer.error?.localizedDescription ?? "Could not append frame")
            }
            frameNumber += 1
        }
    }
    input.markAsFinished()
    let semaphore = DispatchSemaphore(value: 0)
    writer.finishWriting { semaphore.signal() }
    semaphore.wait()
    guard writer.status == .completed else {
        throw RenderError.writer(writer.error?.localizedDescription ?? "Writer did not complete")
    }
}

func merge(videoURL: URL, narrationURL: URL, outputURL: URL) throws {
    try? FileManager.default.removeItem(at: outputURL)
    let videoAsset = AVURLAsset(url: videoURL)
    let audioAsset = AVURLAsset(url: narrationURL)
    guard let sourceVideo = videoAsset.tracks(withMediaType: .video).first else {
        throw RenderError.missingTrack("Silent render has no video track")
    }
    guard let sourceAudio = audioAsset.tracks(withMediaType: .audio).first else {
        throw RenderError.missingTrack("Narration has no audio track")
    }
    let composition = AVMutableComposition()
    guard let videoTrack = composition.addMutableTrack(withMediaType: .video, preferredTrackID: kCMPersistentTrackID_Invalid),
          let audioTrack = composition.addMutableTrack(withMediaType: .audio, preferredTrackID: kCMPersistentTrackID_Invalid) else {
        throw RenderError.missingTrack("Could not create composition tracks")
    }
    try videoTrack.insertTimeRange(CMTimeRange(start: .zero, duration: videoAsset.duration), of: sourceVideo, at: .zero)
    let audioDuration = CMTimeMinimum(audioAsset.duration, videoAsset.duration)
    try audioTrack.insertTimeRange(CMTimeRange(start: .zero, duration: audioDuration), of: sourceAudio, at: .zero)
    guard let exporter = AVAssetExportSession(asset: composition, presetName: AVAssetExportPreset1920x1080) else {
        throw RenderError.export("Could not create 1080p export session")
    }
    exporter.outputURL = outputURL
    exporter.outputFileType = .mp4
    exporter.shouldOptimizeForNetworkUse = true
    let semaphore = DispatchSemaphore(value: 0)
    exporter.exportAsynchronously { semaphore.signal() }
    semaphore.wait()
    guard exporter.status == .completed else {
        throw RenderError.export(exporter.error?.localizedDescription ?? "Export did not complete")
    }
}

do {
    guard CommandLine.arguments.count == 5 else { throw RenderError.usage }
    let manifestURL = URL(fileURLWithPath: CommandLine.arguments[1])
    let narrationURL = URL(fileURLWithPath: CommandLine.arguments[2])
    let silentURL = URL(fileURLWithPath: CommandLine.arguments[3])
    let outputURL = URL(fileURLWithPath: CommandLine.arguments[4])
    let data = try Data(contentsOf: manifestURL)
    let manifest = try JSONDecoder().decode(Manifest.self, from: data)
    guard manifest.schemaVersion == "1.0", manifest.width == 1920, manifest.height == 1080,
          manifest.fps == 30, !manifest.scenes.isEmpty else {
        throw RenderError.invalidManifest("Manifest must be schema 1.0, 1920x1080, 30 fps and non-empty")
    }
    let summedDuration = manifest.scenes.reduce(0) { $0 + $1.duration }
    guard abs(summedDuration - manifest.duration) < 0.01,
          manifest.duration >= 105, manifest.duration <= 115 else {
        throw RenderError.invalidManifest("Manifest duration must be 105–115 seconds and match its scenes")
    }
    try renderSilentVideo(manifest: manifest, outputURL: silentURL)
    try merge(videoURL: silentURL, narrationURL: narrationURL, outputURL: outputURL)
    print("rendered=\(outputURL.path)")
} catch {
    FileHandle.standardError.write(Data("RENDER_FAIL: \(error)\n".utf8))
    exit(1)
}
