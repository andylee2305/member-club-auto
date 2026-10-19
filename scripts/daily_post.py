"""Generate a fictional character's daily photo and schedule one Instagram post."""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import subprocess
import sys
import time
from contextlib import ExitStack
from datetime import date, datetime, time as clock_time, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests
from PIL import Image, ImageOps


ROOT = Path(__file__).resolve().parents[1]
REFERENCE_DIR = ROOT / "assets" / "reference"
POSTS_DIR = ROOT / "posts"
TARGET_HANDLE = "kellykellyhk3"
HONG_KONG = ZoneInfo("Asia/Hong_Kong")
BUFFER_URL = "https://api.buffer.com"
SCENES = (
    "a quiet morning in a small Hong Kong cafe, coffee by the window",
    "walking past the flower stalls at a Hong Kong street market",
    "a relaxed afternoon reading in a bright neighborhood bookshop",
    "taking a break on a shaded waterfront promenade in Hong Kong",
    "choosing fresh fruit at a neighborhood market",
    "enjoying a simple lunch at a sunny local cafe",
    "walking through an older Hong Kong street after light rain",
    "sitting by a window with a notebook on a slow weekend morning",
    "browsing a small independent flower shop",
    "waiting for a tram on a sunny Hong Kong street",
    "having a casual bakery stop after an afternoon walk",
    "looking out over Victoria Harbour from a public promenade",
    "visiting a quiet art gallery on a free afternoon",
    "walking under trees in a Hong Kong city park",
)


def target_day(value: str | None) -> date:
    if value:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError("Date must be YYYY-MM-DD")
        return parsed
    return datetime.now(HONG_KONG).date() + timedelta(days=1)


def publication_time(day: date) -> datetime:
    return datetime.combine(day, clock_time(11, 0), HONG_KONG).astimezone(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def paths(day: date) -> tuple[Path, Path]:
    return POSTS_DIR / f"{day.isoformat()}.jpg", POSTS_DIR / f"{day.isoformat()}.json"


def required_secret(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing {name}. Add it as a GitHub Actions repository secret.")
    return value


def model_candidates(env_name: str, defaults: tuple[str, ...]) -> tuple[str, ...]:
    configured = os.getenv(env_name, "").strip()
    return tuple(item.strip() for item in configured.split(",") if item.strip()) if configured else defaults


def is_model_access_error(exc: Exception) -> bool:
    return getattr(exc, "status_code", None) in (403, 404) and (
        getattr(exc, "code", None) == "model_not_found"
        or "does not have access to model" in str(exc)
    )


def graphql(api_key: str, query: str) -> dict:
    response = requests.post(
        BUFFER_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={"query": query},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        messages = "; ".join(item.get("message", "GraphQL error") for item in payload["errors"])
        raise RuntimeError(f"Buffer API: {messages}")
    return payload["data"]


def quoted(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def find_target_channel(api_key: str) -> tuple[str, dict]:
    data = graphql(api_key, "query { account { organizations { id name } } }")
    organizations = data.get("account", {}).get("organizations", [])
    matches: list[tuple[str, dict]] = []
    for org in organizations:
        channels = graphql(
            api_key,
            f'query {{ channels(input: {{ organizationId: {quoted(org["id"])} }}) '
            "{ id name displayName service type isDisconnected isLocked isQueuePaused } }",
        )["channels"]
        for channel in channels:
            name = str(channel.get("name") or "").lstrip("@").casefold()
            if name == TARGET_HANDLE:
                matches.append((org["id"], channel))
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly one @{TARGET_HANDLE} channel in this Buffer account; found {len(matches)}."
        )
    org_id, channel = matches[0]
    if str(channel.get("service", "")).casefold() != "instagram":
        raise RuntimeError(f"@{TARGET_HANDLE} is not an Instagram channel.")
    if channel.get("isDisconnected") or channel.get("isLocked") or channel.get("isQueuePaused"):
        raise RuntimeError(f"@{TARGET_HANDLE} is disconnected, locked, or its queue is paused in Buffer.")
    return org_id, channel


def preflight(day: date) -> None:
    if publication_time(day) <= datetime.now(timezone.utc):
        raise RuntimeError("11:00 Hong Kong time has passed for this date.")
    org_id, channel = find_target_channel(required_secret("BUFFER_API_KEY"))
    print(f"Verified Instagram channel @{channel['name']} (ID {channel['id']}, organization {org_id}).")


def generate_caption(client, scene: str) -> str:
    prompt = (
        "Write one Instagram caption in natural Hong Kong Traditional Chinese, first-person, "
        "for a fictional adult AI woman posting a daily lifestyle photo. "
        "The pictured scene is: " + scene + ". "
        "Use a light, warm Cantonese voice, 1-2 short sentences, maximum 90 Chinese characters. "
        "No invented specific venue, product endorsement, quote marks, markdown or hashtags. "
        "Return only the caption."
    )
    response = None
    candidates = model_candidates("OPENAI_TEXT_MODEL", ("gpt-5-mini",))
    for index, model in enumerate(candidates):
        try:
            response = client.responses.create(model=model, input=prompt, max_output_tokens=180)
            print(f"OpenAI caption model: {model}")
            break
        except Exception as exc:
            if not is_model_access_error(exc) or index == len(candidates) - 1:
                raise
    assert response is not None
    caption = response.output_text.strip().strip('"“”')
    if not caption or len(caption) > 300:
        raise RuntimeError("OpenAI returned an empty or overly long caption.")
    return f"{caption}\n\n#AI創作"


def generate_photo(client, scene: str) -> bytes:
    references = sorted(REFERENCE_DIR.glob("*.jpg"))
    if len(references) != 4:
        raise RuntimeError("Expected four JPG reference photos under assets/reference/.")
    prompt = (
        "Create a NEW photorealistic candid lifestyle photograph. The four input photos "
        "show the SAME fictional adult East Asian woman. Preserve her recognizable facial "
        "structure, eyes, smile and long dark brown hair; do not copy a source pose or background. "
        f"Scene: {scene}. Contemporary casual clothes appropriate to the setting, natural posture, "
        "believable Hong Kong details, soft available light, realistic skin texture and subtle "
        "camera imperfections. One featured person only. Compose a vertical 4:5 Instagram feed "
        "photo with the whole face clearly visible. No text, logos, watermarks, collage, "
        "exaggerated beauty retouching or obvious AI artifacts."
    )
    result = None
    candidates = model_candidates("OPENAI_IMAGE_MODEL", ("gpt-image-2.5-sunburst", "gpt-image-1.5", "gpt-image-1"))
    for index, model in enumerate(candidates):
        try:
            with ExitStack() as stack:
                images = [stack.enter_context(path.open("rb")) for path in references]
                result = client.images.edit(
                    model=model,
                    image=images,
                    prompt=prompt,
                    size="1024x1280" if model.startswith("gpt-image-2") else "1024x1536",
                    quality="high",
                    output_format="jpeg",
                )
            print(f"OpenAI image model: {model}")
            break
        except Exception as exc:
            if not is_model_access_error(exc) or index == len(candidates) - 1:
                raise
    assert result is not None
    encoded = result.data[0].b64_json
    if not encoded:
        raise RuntimeError("OpenAI did not return image data.")
    with Image.open(io.BytesIO(base64.b64decode(encoded))) as source:
        photo = ImageOps.fit(source.convert("RGB"), (1080, 1350), method=Image.Resampling.LANCZOS)
        output = io.BytesIO()
        photo.save(output, format="JPEG", quality=82, optimize=True, progressive=True)
    return output.getvalue()


def generate(day: date) -> None:
    image_path, manifest_path = paths(day)
    if image_path.exists() and manifest_path.exists():
        print(f"Reusing existing photo and caption for {day}.")
        return
    if image_path.exists() != manifest_path.exists():
        raise RuntimeError("Photo/manifest pair is incomplete; inspect it before retrying.")
    from openai import OpenAI

    client = OpenAI(api_key=required_secret("OPENAI_API_KEY"))
    scene = SCENES[day.toordinal() % len(SCENES)]
    caption = generate_caption(client, scene)
    photo = generate_photo(client, scene)
    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(photo)
    manifest_path.write_text(
        json.dumps(
            {
                "date": day.isoformat(),
                "due_at_utc": iso_utc(publication_time(day)),
                "scene": scene,
                "caption": caption,
                "image": image_path.relative_to(ROOT).as_posix(),
                "buffer_post_id": None,
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    print(f"Generated {image_path.relative_to(ROOT)} and caption for {day}.")


def raw_image_url(image_path: Path) -> str:
    repo = os.getenv("GITHUB_REPOSITORY", "")
    if repo != "andylee2305/member-club-auto":
        raise RuntimeError("Unexpected GITHUB_REPOSITORY; refusing to publish an image URL.")
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    relative_path = image_path.relative_to(ROOT).as_posix()
    return f"https://raw.githubusercontent.com/{repo}/{sha}/{quote(relative_path)}"


def verify_public_image(url: str) -> None:
    for attempt in range(8):
        response = requests.get(url, allow_redirects=False, stream=True, timeout=20)
        try:
            if response.status_code == 200 and response.headers.get("Content-Type", "").startswith("image/"):
                return
        finally:
            response.close()
        if attempt < 7:
            time.sleep(5)
    raise RuntimeError("The committed image is not yet available at its public GitHub URL.")


def existing_post(api_key: str, org_id: str, channel_id: str, due_at: str, caption: str) -> str | None:
    cursor = None
    while True:
        after = f", after: {quoted(cursor)}" if cursor else ""
        query = (
            f"query {{ posts(first: 100{after}, input: {{ organizationId: {quoted(org_id)}, "
            f"filter: {{ status: [scheduled, sending, sent, error], channelIds: [{quoted(channel_id)}], "
            f"dueAt: {{ start: {quoted(due_at)}, end: {quoted(due_at)} }} }} }}) "
            "{ edges { node { id text dueAt status } } pageInfo { hasNextPage endCursor } } }"
        )
        results = graphql(api_key, query)["posts"]
        for edge in results["edges"]:
            post = edge["node"]
            if post["text"] == caption:
                if post.get("status") == "error":
                    raise RuntimeError("Matching Buffer post has an error; review it before retrying.")
                return post["id"]
            raise RuntimeError("Another Instagram post already occupies this 11:00 slot; review Buffer.")
        page = results["pageInfo"]
        if not page["hasNextPage"]:
            return None
        cursor = page["endCursor"]


def create_post(api_key: str, channel_id: str, caption: str, due_at: str, image_url: str) -> str:
    query = (
        "mutation { createPost(input: { "
        f"text: {quoted(caption)}, channelId: {quoted(channel_id)}, "
        "schedulingType: automatic, mode: customScheduled, "
        f"dueAt: {quoted(due_at)}, "
        f"assets: [{{ image: {{ url: {quoted(image_url)} }} }}], "
        "metadata: { instagram: { type: post, shouldShareToFeed: true, isAiGenerated: true } }, "
        "aiAssisted: true "
        "}) { ... on PostActionSuccess { post { id dueAt channelId } } "
        "... on MutationError { message } } }"
    )
    result = graphql(api_key, query)["createPost"]
    if not result.get("post"):
        raise RuntimeError(f"Buffer refused the post: {result.get('message', 'unknown error')}")
    post = result["post"]
    actual_due = datetime.fromisoformat(post["dueAt"].replace("Z", "+00:00"))
    intended_due = datetime.fromisoformat(due_at.replace("Z", "+00:00"))
    if post["channelId"] != channel_id or actual_due != intended_due:
        raise RuntimeError("Buffer returned an unexpected channel or scheduled time.")
    return post["id"]


def schedule(day: date) -> None:
    image_path, manifest_path = paths(day)
    if not image_path.is_file() or not manifest_path.is_file():
        raise RuntimeError("Generate and commit the photo and manifest before scheduling.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["date"] != day.isoformat() or manifest["image"] != image_path.relative_to(ROOT).as_posix():
        raise RuntimeError("Manifest date or image path does not match the requested date.")
    if publication_time(day) <= datetime.now(timezone.utc):
        raise RuntimeError("The requested 11:00 Hong Kong publishing time has passed.")
    api_key = required_secret("BUFFER_API_KEY")
    org_id, channel = find_target_channel(api_key)
    if manifest.get("buffer_post_id"):
        print(f"Already scheduled in Buffer: {manifest['buffer_post_id']}")
        return
    post_id = existing_post(api_key, org_id, channel["id"], manifest["due_at_utc"], manifest["caption"])
    if post_id:
        print(f"Found matching existing Buffer post: {post_id}")
    else:
        url = raw_image_url(image_path)
        verify_public_image(url)
        post_id = create_post(api_key, channel["id"], manifest["caption"], manifest["due_at_utc"], url)
        print(f"Scheduled @{TARGET_HANDLE} for {day} 11:00 Hong Kong time: {post_id}")
    manifest["buffer_post_id"] = post_id
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "generate", "schedule"))
    parser.add_argument("--date", default="", help="Hong Kong publication date, YYYY-MM-DD; default tomorrow")
    args = parser.parse_args()
    day = target_day(args.date)
    try:
        {"preflight": preflight, "generate": generate, "schedule": schedule}[args.command](day)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
