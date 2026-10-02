import hashlib
import hmac
import json
import math
from datetime import datetime, time, timedelta, timezone
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Scan(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    event_id: UUID
    occurred_at: datetime
    direction: Literal['IN', 'OUT']
    embedding: list[float] = Field(min_length=128, max_length=128)

    @field_validator('occurred_at')
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('occurred_at must include a timezone')
        return value.astimezone(timezone.utc)

    @field_validator('embedding')
    @classmethod
    def bounded(cls, values):
        if any(not math.isfinite(v) or abs(v) > 10 for v in values):
            raise ValueError('Embedding contains invalid values')
        return values


def fingerprint(scan, key):
    raw = json.dumps(scan.model_dump(mode='json'), sort_keys=True, separators=(',', ':')).encode()
    return hmac.new(key.encode(), raw, hashlib.sha256).hexdigest()


def token_hash(token):
    # Only high-entropy generated API tokens; this is NOT password hashing.
    return hashlib.sha256(token.encode()).hexdigest()


def status_for(direction, occurred_at, settings):
    local = occurred_at.astimezone(ZoneInfo(settings.timezone)).time()
    start, end = time.fromisoformat(settings.class_start), time.fromisoformat(settings.class_end)
    if direction == 'IN':
        if local >= end:
            return 'After Scheduled Hours'
        return 'In-Time Entry' if local <= start else 'Late Entry'
    return 'Early Exit' if local < end else 'Exit'


def day_bounds(day, tz_name):
    tz = ZoneInfo(tz_name)
    start = datetime.combine(day, time.min, tzinfo=tz)
    return start, datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)


def nearest_match(incoming, candidates, threshold, margin):
    # Multiple templates per student must not be treated as competing identities.
    best_by_student = {}
    for student_id, vector in candidates:
        if len(vector) != 128 or any(not math.isfinite(v) for v in vector):
            raise ValueError('Corrupt stored embedding')
        distance = math.dist(incoming, vector)
        best_by_student[student_id] = min(distance, best_by_student.get(student_id, math.inf))
    ranked = sorted((distance, student_id) for student_id, distance in best_by_student.items())
    if not ranked or ranked[0][0] > threshold:
        return None
    if len(ranked) > 1 and ranked[1][0] - ranked[0][0] < margin:
        return None
    return ranked[0][1]
