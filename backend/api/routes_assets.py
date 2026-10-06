from fastapi import APIRouter, HTTPException, Query, Response

from backend.services.image_storage import is_blob_reference, read_image_bytes
from backend.services.vision_base import guess_mime_type


router = APIRouter()


@router.get("/image")
async def private_image(ref: str = Query(..., max_length=1400)):
    if not is_blob_reference(ref):
        raise HTTPException(status_code=400, detail="Invalid image reference")
    try:
        payload = await read_image_bytes(ref)
        mime = guess_mime_type(payload)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Image not found") from exc
    return Response(
        content=payload,
        media_type=mime,
        headers={
            "Cache-Control": "private, no-cache",
            "X-Content-Type-Options": "nosniff",
        },
    )
