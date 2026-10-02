import io
import warnings
from PIL import Image, UnidentifiedImageError
from fastapi import HTTPException

MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_PIXELS = 4_000_000


def extract_embedding(contents):
    if not contents or len(contents) > MAX_IMAGE_BYTES:
        raise HTTPException(413, 'Image must be between 1 byte and 4 MiB')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(contents)) as image:
                if image.format not in {'JPEG', 'PNG'}:
                    raise HTTPException(415, 'Use a JPEG or PNG image')
                if image.width * image.height > MAX_PIXELS:
                    raise HTTPException(413, 'Image exceeds 4 million pixels')
                image.load()
                rgb = image.convert('RGB')
                rgb.thumbnail((1280, 1280))
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(400, 'Invalid or oversized image') from None
    try:
        import face_recognition
        import numpy as np
    except ImportError:
        raise HTTPException(503, 'Install the server biometric dependencies to process images') from None
    encodings = face_recognition.face_encodings(np.array(rgb))
    if len(encodings) != 1:
        raise HTTPException(400, 'Provide an image containing exactly one face')
    return encodings[0].tolist()
