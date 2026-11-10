"""Screenshots for cases: upload, view, reset, and the Slack call that sends them."""

from fastapi import APIRouter, File, HTTPException, Response, UploadFile

from app import case_images, storage
from app.case_images import ALLOWED_TYPES, MAX_BYTES
from app.current_user import CurrentUserId

router = APIRouter(prefix="/api/case-images", tags=["Case screenshots"])


async def _read_upload(file: UploadFile) -> tuple[bytes, str]:
    content = await file.read(MAX_BYTES + 1)
    if not content:
        raise HTTPException(422, "The uploaded image is empty")
    if len(content) > MAX_BYTES:
        raise HTTPException(413, "The image is larger than 10 MB")
    media_type = case_images._sniff(content)
    if media_type not in ALLOWED_TYPES:
        raise HTTPException(422, "Only PNG, JPEG, GIF or WebP images are accepted")
    return content, media_type


@router.get("/{image_id}")
def view_image(image_id: int, user_id: CurrentUserId = storage.LOCAL_USER_ID) -> Response:
    """Serve the stored bytes so the card can show the picture it will send."""
    row = case_images.read_image(image_id, user_id)
    if not row:
        raise HTTPException(404, "Image not found")
    return Response(
        content=row["content"],
        media_type=row["media_type"],
        headers={
            "Cache-Control": "private, max-age=300",
            # The file is rendered in an <img>: never let it be treated as a page.
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/sets/{set_id}/default", status_code=201)
async def upload_default(
    set_id: int,
    file: UploadFile = File(...),
    user_id: CurrentUserId = storage.LOCAL_USER_ID,
) -> dict:
    """One picture for the whole set: it is used by every generated case."""
    content, media_type = await _read_upload(file)
    with storage.connection() as db:
        from app.local_api import require, require_task

        set_row = db.execute("SELECT task_id FROM case_sets WHERE id=?", (set_id,)).fetchone()
        if set_row is None:
            raise HTTPException(404, "Set not found")
        require_task(db, set_row["task_id"], user_id)
    return case_images.set_default(set_id, user_id, file.filename or "image", content, media_type)


@router.post("/cases/{case_id}", status_code=201)
async def upload_override(
    case_id: int,
    file: UploadFile = File(...),
    user_id: CurrentUserId = storage.LOCAL_USER_ID,
) -> dict:
    """The picture for one case; it replaces the set default for that case only."""
    content, media_type = await _read_upload(file)
    with storage.connection() as db:
        from app.local_api import require, require_task

        case = db.execute(
            """SELECT c.id,c.set_id,s.task_id FROM test_cases c
               JOIN case_sets s ON s.id=c.set_id WHERE c.id=?""", (case_id,),
        ).fetchone()
        if case is None:
            raise HTTPException(404, "Case not found")
        require_task(db, case["task_id"], user_id)
    image = case_images.add_override(case["set_id"], user_id, file.filename or "image",
                                     content, media_type)
    with storage.connection() as db:
        db.execute("UPDATE test_cases SET image_id=? WHERE id=?", (image["id"], case_id))
        from app.local_api import touch

        touch(db, case["task_id"])
    return {**image, "case_id": case_id}


@router.delete("/cases/{case_id}", status_code=204)
def reset_override(case_id: int, user_id: CurrentUserId = storage.LOCAL_USER_ID) -> Response:
    """Go back to the set picture for this case."""
    with storage.connection() as db:
        from app.local_api import require_task, touch

        case = db.execute(
            """SELECT c.id,c.set_id,s.task_id FROM test_cases c
               JOIN case_sets s ON s.id=c.set_id WHERE c.id=?""", (case_id,),
        ).fetchone()
        if case is None:
            raise HTTPException(404, "Case not found")
        require_task(db, case["task_id"], user_id)
        db.execute("UPDATE test_cases SET image_id=NULL WHERE id=?", (case_id,))
        case_images.delete_orphan_override(db, case_id)
        touch(db, case["task_id"])
    return Response(status_code=204)
