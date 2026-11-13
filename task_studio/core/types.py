"""블록 사이를 흐르는 값(wire)의 기본 타입. 전부 base_link 기준, m / rad."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Pose(BaseModel):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    roll: float = 0.0
    pitch: float = 0.0
    yaw: float = 0.0


class JointState(BaseModel):
    group: str
    q: list[float]


class Wrench(BaseModel):
    fx: float = 0.0
    fy: float = 0.0
    fz: float = 0.0
    tx: float = 0.0
    ty: float = 0.0
    tz: float = 0.0
    t: float = 0.0


class Frame(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    rgb: Any = None
    depth: Any = None
    q_torso: list[float] = Field(default_factory=list)
    q_head: list[float] = Field(default_factory=list)
    t: float = 0.0


class ObjectPose(BaseModel):
    cls: str
    pose: Pose                      # x, y = 중심, z = 윗면 높이, yaw = 긴 변 방향
    size: tuple[float, float, float] = (0.0, 0.0, 0.0)
    conf: float = 1.0


class Station(BaseModel):
    name: str
    pose: Pose                      # 지도 좌표


class Decision(BaseModel):
    choice: str
    args: dict[str, Any] = Field(default_factory=dict)
