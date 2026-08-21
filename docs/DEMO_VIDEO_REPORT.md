# Demo Video Verification

Verified locally on 2026-08-20 with AVFoundation.

## Final artifact

- Path: `output/demo-video/contextpatch-demo.mp4`
- SHA-256: `0abae3b750704677c11e68e3480b1cf1bcc2140b5c91545b3d748a104109c133`
- File size: 25,599,335 bytes
- Video duration: 111.000 seconds
- Narration duration: 110.155 seconds
- Resolution: 1920×1080
- Frame rate: 30 fps
- Video codec: H.264 (`avc1`)
- Tracks: 1 video, 1 English narration audio
- English subtitles: burned into every scene

Verification command:

```bash
swift scripts/verify_demo_video.swift \
  output/demo-video/contextpatch-demo.mp4 \
  output/demo-video/preview-midpoint.png
```

Result: `MEDIA_VERIFY_OK`.

## Visual review

Preview frames from the title, single-date source-of-truth, deterministic scan, Minds boundary,
cross-session continuity, three platform patches, review and closing scenes were inspected. Text is
upright and readable at 1920×1080. Every scene carries `SYNTHETIC DEMO`; Minds continuity scenes carry
`LIVE MINDS CONTINUITY VERIFIED`. No API key, Mind UUID, email, alias, remote ID, customer or
real platform account appears.

The live label reflects separately verified, redacted Builder evidence: one principle store and two
recalls under the same Mind across three distinct conversations, with continuity matching. It does
not convert the fictional creator or content into real-user evidence.

The rendered scenario changes only `launch_date: September 30 -> October 7`. Price, session count
and recording access are explicitly shown as unchanged. X, LinkedIn and YouTube patches preserve
their existing context while making the date correction visible.

## Evidence boundary

The AVFoundation checks prove only that the local media artifact was rendered correctly. The live
Minds claim depends on the separate redacted continuity report, not on the MP4 alone. Neither the
video nor that integration proof establishes a public upload, platform correction, real user,
revenue, submission or award. The entire `output/demo-video/` directory is Git-ignored; upload is a
separate external action.
