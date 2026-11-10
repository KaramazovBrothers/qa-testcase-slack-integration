"""Screenshots attached to cases.

One picture per set is the default for every generated case ("how the method
looks on the frontend"); any case can point at its own picture instead. Both
kinds live in `case_images`; the default row is the one with `is_default=1`.
"""

import io
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app import storage

# Formats every browser can display and Slack accepts as an image.
ALLOWED_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}
MAX_BYTES = 10 * 1024 * 1024
# Slack shows an attachment at its natural size, so a full-page screenshot would
# fill the thread. The picture is only a hint, and 50 px is enough to recognize
# the method; the original stays available in the workspace.
SLACK_THUMB_SIZE = (50, 50)
_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sniff(content: bytes) -> Optional[str]:
    """Trust the bytes, not the browser-supplied content type."""
    for signature, media_type in _SIGNATURES:
        if content.startswith(signature):
            return media_type
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None


def safe_filename(name: str, media_type: str) -> str:
    stem = Path(name or "image").name
    stem = re.sub(r"[^\w.\- ]+", "_", stem).strip(" ._") or "image"
    if not stem.lower().endswith(ALLOWED_TYPES[media_type]):
        stem = f"{Path(stem).stem[:80]}{ALLOWED_TYPES[media_type]}"
    return stem[:120]


def read_image(image_id: int, user_id: int) -> Optional[dict]:
    with storage.connection() as db:
        row = db.execute(
            "SELECT * FROM case_images WHERE id=? AND owner_user_id=?",
            (image_id, user_id),
        ).fetchone()
    return dict(row) if row else None


def meta_for(db, image_id: Optional[int]) -> Optional[dict]:
    """Everything the UI needs about a picture except its bytes."""
    if not image_id:
        return None
    row = db.execute(
        "SELECT id,filename,media_type,size_bytes,updated_at,is_default "
        "FROM case_images WHERE id=?", (image_id,),
    ).fetchone()
    return dict(row) if row else None


def set_default(set_id: int, user_id: int, filename: str, content: bytes,
                media_type: str) -> dict:
    """Store the set's default picture, replacing the previous one in place."""
    name = safe_filename(filename, media_type)
    stamp = _now()
    with storage.connection() as db:
        existing = db.execute(
            "SELECT id FROM case_images WHERE set_id=? AND is_default=1", (set_id,),
        ).fetchone()
        if existing:
            image_id = existing["id"]
            db.execute(
                """UPDATE case_images SET filename=?,media_type=?,size_bytes=?,
                       content=?,updated_at=?,owner_user_id=? WHERE id=?""",
                (name, media_type, len(content), content, stamp, user_id, image_id),
            )
        else:
            image_id = db.execute(
                """INSERT INTO case_images(owner_user_id,set_id,filename,media_type,
                       size_bytes,content,is_default,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,1,?,?)""",
                (user_id, set_id, name, media_type, len(content), content, stamp, stamp),
            ).lastrowid
        return {"id": image_id, "filename": name, "media_type": media_type,
                "size_bytes": len(content), "updated_at": stamp, "is_default": True}


def add_override(set_id: int, user_id: int, filename: str, content: bytes,
                 media_type: str) -> dict:
    """Store a picture for one case; the case then points at this new row."""
    name = safe_filename(filename, media_type)
    stamp = _now()
    with storage.connection() as db:
        image_id = db.execute(
            """INSERT INTO case_images(owner_user_id,set_id,filename,media_type,
                   size_bytes,content,is_default,created_at,updated_at)
               VALUES(?,?,?,?,?,?,0,?,?)""",
            (user_id, set_id, name, media_type, len(content), content, stamp, stamp),
        ).lastrowid
    return {"id": image_id, "filename": name, "media_type": media_type,
            "size_bytes": len(content), "updated_at": stamp, "is_default": False}


def default_image_id(db, set_id: int) -> Optional[int]:
    row = db.execute(
        "SELECT id FROM case_images WHERE set_id=? AND is_default=1", (set_id,),
    ).fetchone()
    return row["id"] if row else None


def effective_image(db, case: dict) -> Optional[dict]:
    """The picture a case actually delivers: its own, else the set default."""
    image_id = case.get("image_id") or default_image_id(db, case.get("set_id"))
    return meta_for(db, image_id)


def attach_images(db, cases: list[dict]) -> None:
    """Add `image` (meta) and `image_source` to every case in a set payload."""
    default_id = default_image_id(db, cases[0]["set_id"]) if cases else None
    for case in cases:
        image_id = case.get("image_id") or default_id
        case["image"] = meta_for(db, image_id)
        case["image_source"] = (
            None if not image_id else
            "case" if case.get("image_id") else "set"
        )


def for_slack(image: dict) -> dict:
    """The attachment that goes to Slack: the same picture, scaled down.

    Slack renders an image at its natural size, so a page screenshot would push
    the whole case out of view. A small copy is enough to recognize the method;
    the result is handed back as a PNG (or the original when it cannot be
    re-encoded, so a send never fails just because of the thumbnail).
    """
    content = image.get("content") or b""
    try:
        from PIL import Image  # Pillow is optional: see the fallback below

        with Image.open(io.BytesIO(content)) as source:
            picture = source.convert("RGBA")
            # Slack always shows an image at its natural size, so the small copy
            # is the real size; without this it would be upscaled to the frame.
            picture.thumbnail(SLACK_THUMB_SIZE, Image.LANCZOS)
            canvas = Image.new("RGBA", SLACK_THUMB_SIZE, (0, 0, 0, 0))
            canvas.paste(picture, ((SLACK_THUMB_SIZE[0] - picture.width) // 2,
                                   (SLACK_THUMB_SIZE[1] - picture.height) // 2))
            buffer = io.BytesIO()
            canvas.save(buffer, format="PNG", optimize=True)
        return {"filename": f"method-{image['id']}.png", "content": buffer.getvalue()}
    except Exception:
        # No Pillow (or an image it cannot decode): send the original untouched.
        return {"filename": image["filename"], "content": content}


def delete_orphan_override(db, case_id: int) -> None:
    """Drop a case's own picture once no case points at it any more."""
    row = db.execute("SELECT image_id FROM test_cases WHERE id=?", (case_id,)).fetchone()
    if row and row["image_id"]:
        db.execute("DELETE FROM case_images WHERE id=? AND is_default=0 "
                   "AND NOT EXISTS (SELECT 1 FROM test_cases WHERE image_id=?)",
                   (row["image_id"], row["image_id"]))
