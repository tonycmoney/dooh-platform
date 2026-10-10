import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from .models import ApprovalStatus, MediaKind, VideoFit

HexColor = Annotated[str, StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$")]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Player -------------------------------------------------------------------


class RegisterIn(BaseModel):
    device_uid: Annotated[str, StringConstraints(min_length=4, max_length=128)]
    app_version: str | None = None


class RegisterOut(BaseModel):
    pairing_code: str
    claim_secret: str


class PairingStatusIn(BaseModel):
    device_uid: str
    claim_secret: str


class PairingStatusOut(BaseModel):
    paired: bool
    token: str | None = None
    device_id: uuid.UUID | None = None
    name: str | None = None
    venue_name: str | None = None


class HeartbeatIn(BaseModel):
    app_version: str | None = None
    battery_level: Annotated[int, Field(ge=0, le=100)] | None = None
    is_charging: bool | None = None
    latitude: Annotated[float, Field(ge=-90, le=90)] | None = None
    longitude: Annotated[float, Field(ge=-180, le=180)] | None = None
    location_accuracy_m: float | None = None
    now_playing_media_id: uuid.UUID | None = None
    now_playing_title: str | None = None
    manifest_version: str | None = None


class HeartbeatOut(BaseModel):
    manifest_version: str
    name: str | None
    venue_name: str | None


class TextSlideProps(BaseModel):
    text: str
    font_size: int
    text_color: str
    background_color: str


class ManifestItem(BaseModel):
    item_id: uuid.UUID
    media_id: uuid.UUID
    kind: MediaKind
    title: str
    duration_seconds: int
    video_fit: VideoFit
    url: str | None = None
    sha256: str | None = None
    size_bytes: int | None = None
    media_duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    text: TextSlideProps | None = None


class Manifest(BaseModel):
    version: str
    loop_id: uuid.UUID | None
    loop_name: str | None
    items: list[ManifestItem]


class PlayIn(BaseModel):
    id: uuid.UUID
    media_id: uuid.UUID | None = None
    media_title: str | None = None
    loop_id: uuid.UUID | None = None
    started_at: datetime
    duration_ms: Annotated[int, Field(ge=0)]


class PlaysIn(BaseModel):
    plays: Annotated[list[PlayIn], Field(max_length=500)]


class PlaysOut(BaseModel):
    accepted: list[uuid.UUID]
    inserted: int


# --- Admin --------------------------------------------------------------------


class LoginIn(BaseModel):
    password: str


class LoginOut(BaseModel):
    token: str


class SettingsOut(BaseModel):
    auto_approve: bool


class SettingsIn(BaseModel):
    auto_approve: bool


class MediaOut(ORM):
    id: uuid.UUID
    kind: MediaKind
    title: str
    status: ApprovalStatus
    url: str | None = None
    thumbnail_url: str | None = None
    original_name: str | None
    mime_type: str | None
    size_bytes: int | None
    width: int | None
    height: int | None
    duration_seconds: float | None
    text: str | None
    font_size: int | None
    text_color: str | None
    background_color: str | None
    created_at: datetime
    used_in_loops: int = 0
    converted_from: str | None = None  # set on upload, e.g. "HEIC → JPG"


class MediaUpdate(BaseModel):
    title: ShortText | None = None


class TextSlideIn(BaseModel):
    title: ShortText
    text: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    font_size: Annotated[int, Field(ge=8, le=400)] = 96
    text_color: HexColor = "#FFFFFF"
    background_color: HexColor = "#000000"


class LoopItemIn(BaseModel):
    media_id: uuid.UUID
    duration_seconds: Annotated[int, Field(ge=1, le=3600)] = 10
    video_fit: VideoFit = VideoFit.loop


class LoopIn(BaseModel):
    name: ShortText
    items: list[LoopItemIn] = []


class LoopItemOut(ORM):
    id: uuid.UUID
    media_id: uuid.UUID
    position: int
    duration_seconds: int
    video_fit: VideoFit
    media: MediaOut


class LoopOut(ORM):
    id: uuid.UUID
    name: str
    items: list[LoopItemOut]
    device_ids: list[uuid.UUID]
    total_seconds: int
    updated_at: datetime


class LoopSummary(ORM):
    id: uuid.UUID
    name: str
    item_count: int
    total_seconds: int
    device_count: int
    updated_at: datetime


class AssignIn(BaseModel):
    device_ids: list[uuid.UUID]


class PairIn(BaseModel):
    pairing_code: Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=6, max_length=6)]
    name: ShortText
    venue_name: ShortText
    venue_address: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] = ""
    loop_id: uuid.UUID | None = None


class DeviceUpdate(BaseModel):
    name: ShortText | None = None
    venue_name: ShortText | None = None
    venue_address: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None
    loop_id: uuid.UUID | None = None
    clear_loop: bool = False


class DeviceOut(ORM):
    id: uuid.UUID
    device_uid: str
    name: str | None
    venue_name: str | None
    venue_address: str | None
    latitude: float | None
    longitude: float | None
    location_accuracy_m: float | None
    location_at: datetime | None
    online: bool
    last_seen_at: datetime | None
    battery_level: int | None
    is_charging: bool | None
    app_version: str | None
    now_playing_title: str | None
    now_playing_media_id: uuid.UUID | None
    loop_id: uuid.UUID | None
    loop_name: str | None
    in_sync: bool
    paired_at: datetime | None


class PlayLogOut(ORM):
    id: uuid.UUID
    device_id: uuid.UUID
    media_id: uuid.UUID | None
    media_title: str | None
    loop_id: uuid.UUID | None
    started_at: datetime
    duration_ms: int
    received_at: datetime
