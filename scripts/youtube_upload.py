#!/usr/bin/env python3
"""
YouTube auto-uploader for AutoClip clips.

Reads a project's clips (data/projects/<id>/metadata/clips_metadata.json),
converts each clip to a 9:16 vertical Short (blurred background) with ffmpeg,
and uploads it to YouTube with the AI-generated English title + description.

Setup (one-time)
----------------
1. Google Cloud Console -> create a project -> enable "YouTube Data API v3".
2. APIs & Services -> OAuth consent screen -> External -> add your Google
   account as a Test user.
3. Credentials -> Create OAuth client ID -> Application type "Desktop app" ->
   download the JSON as  scripts/client_secret.json
4. Install deps:
     pip install google-api-python-client google-auth-oauthlib
   (ffmpeg must be on PATH -- `brew install ffmpeg`)

Usage
-----
  python scripts/youtube_upload.py --project <PROJECT_ID> --privacy unlisted
  python scripts/youtube_upload.py --project <PROJECT_ID> --dry-run
  python scripts/youtube_upload.py --list                     # list projects

Notes
-----
* Each upload costs 1,600 API quota units. Default daily quota is 10,000, so
  you can upload ~6 clips/day unless you request a quota increase from Google.
* Already-uploaded clips are recorded in the project's output/.youtube_uploaded.json
  and skipped on re-runs, so you never double-upload or waste quota.
* YouTube titles are capped at 100 chars (auto-truncated). Vertical video <= 3 min
  + "#Shorts" is classified by YouTube as a Short.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.utils.output_profile import build_output_profile
from backend.utils.video_processor import VideoProcessor, resolve_reframe

PROJECTS_DIR = REPO_ROOT / "data" / "projects"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
CLIENT_SECRET = Path(__file__).resolve().parent / "client_secret.json"
TOKEN_FILE = Path(__file__).resolve().parent / "token.json"
YOUTUBE_TITLE_MAX = 100


def die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def list_projects() -> None:
    if not PROJECTS_DIR.exists():
        die(f"no projects dir at {PROJECTS_DIR}")
    rows = []
    for p in sorted(PROJECTS_DIR.iterdir()):
        meta = p / "metadata" / "clips_metadata.json"
        if meta.exists():
            try:
                data = json.loads(meta.read_text())
                clips = data if isinstance(data, list) else data.get("clips", [])
                rows.append((p.name, len(clips)))
            except Exception:
                rows.append((p.name, "?"))
    if not rows:
        print("No projects with clips found.")
        return
    print(f"{'PROJECT_ID':40}  CLIPS")
    for pid, n in rows:
        print(f"{pid:40}  {n}")


def load_clips(project_id: str) -> tuple[Path, list[dict]]:
    proj = PROJECTS_DIR / project_id
    meta = proj / "metadata" / "clips_metadata.json"
    if not meta.exists():
        die(f"no clips_metadata.json for project {project_id} ({meta})")
    data = json.loads(meta.read_text())
    clips = data if isinstance(data, list) else data.get("clips", [])
    if not clips:
        die(f"project {project_id} has no clips")
    return proj, clips


def find_clip_file(proj: Path, clip: dict) -> Path | None:
    clips_dir = proj / "output" / "clips"
    cid = str(clip.get("id", "")).strip()
    # clip files are named "<id>_<title>.mp4"
    if cid:
        matches = sorted(clips_dir.glob(f"{cid}_*.mp4"))
        if matches:
            return matches[0]
    # fallback: match on a slug of the title
    title = (clip.get("generated_title") or "").strip()
    for f in clips_dir.glob("*.mp4"):
        if title and title[:20] in f.name:
            return f
    return None


def make_vertical(src: Path, dst: Path) -> Path:
    """Return a validated Short, converting through the shared renderer if needed."""
    source_errors = VideoProcessor.validate_youtube_short(src)
    if not source_errors:
        print(f"    already Shorts-compatible: {src.name}")
        return src
    if any('时长' in error and '超过' in error for error in source_errors):
        die(f"{src.name} is too long for YouTube Shorts: {'; '.join(source_errors)}")

    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        cached_errors = VideoProcessor.validate_youtube_short(dst)
        if not cached_errors:
            print(f"    using validated cached Short: {dst.name}")
            return dst

    profile = build_output_profile('youtube_shorts', 'blur_pad')
    reframe = resolve_reframe(profile)
    if reframe is None:
        die("could not resolve the YouTube Shorts output profile")

    print(f"    converting -> 9:16 vertical: {dst.name}")
    if not VideoProcessor.reframe_video(src, dst, reframe):
        die(f"ffmpeg failed for {src.name}")

    output_errors = VideoProcessor.validate_youtube_short(dst)
    if output_errors:
        die(f"converted file failed Shorts validation: {'; '.join(output_errors)}")
    return dst


def get_youtube():
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError:
        die("missing deps. Run: pip install google-api-python-client google-auth-oauthlib")

    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CLIENT_SECRET.exists():
                die(f"missing {CLIENT_SECRET} -- download OAuth Desktop creds (see header).")
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_FILE.write_text(creds.to_json())
    return build("youtube", "v3", credentials=creds)


def upload(youtube, video: Path, title: str, description: str, privacy: str,
           category: str, tags: list[str]) -> str:
    from googleapiclient.http import MediaFileUpload
    body = {
        "snippet": {
            "title": title[:YOUTUBE_TITLE_MAX],
            "description": description,
            "tags": tags,
            "categoryId": category,
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(str(video), chunksize=-1, resumable=True, mimetype="video/mp4")
    req = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            print(f"    uploading... {int(status.progress() * 100)}%")
    return resp["id"]


def main() -> None:
    ap = argparse.ArgumentParser(description="Upload AutoClip clips to YouTube as Shorts.")
    ap.add_argument("--project", help="project id (folder under data/projects/)")
    ap.add_argument("--list", action="store_true", help="list projects with clips and exit")
    ap.add_argument("--privacy", default="unlisted",
                    choices=["public", "unlisted", "private"], help="default: unlisted")
    ap.add_argument("--category", default="24", help="YouTube category id (24=Entertainment, 22=People)")
    ap.add_argument("--max", type=int, default=0, help="max uploads this run (0 = all; mind the ~6/day quota)")
    ap.add_argument("--no-convert", action="store_true", help="upload as-is (no 9:16 conversion)")
    ap.add_argument("--dry-run", action="store_true", help="convert + print, but do not upload")
    args = ap.parse_args()

    if args.list or not args.project:
        list_projects()
        return

    proj, clips = load_clips(args.project)
    ledger_path = proj / "output" / ".youtube_uploaded.json"
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {}

    youtube = None if args.dry_run else get_youtube()
    uploaded = 0

    for clip in clips:
        cid = str(clip.get("id", ""))
        title = (clip.get("generated_title") or f"Clip {cid}").strip()
        desc = (clip.get("recommend_reason") or "").strip()
        description = f"{desc}\n\n#Shorts".strip()
        tags = ["Shorts", "clip"]

        if cid in ledger:
            print(f"[{cid}] already uploaded ({ledger[cid]}) -- skipping")
            continue

        src = find_clip_file(proj, clip)
        if not src:
            print(f"[{cid}] clip file not found -- skipping")
            continue

        print(f"[{cid}] {title[:70]}")
        video = src if args.no_convert else make_vertical(src, proj / "output" / "shorts" / src.name)

        if args.dry_run:
            print(f"    DRY RUN -> would upload {video.name} (privacy={args.privacy})")
            continue

        try:
            vid = upload(youtube, video, title, description, args.privacy, args.category, tags)
        except Exception as e:  # noqa: BLE001
            print(f"    upload failed: {e}")
            if "quota" in str(e).lower():
                print("    -> daily quota likely exhausted (~6 uploads/day). Try again tomorrow "
                      "or request a quota increase.")
                break
            continue

        url = f"https://youtu.be/{vid}"
        print(f"    uploaded: {url}")
        ledger[cid] = url
        ledger_path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2))
        uploaded += 1
        if args.max and uploaded >= args.max:
            print(f"reached --max {args.max}, stopping.")
            break

    print(f"\nDone. Uploaded {uploaded} clip(s). Ledger: {ledger_path}")


if __name__ == "__main__":
    main()
