"""파트 인터페이스 (Level 0). 스킬은 이것만 안다. `vega/` 와 `mock/` 가 각각 채운다.

모든 움직임은 Motion 으로 돌려준다: 스킬이 tick 마다 `step(dt)` 를 부르고, 가드가 울리면 `stop()`.
그래서 가드·선점은 스킬 쪽 루프 하나(Action.drive)에만 있다.
"""
from __future__ import annotations

from typing import Protocol

from ..core.types import Frame, ObjectPose, Pose, Wrench


class Motion(Protocol):
    def step(self, dt: float) -> bool: ...      # 한 tick 진행. True = 목표 도달
    def stop(self) -> None: ...                 # 지금 자리에서 멈춤


class Arm(Protocol):
    def ee_pose(self) -> Pose: ...
    def move_ee(self, pose: Pose, straight: bool, speed: float) -> Motion: ...   # 못 풀면 Unreachable
    def reachable(self, pose: Pose) -> tuple[bool, float]: ...                   # (닿나, 오차 m)


class Joints(Protocol):
    def q(self, group: str) -> list[float]: ...
    def move(self, group: str, q: list[float], speed: float) -> Motion: ...      # speed = 속도 배율 0~1


class Chassis(Protocol):
    def move(self, dx: float, dy: float, dyaw: float, speed: float) -> Motion: ...


class Suction(Protocol):
    def on(self) -> None: ...
    def off(self, blow: bool = False) -> None: ...
    def sealed(self) -> bool: ...


class WristSensor(Protocol):
    def read(self) -> Wrench: ...


class Camera(Protocol):
    def capture(self) -> Frame: ...


class Detector(Protocol):
    """검출 모델은 과제가 등록한다. 기본 층은 모델을 모른다."""
    def detect(self, frame: Frame, cls: str) -> list[ObjectPose]: ...


class Robot(Protocol):
    chassis: Chassis
    suction: Suction
    joints: Joints

    def arm(self, side: str) -> Arm: ...
    def wrist(self, side: str) -> WristSensor: ...
    def camera(self, name: str) -> Camera: ...
    def detector(self, name: str) -> Detector: ...
    def device(self, name: str): ...            # 과제가 등록한 장치 (바코드 리더 등)
    def check(self) -> None: ...                # E-stop / 하드 힘 한계 → Aborted
