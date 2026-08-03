---
name: youtube-script-digest
description: >
  Extracts a YouTube video's real caption/subtitle track (never audio
  transcription) into a single markdown file containing the original script,
  a Korean translation (skipped only if the video is already genuinely
  Korean), and a Korean summary of the key points. Use this whenever the user
  gives a YouTube link (youtube.com or youtu.be) and asks to save/extract the
  script, transcript, subtitles, or captions, or asks for a Korean
  translation or summary of a YouTube video — e.g. "이 유튜브 영상 스크립트 좀
  뽑아줘", "이거 한글 번역이랑 요약해서 md로 만들어줘", "get me the transcript of
  this youtube video and translate it to Korean", "유튜브 자막 정리해줘". Also use
  it proactively any time a bare youtube.com/youtu.be URL appears alongside a
  request to summarize, translate, or write up its content, even if the user
  doesn't say "script" or "transcript" explicitly.
---

# YouTube Script Digest

Turn a YouTube link into one markdown file: original script + Korean
translation + Korean summary.

## Why the design is this way

This skill only ever reads YouTube's own caption tracks (manual or
auto-generated) via `yt-dlp`. It deliberately does **not** download audio and
run speech-to-text as a fallback — if a video has no captions at all, that's
a hard failure, not something to work around. Don't try to route around this
by fetching the audio yourself.

The other reason captions (not the raw JSON caption files) end up rewritten
rather than pasted verbatim: YouTube's auto-generated captions have no
punctuation and scroll with overlapping duplicate text. A translation of that
raw mess reads badly. Reflowing it into real sentences first, then
translating, produces something an actual person would want to read.

## Step 1 — Run the extraction script

```
python3 <skill-dir>/scripts/fetch_transcript.py "<youtube-url>"
```

This prints one JSON object to stdout and cleans up its own temp files
regardless of outcome. Two shapes:

**Success:**
```json
{
  "ok": true,
  "title": "...",
  "channel": "...",
  "video_id": "...",
  "url": "https://www.youtube.com/watch?v=...",
  "source_lang": "en",
  "is_korean": false,
  "manual": true,
  "transcript": "raw caption text, cues joined into a flat string, no timestamps"
}
```
- `is_korean: true` means the caption track it picked is already genuinely
  Korean (real manual Korean captions, or the video's own original spoken
  language resolved to Korean) — not YouTube's auto-translated Korean track.
  Translation is skipped in this case.
- `manual` tells you whether these were human/creator-provided captions
  (higher quality) or auto-generated (rougher, no punctuation, possibly
  ASR errors) — mention this in the output so the reader knows how much to
  trust the wording.

**Failure:**
```json
{"ok": false, "error": "이 영상에는 자막이 전혀 없어..."}
```
When this happens, stop here. Tell the user plainly that the video has no
captions (manual or auto-generated) and that this skill doesn't fall back to
transcribing audio. Do not attempt an alternative extraction method.

## Step 2 — Turn the raw transcript into a readable script

The `transcript` field is one long run of caption text with no paragraph
breaks or reliable punctuation (especially when `manual` is false). Before
using it, reflow it into normal prose: add sentence punctuation and break it
into paragraphs at natural topic/pause boundaries, without changing or
inventing content. This is the "original script" section.

## Step 3 — Translate to Korean (skip only if `is_korean` is true)

If `is_korean` is false, produce a natural, coherent Korean translation of
the full script — translate meaning and register, not caption-by-caption.
Keep it complete (don't summarize here; that's step 4).

If `is_korean` is true, don't translate — just note plainly in that section
that the video's own script is already Korean, so no translation was made.

## Step 4 — Summarize key points in Korean

Write a concise Korean summary of the video's key content as a bulleted
list (aim for the actual main points, not a padded list — could be 3 bullets
or 15 depending on the video). Always in Korean, regardless of `is_korean`.

## Step 5 — Assemble the markdown file

Use this structure:

```markdown
# [영상 제목]

- **채널**: [channel]
- **URL**: [url]
- **video_id**: [video_id]
- **자막 출처**: [수동 자막 / 자동 생성 자막] ([source_lang])

## 원본 스크립트

[reflowed original-language script from Step 2]

## 한글 번역

[Step 3 output, or the "already Korean" note]

## 핵심 요약

[Step 4 bullet list]
```

Save it as a single `.md` file. Name it from the sanitized video title plus
the video id (e.g. `영상-제목-dQw4w9WgXcQ.md`) so it doesn't collide with
other digests. Save to the current working directory unless the user names a
different location.

## Notes

- `yt-dlp` and network access to YouTube are required — if `yt-dlp` isn't
  installed, `pip install yt-dlp` first (no API key needed).
- If the user's environment blocks outbound access to youtube.com /
  googlevideo.com, the script will fail on the info-fetch step with a
  network error — that's an environment/network-policy issue, not a bug in
  this skill.
