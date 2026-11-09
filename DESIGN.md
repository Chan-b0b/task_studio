# Task Studio — 로봇 동작을 블록(스킬)으로 쪼개고 다시 엮기

작성 2026-11-05. 참고한 코드: 로봇 PC `dexmate-LGES:/home/dexmate/LGES/Dexmate/LGES/ik_demo/` (17,000줄).
**실행 위치: 로봇 edge(Jetson Thor).** 개발은 노트북에서, 실행은 로봇 PC에서 한다. 로봇 PC에 패키지를 설치해도 된다 (사용자 2026-11-05). **`ik_demo`는 참고만 한다.** Task Studio는 ik_demo 클래스를 import·상속하지 않고 dexcontrol 위에 새로 짠다. 이 태스크에 묶이지 않기 위해서다. 표의 "참고 코드" 열은 같은 일을 ik_demo가 어디서 어떻게 했는지 가리킬 뿐이다.
**범위: 실로봇만.** 시뮬(`~/Humanoid/LGES_Sim/phys/`)은 일단 제외 (사용자 결정 2026-11-05). 파트 인터페이스를 지키면 나중에 시뮬 어댑터를 붙일 수 있게만 해 둔다.

---

## 0. 한 줄 목표

**"집는다 / 놓는다 / 옆으로 간다 / 본다" 같은 동작 하나를 입·출력이 정해진 파이썬 모듈(스킬)로 만들고,
그 스킬들을 글(YAML)이나 블록 편집기로 이어 붙인 프로그램으로 실로봇 과제를 돌리고, 다음 PoC에서도 같은 바닥을 쓴다.**

## 1. 지금 코드에서 보이는 문제 (왜 하는가)

| 지금 | 문제 |
|---|---|
| `chassis_sequence.run_item()` 680줄 (3567–4247행) | 아이템 하나의 "왼쪽 가서 → 보고 → 집고 → 오른쪽 가서 → 보고 → 놓고 → 돌아오기"가 한 함수에 다 들어 있다. 감지 재시도, 창(window) 보정, 태그, 운영자 프롬프트, 트윈 로그, z 예측 장부가 전부 섞여 있다. Task 1(뚜껑)·2(bin)·4(박스)는 또 따로 긴 함수다. |
| 결과는 `PickResult(success, reason, contact_ee_z, ...)`로 잘 돼 있음 | 좋은 출발점. 하지만 실패했을 때 "다시 볼지 / 섀시를 옮길지 / 사람 부를지"가 코드 안에 하드코딩돼 있다. |
| 기록 코드가 스킬 안에 섞여 있다 (`[twin]` 줄, `ZTracker` CSV, `joint_trace`, `episode_record`) | 각자 목적이 있는 로그라 그대로 둔다. Task Studio 자체 기록은 이벤트 한 갈래로 따로 남긴다. |

좋은 점도 분명하다: 동작 단위(`move_joints`, `move_ee_line`, `pick`, `place`, `strafe`, `detect`)는 이미 함수로 나뉘어 있고,
입력(포즈, 예상 z)과 출력(`PickResult`)도 있다. 그 분해와 숫자(접촉 규칙, 속도, 지연)를 참고해서 **Task Studio는 새로 짠다.** ik_demo는 건드리지도, 가져다 쓰지도 않는다.

## 2. 현재 코드에서 뽑아낸 동작 목록 → 4단계로 나눔

이 저장소는 다음 PoC의 바닥이기도 하므로, 모든 블록은 두 층 중 하나에 속한다. 로봇은 항상 Dexmate Vega다 (로봇 층은 따로 두지 않는다). 기본층은 과제층을 import하지 않는다.

| 층 | 폴더 | 무엇이 들어가나 | 바뀌는 때 |
|---|---|---|---|
| **① 기본** | `task_studio/` | 스킬 계약, 런타임, Vega 하드웨어 어댑터(dexcontrol 직접), 입력 기본값(`params.yaml`), 과제와 무관한 블록, 이벤트 기록, 편집기 | 프레임워크나 로봇 설정을 고칠 때만 |
| **② 과제** | `tasks/lges/` | 작업셀을 알아야 하는 블록(검출 모델, 스테이션 목록, 슬롯 오프셋, 층 쌓기 z 예측, 바코드 분류), Task 1~4 프로그램 | PoC마다 새로 만든다 |

어느 층인지 정하는 규칙: 배터리·케이스·bin·스테이션·층(layer)·바코드·테이블 높이가 이름에 나오면 ② 과제, 아니면 ① 기본 (dexcontrol·URDF·관절 이름이 나와도 기본). 헷갈리면 ②에 두고, 두 번째 PoC에서 다시 쓰고 싶어질 때 ①로 내린다.


### Level 0 — 자원 (스킬이 아니라 스킬이 쓰는 손발)
왼팔 / 오른팔 / 토르소 / 머리 / 섀시 / 흡착 IO / 그리퍼 / 머리 카메라 / 손목 힘센서 (기본) · 바코드 리더 / 감지 모델 (과제가 등록).

### Level 1 — 원자 스킬 (액추에이터 하나, 판단 없음, 1~5초)

- **동작(Action)**: 시작하면 끝날 때까지 블로킹. `run(ctx, in) → Result`.
- **조건(Condition)**: 지금 상태를 보고 참/거짓. `check(ctx) → bool`. 동작의 `guards` 칸에 꽂으면 매 tick 묻고 울리면 동작이 멈춘다(이 자리를 "가드"라 부른다). `Condition` 노드에 넣으면 한 번 묻는다. 같은 블록이 두 자리에 다 들어간다.

규칙:
- 모든 동작은 `guards`(조건 목록)와 `timeout`을 받고, `stopped_by`(`reached` / 울린 조건 이름 / `unreachable` / `aborted`)를 돌려준다.
- 숫자(오프셋, 높이, 힘, 속도)는 블록의 입력이다. 기본값은 `task_studio/params.yaml`(로봇 한계: 속도, 힘, 섀시 지연) ← `tasks/lges/params.yaml`(작업셀 값: 홈 자세, 컵 길이, z_min)이 덮고, 프로그램이 주면 그 값이 이긴다.
- 기존 동작 + 조건으로 적을 수 있으면 새 블록을 만들지 않는다.
- 두 층은 같은 종류(동작·조건)를 만든다. 차이는 작업셀을 알아야 하는가뿐이다. 블록이 파이썬으로 짜였는지 다른 블록의 조합(YAML)인지는 쓰는 쪽에서 보이지 않는다.

#### ① 기본 (Dexmate Vega 전제)

| 종류 | 파트 | 스킬 | 입력 | 출력 | 참고 코드 (ik_demo) |
|---|---|---|---|---|---|
| 동작 | 팔·몸통·머리 | `MoveJoints` | 관절군(left_arm / right_arm / torso / head), 목표 q, 속도 배율, 가드 | `stopped_by`, 도달 q | `ArmMover.move_joints`, `pin_torso`, `set_head_pitch` |
| 동작 | 팔 | `MoveEE` | 목표 Pose, `straight`(직선 / 관절 공간 호), `keep_xy`(수직 전용), 속도, 가드 | `stopped_by`, 멈춘 Pose, 오차 | `move_ee` (호), `move_ee_line`·`move_ee_vertical` (직선), `_approach_force_guard` (호에도 가드) |
| 동작 | 섀시 | `BaseMove` | dx, dy, dyaw(= 최대 이동량), 속도, 가드 | `stopped_by`, 명령한 이동량 | 가드 없음: `strafe_*/move_*/turn_*` (속도×시간) · 가드 있음: `creep_sideways/straight` (천천히 가며 `stop_fn`) |
| 동작 | 섀시 | `Navigate` | 지도 좌표 목표 (x, y, yaw), 속도, 가드 | `stopped_by`, 도착 Pose, 오차 | 로봇 PC `lgcns_nav2_apriltag` (ROS2 Nav2) — 지도·태그 배치는 과제 데이터 |
| 동작 | 석션 | `SuctionOn`, `SuctionOff` | — (`SuctionOff`의 `blow`: 불어서 떼기) | ok | `suction_io.suction_on/off`, blow |
| 동작 | 그리퍼 | `GripperMove` | 폭(또는 위치), 힘, 속도, 가드 | `stopped_by`, 멈춘 위치, 물체 감지 여부 | `RobotiqGripper.move` |
| 동작 | 머리 카메라 | `CaptureFrame` | 카메라 이름 | `Frame{rgb, depth, q_torso, q_head, t}` | `_head_rgb` |
| 동작 | 머리 카메라 | `Detect` | Frame(없으면 직접 찍음), 검출기 이름, 물체 클래스 | `[ObjectPose]` | `case_detection/detect_*` — 검출 모델은 과제가 `parts/detector` 인터페이스로 등록, 기본은 모델을 모른다 |
| 동작 | 손목 센서 | `ReadWrench`, `TareWrench` | 팔, (tare: 샘플 수) | `Wrench`(6) / 기준값 | `vertical_force`, `tare` |
| 동작 | (계산) | `OffsetPose` | Pose, dx dy dz dyaw (Pose 기준 또는 base_link 기준) | Pose | `pick_aim` 계산의 오프셋 덧셈 |
| 동작 | (계산) | `GraspPose` | ObjectPose, 접근 방향(top / side), 잡는 점(center / edge) | Pose (툴 끝이 물체 윗면 그 점에, 물체 yaw에 맞춰) | `pick_aim`의 기하 부분 |
| 동작 | 운영자 | `Gate` | 질문, 허용 명령, autonomy | `Decision` | `_manual_strafe`, `input()` |
| 동작 | 타이머 | `Wait` | timeout, 가드 (예: `[Sealed]` = 씰 될 때까지) | `stopped_by`, 걸린 시간 | `time.sleep`, DI0 폴링 |
| 조건 | 손목 센서 | `ForceOver` | 축, 문턱 N, `relative`, 기준 창 s | bool (+ 마지막 힘) | `_creep_to_force`, `FORCE_HARD_LIMIT_N` |
| 조건 | 석션 | `Sealed` 씰 됐나 | — | bool | DI0 |
| 조건 | 타이머 | `Timeout` | 초 | bool | 각 루프의 deadline |
| 조건 | 팔 | `Reachable` (보통 `Condition` 노드에서 동작 전에 한 번) | Pose / Pose 열(위→아래) | bool, 오차 | `descent_reachable`, `column_reachable` |

#### ② 과제 (LGES)

| 종류 | 파트 | 스킬 | 입력 | 출력 | 참고 코드 (ik_demo) |
|---|---|---|---|---|---|
| 동작 | 바코드 리더 | `ReadCode` | 시간 창 | 문자열 또는 없음 | `BackgroundScanner` |
| 조건 | 팔 | `SafetyFloor` | `z_min`, 기준(컵 끝 / EE) | bool (+ 지금 높이) | `DESCENT_CHECK_BOTTOM_EE_Z`, PickResult `max_descent` |
| 조건 | 머리 카메라 | `BEVInWindow` | 물체 클래스(case/bin/box/lid), 창(x 범위, y 범위), 층 수 | bool (+ 마지막 검출 `ObjectPose`) | `_into_window`, `detect` + `_refine_det` |

### Level 2 — 복합 스킬 (원자 블록 여럿을 묶은 것, 5~30초) — 전부 ② 과제 층

기본 층은 Level 1(원자 블록)까지만 제공한다. 조합은 과제가 한다. 다음 PoC는 여기서 필요한 것을 복사해 시작한다.

| 분류 | 대표 스킬 | 구성 | 참고 코드 (ik_demo) |
|---|---|---|---|
| 보기 | `DetectObject(cls, n)` | `Detect` n번 → 중앙값 → `ObjectPose` | `detect` + `_refine_det` |
| 집기 좌표 | `ResolvePose(det, item)` | = `GraspPose` + 품목별 `OffsetPose`(값은 `objects.yaml`). 품목을 모르는 단순 과제는 이 블록 없이 기본 둘로 충분 | `pick_aim`, 품목별 config 상수 |
| 집기 | `SuctionPick(pose, expected_z, guards)` | 위로 → 접근 → `MoveEE(straight, guards=[ForceOver, SafetyFloor] + 입력 가드)` → `SuctionOn` → `Wait[Sealed]` → 들기 → `PickResult` | `SuctionMover.pick` |
| 놓기 | `SuctionPlace(pose, expected_z, release_above)` | 같은 뼈대 + `early_contact` 판정 + `SuctionOff` → `PlaceResult` | `SuctionMover.place` |
| 이동 | `GoToStation(station)` | 스테이션 목록에서 좌표를 찾아 `Navigate`; 위치 추정이 없을 때는 `BaseMove` + 도착 오차로 거리 보정 | `strafe` + `ChassisNav` |
| 장부 | `ExpectedZ(station, item, layers)` | 열(column)별 접촉 z 기록 → 다음 예상 z | `ZTracker` |
| 병렬 | `ParkDuringLeg` | `Parallel[MoveEE(park), GoToStation]` | `_park_during_legs` |

### Level 3 — 태스크 프로그램 (블록을 엮은 것)

프로그램 하나 = 트리 하나를 YAML로 쓴 것. 블록 그림의 텍스트 형태다. 구성 요소는 셋뿐이다.
1. **제어 노드** 8개 (Sequence, Fallback, Retry, Parallel, Loop, Condition, Gate, Set) — 자식들을 어떤 순서·조건으로 돌릴지.
2. **블록** (Level 1·2 스킬) — 이름과 입력.
3. **변수** `$이름` — 블록의 출력(`out: $det`)을 받아 다음 블록 입력(`pose: $det`)으로 넘기는 전선.

블록이 끝나면 `Result`가 변수에 들어가고, `Sequence`는 `status: fail`에서 멈춰 실패를 위로 올린다. 위의 `Fallback`이 받아 다음 자식(`Gate`)을 시도한다. **실패를 어떻게 처리할지는 블록 안이 아니라 트리 모양에 있다.**
파일 하나를 다른 파일에서 블록처럼 부를 수 있다(`macros/`). 블록 편집기(Blockly)는 M0부터 같이 간다: 사람은 블록을 조립하고, 편집기가 이 YAML을 쓰고 읽는다. YAML은 실행·git diff·손편집용 중간 표현으로 남는다.

## 3. 스킬 계약 (모든 블록이 지키는 모양)

```python
# task_studio/core/skill.py
from pydantic import BaseModel
from typing import ClassVar, Literal

class Result(BaseModel):
    status: Literal["ok", "fail", "aborted"]
    reason: str = ""            # 실패 이유 어휘는 스킬마다 고정

class ActionResult(Result):     # 모든 동작의 출력은 이것을 상속
    stopped_by: str             # reached / <가드 이름> / unreachable / aborted
    pose_at_stop: "Pose | None" = None
    # 스킬별 필드가 여기에 더 붙는다 (contact_z, sealed, ...)

class Skill:
    name: ClassVar[str]
    Input: ClassVar[type[BaseModel]]
    Output: ClassVar[type[Result]]
    requires: ClassVar[frozenset[str]] = frozenset()   # {"left_arm", "suction", "head_cam"} — 병렬 실행 시 충돌 검사

    def run(self, ctx: "Context", inp: BaseModel) -> Result: ...
```

```python
class Context:
    robot: "Robot"              # Level 0 자원 묶음. 지금은 dexcontrol 어댑터 하나
    bb: "Blackboard"            # 블록 사이를 흐르는 값 (typed key)
    def emit(self, event: str, **data): ...   # 모든 기록은 이 한 줄로 나간다
    def check(self): ...        # 긴 스트리밍 루프가 매 tick 부른다: 정지 요청 / 운영자 일시정지 / E-stop → 예외
    params: dict                # params.yaml 값. 스킬은 상수를 코드에 박지 않고 여기서 읽는다
```

규칙 다섯 개:
1. **스킬은 트리를 모른다.** `run()`은 그냥 블로킹 함수다. 엮는 방식(BT, 상태기계, 파이썬 스크립트)이 바뀌어도 스킬은 그대로다.
2. **입·출력은 pydantic 모델.** 스키마가 곧 블록의 "포트"가 되고, 블록 편집기 툴박스를 자동 생성할 수 있다.
3. **실패는 예외가 아니라 `Result.reason`.** 어떻게 복구할지는 트리가 정한다 (재검출 / 섀시 보정 / 운영자).
4. **긴 동작은 매 tick `ctx.check()`를 부르고 `guards`를 평가한다.** 지금 코드의 `stop_fn`, `tick_cb`가 하는 일과 같다. `ctx.check()`는 운영자 일시정지·E-stop(선점), `guards`는 그 동작을 멈추는 조건 블록들이고, 둘은 결과가 다르다: 전자는 `aborted`, 후자는 `stopped_by=<가드>`.
5. **기록은 `ctx.emit()` 하나.** 실행기가 이벤트를 JSONL 한 파일에 쓴다. 스킬 코드에 로그 코드가 없다.

## 4. 블록 사이를 흐르는 값(wire)의 타입

모두 pydantic 모델, **base_link 기준, m / rad**. 타입은 그것을 출력하는 블록과 같은 층에 둔다. 과제 타입은 기본 타입을 상속해 필드를 더할 수 있고, 편집기에서 자식 타입은 부모 구멍에 꽂힌다. 블록의 입출력 스키마가 곧 편집기의 타입 검사다.

**① 기본** (`task_studio/core/types.py`)

| 타입 | 필드 | 쓰는 곳 |
|---|---|---|
| 원시값 | float, int, str, bool, list | 숫자 입력, 식 |
| `Pose` | x y z, roll pitch yaw | EE 목표, 섀시 목표 |
| `JointState` | group, q[] | `MoveJoints` |
| `Wrench` | fx fy fz, tx ty tz, t | `ReadWrench`, `ForceOver` |
| `Frame` | rgb, depth, q_torso, q_head, t | `CaptureFrame` → `Detect` |
| `ObjectPose` | cls: str, pose: Pose, size(L, W, H), conf | `Detect` → 집기 |
| `Station` | name, pose: Pose (지도 좌표) | `Navigate` |
| `Result` / `ActionResult` | status, reason / + stopped_by, pose_at_stop | 모든 블록 / 모든 동작 출력의 공통부 (§3) |
| `Decision` | choice, args (예: move의 dx, dy) | `Gate` |

**② 과제** (`tasks/lges/types.py`)

| 타입 | 필드 | 쓰는 곳 |
|---|---|---|
| `PickResult` | ActionResult + contact_z, sealed | `SuctionPick` |
| `PlaceResult` | ActionResult + contact_z, early_contact | `SuctionPlace` |
| `ItemSpec` | item, release_above, 컵 오프셋, 기대 바코드 | `ItemSpec` → `SuctionPlace`, `DestStation` |
| `StackState` | src_layers, tgt_layers | 층 루프, `ExpectedZ` |
| `LegStation` | Station + 학습된 leg 거리 | `GoToStation`이 `Navigate` 대신 `BaseMove`를 쓸 때 |

## 5. 엮는 방식

제어 흐름은 BT 노드 8개, 값 전달은 타입 있는 `$변수`, 조건은 가드 홈. 프로그램 원본은 YAML, Blockly는 그 YAML을 그리고 읽는 편집기, 실행기는 자체 미니 BT(스레드 하나, 스킬 `run()`은 블로킹).
빌린 것: BT에서 제어 노드와 선점, Blockly에서 타입 있는 포트와 편집기, FlexBE에서 운영자 게이트.

### 선 세 종류

| 선 | 뜻 | YAML에서 | Blockly에서 |
|---|---|---|---|
| 순서선 | 부모 노드가 자식을 어떤 순서·정책으로 돌리나 | 노드 아래 들여쓴 목록 | C자 블록의 입 안에 블록을 쌓는다 |
| 값선 | 한 블록의 출력이 다른 블록의 입력으로 | `out: $det` → `pose: $det` | 변수 블록을 입력 구멍에 꽂는다. 타입이 맞아야 꽂힌다 (Pose 구멍에 Pose만) |
| 가드선 | 동작이 도는 동안 조건을 계속 본다 | `guards: [ForceOver: {…}]` | 동작 블록 옆면의 홈에 조건 블록을 꽂는다 |

### 노드 종류 (8개)

| 노드 | 뜻 | ik_demo에서는 |
|---|---|---|
| `Sequence` | 차례로, 하나 실패하면 실패 | 함수 본문 |
| `Fallback` | 차례로, 하나 성공하면 성공 | "재검출 → 안 되면 운영자" |
| `Retry(n, backoff)` | 실패하면 n번 다시 | `MAX_PHASE_ATTEMPTS`, `WINDOW_MAX_MOVES` |
| `Parallel(policy)` | 동시에, 전부/하나 끝나면 | `_park_during_legs` |
| `Loop(while / for)` | 반복, 블랙보드 값으로 종료 | `while src >= 1`, `for label, key in ITEMS` |
| `Condition(조건 블록 또는 식)` | 한 번 검사, 참이면 통과 | `if descent_reachable(...)`, `if label == "case"` |
| `Gate(prompt, allowed)` | 운영자 결정이 올 때까지 멈춤, 결정을 블랙보드에 | `_manual_strafe`, `input("Continue?")` |
| `Set` | 블랙보드 값 바꾸기 | `src -= 1; tgt += 1` |

### 블록 모양

| 종류 | Blockly 모양 | 예 |
|---|---|---|
| 제어 노드 | 입이 있는 C자 블록 | `Sequence`, `Retry(n)` |
| 동작 | 네모 블록. 입력 구멍 + 가드 홈 + `out` 변수 | `MoveEE`, `SuctionPick` |
| 조건 | 육각형 값 블록. `Condition` 노드나 가드 홈에만 꽂힌다 | `ForceOver`, `Sealed` |
| 매크로 (다른 파일) | 사용자 정의 블록. 입력 포트는 그 파일의 `$입력` | `task3_item` |
| 프로그램 | 모자 블록 두 개: "시작" 트리, "중단되면" 트리 | `main`, `on_abort` |

식은 산술·비교·논리만 (`$stack.src - 1`, `$stack.src >= 1`) — Blockly 기본 수식 블록으로 그린다. 과제 지식이 드는 계산(품목별 값, 목적지 결정, 슬롯 좌표)은 식이 아니라 블록이다. 그래야 YAML과 블록 그림이 1:1이다.

### 예시 — Task 3의 "아이템 하나" (ik_demo `run_item` 680줄에 해당)

```yaml
# tasks/lges/programs/task3_item.yaml   입력: $item (case / battery_2 / battery_1), $stack {src, tgt}
main:
  Sequence:
    - ItemSpec: {item: $item, out: $spec}                            # objects.yaml에서 품목 값 (release_above 등)
    - GoToStation: {station: source}
    - Fallback:                                                      # 소스 케이스를 찾는다. 못 찾으면 사람에게
        - Sequence:
            - BaseMove: {dy: 0.3, speed: 0.05, guards: [BEVInWindow: {cls: case}]}   # 창에 들어올 때까지 기어감
            - DetectObject: {cls: case, n: 5, out: $det}
        - Gate: {prompt: "소스 케이스를 못 찾음", allowed: [move, continue, abort]}
    - ResolvePose: {det: $det, item: $item, out: $aim}               # 케이스 중심 → 이 품목의 컵 목표
    - Condition: {check: Reachable: {pose: $aim}}
    - ExpectedZ: {station: source, item: $item, layers: $stack.src, out: $ez}
    - SuctionPick: {pose: $aim, expected_z: $ez, out: $pick}
    - ReadCode: {window: 2.0, out: $code}                             # 들고 있는 동안 바코드 리더
    - DestStation: {item: $item, barcode: $code, out: $dest}         # 바코드 일치 배터리는 divert 스테이션
    - ParkDuringLeg: {station: $dest}
    - Fallback:                                                      # 타깃 케이스를 찾는다. 절대 blind-stack 하지 않는다
        - DetectObject: {cls: case, n: 5, out: $tdet}
        - Gate: {prompt: "타깃 케이스를 못 찾음", allowed: [move, abort]}
    - SlotPose: {det: $tdet, item: $item, out: $slot}                # 타깃 케이스 → 이 품목이 놓일 자리
    - ExpectedZ: {station: target, item: $item, layers: $stack.tgt, out: $ez_t}
    - SuctionPlace: {pose: $slot, expected_z: $ez_t, release_above: $spec.release_above, out: $place}
    - Fallback:
        - Condition: {expr: "$place.status == 'ok'"}
        - Gate: {prompt: "놓기 실패, 부품을 들고 있음", allowed: [release, hold, abort]}
    - ParkDuringLeg: {station: source}
```

```yaml
# tasks/lges/programs/task3.yaml — 층 루프
main:
  Sequence:
    - Gate: {prompt: "섀시를 소스 스테이션에 세우고 d", allowed: [move, continue, abort]}
    - Loop: {while: "$stack.src >= 1",
        body: Sequence:
          - Loop: {for: $item, in: [case, battery_2, battery_1], body: task3_item}
          - Set: {$stack.src: "$stack.src - 1", $stack.tgt: "$stack.tgt + 1"}}
on_abort:                                        # 어디서 멈추든: 낮으면 수직으로 올린 뒤 홈
  Sequence:
    - MoveEE: {pose: {z: 1.1}, straight: true, keep_xy: true}
    - MoveJoints: {group: left_arm, q: $params.home_left}
```

Task 2는 같은 블록에서 `cls: case` 대신 `cls: bin`을 꽂은 것. 블록이 맞게 쪼개졌는지는 **Task 1/2/4가 새 블록 없이 조립되는지**로 검증한다 (M4).

## 6. 가로지르는 것들

**기록은 이벤트 JSONL 하나.** 실행기가 자동으로 `node_enter / node_exit(result)`를 쏘고, 스킬 안에서는 `ctx.emit("touch", f=…)`처럼 의미 있는 순간만 쏜다. 한 실행 = 파일 하나. 같은 이벤트를 Blockly 하이라이트와 화면 패널이 듣고, `replay.py`가 다시 읽는다.
기존 `[twin]` 줄·ZTracker CSV·`joint_trace`·`episode_record`는 Task Studio와 무관한 용도라 ik_demo 코드가 하던 대로 남긴다. Task Studio가 만들지 않는다.

**운영자 게이트.** 지금은 키보드 `l/r/f/b d q`. `Gate` 노드는 "질문 + 허용 명령"을 내고 `Decision`을 받는다. 키보드든 웹 버튼이든 상관없다.
FlexBE의 autonomy level을 빌려, 게이트마다 `autonomy: low|high`를 두면 "전자동 모드"에서는 low 게이트가 자동 통과한다.

**선점.** 긴 동작은 `ctx.check()`를 tick마다 부른다. 운영자 일시정지(지금 SPACE), 하드 힘 한계(20 N), E-stop이 여기서 예외를 던지고, 트리는 `aborted`로 접는다.
팔이 낮은 상태에서 멈췄을 때의 복구(수직으로 올리기 → 홈)는 프로그램의 `on_abort` 트리에 두 블록으로 적는다.

**하드웨어 어댑터.** `Robot` 프로토콜 하나(팔·섀시·석션·그리퍼·카메라·힘센서)를 `task_studio/vega/`가 dexcontrol 위에 직접 채운다. ik_demo 클래스는 쓰지 않는다. 새로 짜야 하는 것: IK(pink/pinocchio, URDF), 직선·수직 EE 이동, 관절 보간(ruckig), 힘 접촉 판정(변화량 vs 이동 중앙값), 섀시 odometry 이동, 석션 DIO, 그리퍼, 카메라 캡처. 프로토콜을 지키면 나중에 시뮬 어댑터도 같은 자리에 붙는다.

## 7. 디렉토리 (두 층이 폴더로 보이게)

```
Task_Studio/
  task_studio/                 ① 기본 — Vega 전제, 과제는 모른다
    core/       skill.py  types.py  context.py  blackboard.py  events.py  registry.py
    runtime/    nodes.py (8개)  loader.py (YAML→트리, 이름 붙인 조합 포함)  executor.py (스레드)
    parts/      arm.py  chassis.py  suction.py  gripper.py  camera.py  wrist_sensor.py  detector.py   # 파트 인터페이스
    vega/       robot.py (dexcontrol)  ik.py (pink)  arm.py  chassis.py  suction.py  gripper.py  camera.py  wrist.py  — ik_demo 의존 없음
    params.yaml 로봇 한계만: 속도 예산, 힘 임계값, 섀시 지연
    skills/     motion/  base/  suction/  gripper/  sense/  conditions/  human/   # Level 1만
    macros/     이름 붙인 블록 조합 (YAML)
    events/     jsonl.py (실행 1회 = 파일 1개)
    editor/     schema.py (스킬 pydantic 스키마 → Blockly 블록 정의·툴박스)  server.py (편집기 서빙, 실행, 블록 하이라이트, 운영자 게이트)
    tools/      run.py  replay.py
  tasks/
    lges/                      ② 과제 — LGES 작업셀
      params.yaml (홈 자세, 컵 길이, z_min)  objects.yaml  stations.yaml  map/ (Nav2 지도, 태그 배치)
      skills/     ReadCode (동작), SafetyFloor, BEVInWindow (조건)
      perceive/   DetectObject (+ 나중에 MeasureTopZ, TagLocalize 등)
      types.py    PickResult  PlaceResult  ItemSpec  StackState  LegStation
      manip/      SuctionPick  SuctionPlace  ResolvePose  SlotPose  ItemSpec
      nav/        GoToStation, ParkDuringLeg
      memory/     ExpectedZ  DestStation  StackModel
      macros/     이름 붙인 블록 조합 (YAML)
      programs/   task3.yaml  task3_item.yaml  task2_case_to_bin.yaml  task1_lid.yaml  task4_box.yaml
  editor/                      Blockly 웹 편집기 (브라우저 쪽)
    index.html  blocks.js (schema.py가 생성)  to_yaml.js  from_yaml.js  run_panel.js
    (프로그램 저장 = programs/x.yaml + programs/x.blockly.json 한 쌍)
  DESIGN.md
```

import 방향은 한쪽뿐이다: `tasks/lges` → `task_studio`. 새 PoC는 `tasks/<이름>/`을 새로 만든다.

## 8. 마일스톤

| # | 내용 | 완료 기준 |
|---|---|---|
| M0 | ① 기본의 프레임워크: 스킬 계약, 노드 8개, YAML 로더, 가짜(mock) 로봇 + **Blockly 편집기 뼈대** (스킬 스키마 → 툴박스, 블록 → YAML, 실행 중 블록 하이라이트) | 로봇 없이 `pytest` 통과; 브라우저에서 트리를 그려 mock 로봇으로 돌리면 도는 블록이 색칠된다 |
| M1 | ① `task_studio/vega` 어댑터 (dexcontrol 직접, IK 포함) + 원자 스킬 전부; 편집기를 로봇 PC에서 서빙 | 로봇 PC 편집기에서 `--dry`(계획만, 안 움직임)로 Task 3 아이템 1개의 트리가 끝까지 평가되고, 운영자 입회 하에 원자 스킬 하나씩(`MoveJoints` 홈, `BaseMove` 10 cm, `SuctionOn/Off`)이 로봇에서 돈다 |
| M2 | ② `tasks/lges` Level 2 스킬 (감지, 흡착 pick/place, 스테이션, 예상 z) + `task3_item.yaml` | 운영자 입회 하에 아이템 1개 (`chassis_sequence` 메뉴 3의 한 사이클과 같은 결과) |
| M3 | 이벤트 JSONL + `replay.py` + 층 루프 `task3.yaml` | 한 실행의 로그 파일 하나로 편집기에서 실행을 되돌려 볼 수 있다 |
| M4 | Task 1/2/4를 새 블록 없이 조립 | 블록 분해가 맞았는지 검증 |
| M5 | 운영자 웹 게이트를 편집기 화면에 통합, 블록 타입 검사·표현식 블록 마무리 | 비개발자가 Task 2 변형을 그려서 돌린다 |

M1에서 로봇을 처음 움직일 때는 원자 스킬 하나씩, 운영자가 옆에 있을 때만. dexcontrol `Robot()`은 Task Studio 실행기가 만든다. ik_demo 프로세스와 동시에 띄우지 않는다.

## 9. 결정 사항

| 항목 | 결정 (2026-11-06) |
|---|---|
| 런타임 | 자체 미니 BT |
| 저장소·배포 | 별도 git, 로봇 PC에 clone 후 `git pull`, 시스템 python3.12 |
| 좌표계 | 스킬 API는 base_link, m / rad |
| 편집기 | Blockly, M0부터 |
| 프로그램 파일 | YAML이 실행·diff·손편집용 원본. 편집기는 블록 ↔ YAML 양방향 변환, 편집기 상태(배치·접힘·주석)는 Blockly JSON을 옆에 같이 저장 |
| 기록 | 이벤트 JSONL 하나. 기존 ik_demo 로그는 그대로, 에피소드 녹화기는 범위 밖 |
| ik_demo | 참고만. import·상속 없음, dexcontrol 위에 새로 짠다 |
| 지금 단계 | 구현 없이 컨셉 발표 |
