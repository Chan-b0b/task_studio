"""가짜 로봇. 팔 끝·섀시·석션·힘센서를 숫자로만 흉내 낸다. 작업셀(World)은 과제가 꽂는다."""
from __future__ import annotations

import math
import random
from typing import Any, Callable

from ..core.skill import Aborted, Unreachable
from ..core.types import Frame, ObjectPose, Pose, Wrench


class World:
    """작업셀. 기본은 아무것도 없는 평평한 바닥."""

    def contact_ee_z(self, wx: float, wy: float, holding: Any) -> float:
        return 0.0                                   # 이 높이에서 컵(또는 들고 있는 물건)이 닿는다

    def grab(self, wx: float, wy: float) -> Any:     # 씰 됐을 때 무엇을 집었나 (None = 아무것도)
        return None

    def drop(self, wx: float, wy: float, obj: Any) -> None: ...

    def objects(self, cls: str) -> list[tuple[float, float, float, float]]:
        return []                                    # (world x, y, yaw, 윗면 z)


class _Motion:
    def __init__(self, duration: float, apply: Callable[[float], None]) -> None:
        self.duration, self.apply, self.elapsed, self.stopped = max(duration, 1e-6), apply, 0.0, False

    def step(self, dt: float) -> bool:
        if self.stopped:
            return True
        self.elapsed = min(self.duration, self.elapsed + dt)
        self.apply(self.elapsed / self.duration)
        return self.elapsed >= self.duration

    def stop(self) -> None:
        self.stopped = True


class MockArm:
    REACH = dict(x=(0.30, 0.95), y=(-0.50, 0.50), z=(0.60, 1.35))

    def __init__(self, robot: "MockRobot", side: str, home: Pose) -> None:
        self.robot, self.side, self.pose, self.home = robot, side, home.model_copy(), home

    def ee_pose(self) -> Pose:
        return self.pose.model_copy()

    def reachable(self, pose: Pose) -> tuple[bool, float]:
        err = 0.0
        for axis, (lo, hi) in self.REACH.items():
            v = getattr(pose, axis)
            err = max(err, lo - v, v - hi)
        return err <= 0.0, max(err, 0.0)

    def move_ee(self, pose: Pose, straight: bool, speed: float) -> _Motion:
        if not self.reachable(pose)[0]:
            raise Unreachable(f"{self.side} ({pose.x:.3f}, {pose.y:+.3f}, {pose.z:.3f})")
        a, b = self.pose.model_copy(), pose
        dist = math.dist((a.x, a.y, a.z), (b.x, b.y, b.z))

        def apply(f: float) -> None:
            for k in ("x", "y", "z", "roll", "pitch", "yaw"):
                setattr(self.pose, k, getattr(a, k) + f * (getattr(b, k) - getattr(a, k)))
        return _Motion(dist / max(speed, 1e-3), apply)


class MockJoints:
    def __init__(self, robot: "MockRobot") -> None:
        self.robot = robot
        self._q: dict[str, list[float]] = {}

    def q(self, group: str) -> list[float]:
        return list(self._q.get(group, []))

    def move(self, group: str, q: list[float], speed: float) -> _Motion:
        arm = self.robot._arms.get(group.removesuffix("_arm"))
        start = arm.pose.model_copy() if arm else None

        def apply(f: float) -> None:
            if arm:      # 가짜 로봇의 가정: 팔 관절 이동은 홈(시야 밖)으로 가는 것
                for k in ("x", "y", "z", "roll", "pitch", "yaw"):
                    setattr(arm.pose, k, getattr(start, k) + f * (getattr(arm.home, k) - getattr(start, k)))
            if f >= 1.0:
                self._q[group] = list(q)
        return _Motion(1.5 / max(speed, 0.05), apply)


class MockChassis:
    def __init__(self, robot: "MockRobot", gain: float = 1.0) -> None:
        self.robot, self.gain = robot, gain
        self.x = self.y = self.yaw = 0.0          # world 좌표에서 base_link 의 자리

    def to_world(self, bx: float, by: float) -> tuple[float, float]:
        c, s = math.cos(self.yaw), math.sin(self.yaw)
        return self.x + c * bx - s * by, self.y + s * bx + c * by

    def to_base(self, wx: float, wy: float) -> tuple[float, float]:
        c, s = math.cos(self.yaw), math.sin(self.yaw)
        dx, dy = wx - self.x, wy - self.y
        return c * dx + s * dy, -s * dx + c * dy

    def move(self, dx: float, dy: float, dyaw: float, speed: float) -> _Motion:
        x0, y0, yaw0 = self.x, self.y, self.yaw
        tx, ty = self.to_world(dx * self.gain, dy * self.gain)

        def apply(f: float) -> None:
            self.x, self.y, self.yaw = x0 + f * (tx - x0), y0 + f * (ty - y0), yaw0 + f * dyaw
        return _Motion(max(math.hypot(dx, dy) / max(speed, 1e-3), abs(dyaw) / 0.3), apply)


class MockSuction:
    LATCH_S = 0.3                                 # 진공이 잡히는 데 걸리는 시간

    def __init__(self, robot: "MockRobot") -> None:
        self.robot, self.is_on, self.holding, self._since = robot, False, None, None

    def on(self) -> None:
        self.is_on = True

    def off(self, blow: bool = False) -> None:
        self.is_on, self._since = False, None
        if self.holding is not None:
            wx, wy = self.robot.cup_world_xy()
            self.robot.world.drop(wx, wy, self.holding)
            self.holding = None

    def sealed(self) -> bool:
        if not self.is_on:
            return False
        if self.holding is not None:
            return True
        if self.robot.cup_depth() < 0.0005:       # 컵이 눌려 있지 않다
            self._since = None
            return False
        now = self.robot.clock.now()
        self._since = now if self._since is None else self._since
        if now - self._since >= self.LATCH_S:
            self.holding = self.robot.world.grab(*self.robot.cup_world_xy())
            if self.holding is None:
                self._since = None
        return self.holding is not None


class _Wrist:
    STIFFNESS = 3000.0                            # N/m: 3.3 mm 눌리면 10 N

    def __init__(self, robot: "MockRobot") -> None:
        self.robot = robot

    def read(self) -> Wrench:
        return Wrench(fz=self.STIFFNESS * max(0.0, self.robot.cup_depth()), t=self.robot.clock.now())


class _Camera:
    def __init__(self, robot: "MockRobot") -> None:
        self.robot = robot

    def capture(self) -> Frame:
        return Frame(t=self.robot.clock.now(), q_torso=self.robot.joints.q("torso"), q_head=self.robot.joints.q("head"))


class MockDetector:
    """world 의 물체를 base_link 로 옮겨 돌려준다. 팔이 카메라 앞을 가리면 아무것도 못 본다."""

    def __init__(self, robot: "MockRobot", noise_m: float = 0.002, seed: int = 0) -> None:
        self.robot, self.noise, self.rng = robot, noise_m, random.Random(seed)
        self.blind = 0                            # 시험용: 다음 N 번은 못 본 척

    def detect(self, frame: Frame, cls: str) -> list[ObjectPose]:
        if self.blind > 0:
            self.blind -= 1
            return []
        if self.robot.arm_in_view():
            return []
        found = []
        for wx, wy, wyaw, top_z in self.robot.world.objects(cls):
            bx, by = self.robot.chassis.to_base(wx, wy)
            if 0.30 < bx < 1.20 and abs(by) < 0.45:
                n = lambda: self.rng.uniform(-self.noise, self.noise)
                found.append(ObjectPose(cls=cls, pose=Pose(x=bx + n(), y=by + n(), z=top_z,
                                                           yaw=(wyaw - self.robot.chassis.yaw) % math.pi), conf=0.93))
        return sorted(found, key=lambda o: abs(o.pose.y))


class MockRobot:
    def __init__(self, clock: Any, world: World | None = None, suction_arm: str = "left",
                 chassis_gain: float = 1.0, force_abort_n: float = 40.0) -> None:
        self.clock, self.world = clock, world or World()
        home = dict(roll=math.pi, pitch=0.0, yaw=math.pi)
        self._arms = {"left": MockArm(self, "left", Pose(x=0.45, y=0.38, z=1.17, **home)),
                      "right": MockArm(self, "right", Pose(x=0.45, y=-0.38, z=1.17, **home))}
        self.chassis, self.suction, self.joints = MockChassis(self, chassis_gain), MockSuction(self), MockJoints(self)
        self._wrist, self._cam = _Wrist(self), _Camera(self)
        self.suction_arm, self.force_abort_n = suction_arm, force_abort_n
        self.devices: dict[str, Any] = {}
        self.detectors: dict[str, Any] = {}
        self.estop = False

    def arm(self, side: str) -> MockArm:
        return self._arms[side]

    def wrist(self, side: str) -> _Wrist:
        return self._wrist

    def camera(self, name: str) -> _Camera:
        return self._cam

    def detector(self, name: str) -> Any:
        return self.detectors[name]

    def device(self, name: str) -> Any:
        return self.devices[name]

    def check(self) -> None:
        if self.estop:
            raise Aborted("estop")
        if self._wrist.read().fz > self.force_abort_n:
            raise Aborted("force_limit")

    # --- 가짜 물리 ---
    def cup_world_xy(self) -> tuple[float, float]:
        p = self._arms[self.suction_arm].pose
        return self.chassis.to_world(p.x, p.y)

    def cup_depth(self) -> float:
        """컵(또는 들고 있는 물건)이 닿는 높이보다 얼마나 더 내려가 있나 (m, + = 눌림)."""
        p = self._arms[self.suction_arm].pose
        return self.world.contact_ee_z(*self.cup_world_xy(), self.suction.holding) - p.z

    def arm_in_view(self) -> bool:
        return any(a.pose.x > 0.50 and abs(a.pose.y) < 0.25 for a in self._arms.values())
