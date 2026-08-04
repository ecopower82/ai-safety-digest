#!/usr/bin/env python3
"""
Fetch a YouTube video's caption track (never audio) and print a single JSON
object describing what was found, so the calling assistant can decide how to
build the markdown digest.

Selection order (decided deliberately, see SKILL.md for the reasoning):
  1. Manual (human/creator-provided) Korean captions -> use as-is, no translation.
  2. Any other manual-caption language -> use as the "original script" source,
     translation will be needed.
  3. Automatic captions in the video's original spoken language (yt-dlp's
     special "orig" language tag resolves this correctly instead of picking
     one of the many auto-*translated* tracks) -> used as the source; if that
     resolved language happens to be Korean, no translation is needed either.
  4. Nothing available at all (no manual subs, no automatic captions) -> fail
     loudly. This script deliberately does NOT fall back to downloading audio
     and transcribing it — that was an explicit product decision, not an
     oversight.

Never treat automatic_captions['ko'] as "the video already has Korean" when
the video isn't actually Korean: that track is YouTube's own machine
translation (from whatever ASR language), not a human Korean caption, and
silently using it would defeat the point of asking Claude to translate.
"""
import argparse
import glob
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def fail(message):
    print(json.dumps({"ok": False, "error": message}, ensure_ascii=False))
    sys.exit(1)


def get_info(url):
    p = run(["yt-dlp", "--skip-download", "--dump-single-json", "--no-warnings", url])
    if p.returncode != 0:
        fail(f"영상 정보를 가져오지 못했습니다 (URL을 확인해 주세요): {p.stderr.strip()[-1500:]}")
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError:
        fail("yt-dlp 출력이 JSON으로 파싱되지 않았습니다.")


def korean_key(lang_dict):
    for k in lang_dict:
        if k.lower() in ("ko", "ko-kr"):
            return k
    return None


def download_sub(webpage_url, workdir, manual, lang_tag):
    """Downloads exactly one caption track matching lang_tag and returns its path (or None)."""
    outtmpl = os.path.join(workdir, "%(id)s")
    cmd = [
        "yt-dlp", "--skip-download", "--no-warnings",
        "--sub-format", "vtt/srt/best",
        "--sub-langs", lang_tag,
        "-o", outtmpl,
    ]
    cmd.append("--write-subs" if manual else "--write-auto-subs")
    cmd.append(webpage_url)
    run(cmd)
    files = sorted(glob.glob(os.path.join(workdir, "*.vtt")) + glob.glob(os.path.join(workdir, "*.srt")))
    return files[0] if files else None


def parse_caption_cues(path):
    """Turns a .vtt or .srt file into a list of per-cue text strings (tags/timestamps stripped)."""
    cues = []
    current = []
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    for raw in lines:
        line = raw.strip()
        if not line:
            if current:
                cues.append(" ".join(current))
                current = []
            continue
        upper = line.upper()
        if upper.startswith("WEBVTT") or upper.startswith("KIND:") or upper.startswith("LANGUAGE:") or upper.startswith("NOTE"):
            continue
        if "-->" in line:
            continue
        if re.fullmatch(r"\d+", line):
            continue
        clean = re.sub(r"<[^>]+>", "", line)
        clean = html.unescape(clean).strip()
        if clean:
            current.append(clean)
    if current:
        cues.append(" ".join(current))
    return cues


def dedupe_rolling_captions(cues):
    """
    YouTube's auto-generated .vtt captions scroll: each cue often repeats the
    tail of the previous cue plus a few new words ("roll-up" style). This
    merges cues by only appending the words that are genuinely new, using a
    longest-suffix/prefix match against what's already been collected.
    """
    words = []
    for cue_text in cues:
        cue_words = cue_text.split()
        if not cue_words:
            continue
        max_overlap = min(len(words), len(cue_words))
        overlap = 0
        for k in range(max_overlap, 0, -1):
            if words[-k:] == cue_words[:k]:
                overlap = k
                break
        words.extend(cue_words[overlap:])
    return " ".join(words)


def caption_file_to_text(path):
    return dedupe_rolling_captions(parse_caption_cues(path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="YouTube video URL")
    args = parser.parse_args()

    workdir = tempfile.mkdtemp(prefix="ytscript_")
    try:
        info = get_info(args.url)
        title = info.get("title") or ""
        uploader = info.get("uploader") or info.get("channel") or ""
        video_id = info.get("id") or ""
        webpage_url = info.get("webpage_url") or args.url
        manual = info.get("subtitles") or {}
        auto = info.get("automatic_captions") or {}

        base = {
            "ok": True,
            "title": title,
            "channel": uploader,
            "video_id": video_id,
            "url": webpage_url,
        }

        # 1. Manual Korean captions.
        ko_key = korean_key(manual)
        if ko_key:
            path = download_sub(webpage_url, workdir, True, ko_key)
            if path:
                base.update({
                    "source_lang": ko_key, "is_korean": True, "manual": True,
                    "transcript": caption_file_to_text(path),
                })
                print(json.dumps(base, ensure_ascii=False))
                return

        # 2. Any other manual-language captions (pick deterministically).
        if manual:
            lang = sorted(manual.keys())[0]
            path = download_sub(webpage_url, workdir, True, lang)
            if path:
                base.update({
                    "source_lang": lang, "is_korean": lang.lower() in ("ko", "ko-kr"),
                    "manual": True, "transcript": caption_file_to_text(path),
                })
                print(json.dumps(base, ensure_ascii=False))
                return

        # 3. Automatic captions in the original spoken language ("orig").
        if auto:
            path = download_sub(webpage_url, workdir, False, "orig")
            if path:
                fname = os.path.basename(path)
                m = re.match(re.escape(video_id) + r"\.([A-Za-z0-9_-]+)\.", fname)
                lang = m.group(1) if m else "unknown"
                base.update({
                    "source_lang": lang, "is_korean": lang.lower() in ("ko", "ko-kr"),
                    "manual": False, "transcript": caption_file_to_text(path),
                })
                print(json.dumps(base, ensure_ascii=False))
                return

        fail("이 영상에는 자막(수동 등록 또는 자동 생성)이 전혀 없어 스크립트를 추출할 수 없습니다. "
             "음성 인식(STT)으로 대체하지 않습니다.")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    main()
