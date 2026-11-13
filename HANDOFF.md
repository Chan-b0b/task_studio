# Task Studio — 개발자용 설계 설명

로봇 과제를 블록으로 짜고 실행하는 프레임워크다. 이 문서는 구조와 규칙, 지금 되는 것과 안 되는 것, 다음에 할 일을 적는다.
기준일 2026-11-13. 대상 로봇은 Dexmate Vega.

**개발 범위는 기본 층(`task_studio/`)이다.** 어느 과제에나 쓰이는 기능만 만든다. 특정 과제의 블록, 모듈, 프로그램, 작업셀 숫자는 과제 담당자가 따로 채운다. 이 문서에는 과제 내용이 없고, 몰라도 된다.

## 1. 지금 상태

| 무엇 | 상태 |
|---|---|
| 런타임 (`task_studio/`) | 동작한다. 기본 층 시험 24개 통과 |
| 가짜 로봇 (`task_studio/mock/`) | 있다. 가상 시계로 돈다 |
| 실로봇 | **한 번도 돌리지 않았다.** Vega 어댑터(`task_studio/vega/`)는 비어 있다 |
| 편집기 (`task_studio_editor.html`) | 블록을 놓고 YAML을 내보낸다. YAML 읽어 들이기, 실행, 검사는 없다 |

지켜야 할 것.

- **실로봇을 처음 움직일 때는 블록 하나씩, 운영자가 옆에 있을 때만 한다.** dexcontrol `Robot()`은 Task Studio 실행기가 만든다. 로봇을 쓰는 다른 프로세스와 동시에 띄우지 않는다.
- **기본 층은 과제를 import 하지 않는다.** import 방향은 과제 → 기본 한쪽뿐이다.

## 2. 돌려 보기

```bash
uv venv && uv pip install pydantic pyyaml pytest
.venv/bin/python -m pytest tests/test_runtime.py                          # 기본 층 시험 24개
.venv/bin/python -m task_studio.tools.run <과제> <프로그램> --robot mock   # 과제 패키지가 있을 때
```

실행 1회마다 `runs/<프로그램>_<시각>.jsonl`에 이벤트가 한 줄씩 남는다.
시험 파일 안에 작은 프로그램들이 YAML 문자열로 들어 있다. 문법 예시로 읽기 좋다.

## 3. 구조: 두 층

| 층 | 폴더 | 들어가는 것 | 누가 |
|---|---|---|---|
| ① 기본 | `task_studio/` | 블록의 계약, 런타임, 로봇 파트 인터페이스, 과제와 무관한 블록, 기본 타입, 편집기 | 개발자 |
| ② 과제 | `tasks/<과제>/` | 작업셀을 알아야 하는 블록, 조건 블록, 모듈, 프로그램, 과제 타입, 작업셀 숫자 | 과제 담당자 |

```
task_studio/
  core/      skill.py(블록 계약)  typedefs.py(타입)  registry.py  context.py  blackboard.py(변수·식)  types.py(묶음 클래스)
  runtime/   loader.py(YAML → 트리, 실행 전 검사)  nodes.py(노드 6개, 갈림)  executor.py
  skills/    motion.py  sense.py                 # 기본 블록
  parts/     robot.py                            # 로봇 파트 인터페이스 (Protocol)
  mock/      robot.py                            # 가짜 로봇
  vega/      __init__.py                         # 실로봇 어댑터 자리 (비어 있음)
  types.yaml params.yaml tools/run.py
tests/test_runtime.py
```

과제 패키지가 기본 층에 내놓아야 하는 것은 셋이다. 기본 층은 이것만 안다.

| 과제가 내놓는 것 | 내용 |
|---|---|
| `registry()` | `task_studio.base_registry()`에 과제의 타입, 블록, 조건 블록, 모듈, 프로그램을 더해 돌려준다 |
| `params()` | `task_studio.base_params()`에 과제의 숫자를 덮어 돌려준다 |
| `mock_cell.make(params, clock)` | 가짜 로봇에 올릴 가짜 작업셀 (선택) |

## 4. 개념 여섯 가지

| 개념 | 한 줄 | 어디에 적나 |
|---|---|---|
| 동작 블록 | 로봇을 움직이거나 값을 낸다 | 파이썬 클래스 |
| 조건 | 예 / 아니오만 낸다 | 파이썬 클래스 (`Condition`) |
| 조건 블록 | 조건 + 걸리면 할 일 + 끝. 이름을 붙여 블록에 꽂는다 | YAML (`conditions:`) |
| 노드 | 블록을 엮는 상자 6개 | YAML |
| 모듈 | 블록을 엮어 이름 붙인 상자. 블록처럼 다시 쓴다 | YAML 파일 하나 |
| 타입 | 값이 무엇인가에 붙인 이름 | `types.yaml` |

바탕에 있는 원칙은 하나다. **"실패해서 이 동작"이 아니라 "이 조건에 걸려서 이 동작"으로 적는다.** 그래서 `Fail`, `Retry`, `Fallback` 노드가 없다.

### 4.1 기본 블록

| 종류 | 블록 |
|---|---|
| 시간이 걸리는 동작 | `MoveJoints` `MoveEE` `BaseMove` `Wait` |
| 한 번에 끝나는 동작 | `SuctionOn` `SuctionOff` `CaptureFrame` `Detect` `ReadWrench` `TareWrench` `OffsetPose` `GraspPose` |
| 운영자 | `OperatorDrive` (운영자가 섀시를 원하는 자리에 세운다) |
| 조건 | `ForceOver` `Sealed` `Timeout` `Reachable` |

아직 없는 기본 블록: `Navigate`(지도 좌표로 이동), `GripperMove`. `GraspPose`는 위에서 가운데를 잡는 경우만 된다.

### 4.2 노드 여섯 개

| 노드 | 하는 일 | 적는 법 |
|---|---|---|
| `Sequence` | 위에서 아래로 하나씩 | `Sequence: [블록, 블록]` |
| `Parallel` | 동시에. `all`은 다 끝나면, `any`는 하나가 끝나면 끝 | `Parallel: {policy: all, children: […]}` |
| `Loop` | `n`번. `n`이 없으면 안쪽 `If`가 `again`을 낼 때마다 처음으로 | `Loop: {n: 3, body: […]}` |
| `If` | 식이나 조건을 한 번 보고 갈린다 | `If: {expr: "$left >= 1", then: again, else: continue}` |
| `Gate` | 운영자에게 묻고 고른 대로 갈린다 | `Gate: {prompt: "…", choices: {go: continue, stop: stop}}` |
| `Set` | 변수에 값을 적는다 | `Set: {$left: "$left - 1"}` |

"될 때까지 되풀이"는 노드로 만들지 않고 파이썬 블록 안에서 한다 (예: `OperatorDrive`).

### 4.3 갈림

본류(위에서 아래로 가는 흐름)를 벗어나는 곳은 세 군데뿐이다.

| 갈리는 곳 | 언제 보나 |
|---|---|
| 가드 (블록에 꽂은 조건 블록) | 블록이 도는 동안 |
| `If` | 그 자리에서 한 번 |
| `Gate` | 운영자가 고를 때 |

갈린 가지의 끝은 세 가지다.

| 끝 | 적는 법 | 뜻 |
|---|---|---|
| 본류 계속 | `continue` | 가지의 블록을 하고 본류의 다음 블록으로 간다 |
| 멈춤 | 안 적거나 `stop` | 가지의 블록을 하고 **프로그램 전체**가 그 자리에서 끝난다. 상자가 몇 겹이든 같다 |
| 상자 처음으로 | `again` | `Loop` 상자 안에서만. 상자의 첫 블록으로 돌아간다 |

### 4.4 조건 블록

같은 반응을 여러 블록에 되풀이해 적지 않으려고 둔다. 한 번 정의하고 이름으로 꽂는다.

```yaml
conditions:
  닿음:      {check: {ForceOver: {threshold: 10}}, then: continue}                      # 멈추고 본류 계속
  세게_닿음:  {check: {ForceOver: {threshold: 20}}, then: [SuctionOff: {}]}              # 끝을 안 적음 = 하고 멈춤
  시간_초과:  {check: Timeout}                                                           # 초는 꽂는 곳에서 준다

# 쓰는 곳
- MoveEE: {pose: {z: 0.80}, keep_xy: true, guards: [닿음, 세게_닿음, {시간_초과: {s: 8}}], out: $touch}
```

| 꽂는 곳 | 조건을 보는 때 |
|---|---|
| 시간이 걸리는 블록 | 도는 동안 매 tick |
| 한 번에 끝나는 블록 | 끝난 직후에 한 번 |
| 파이썬 블록, 모듈 | 안에서 부르는 블록 전부. 걸리면 그 블록을 접고 조건 블록의 갈림으로 간다 |

- `timeout` 입력은 없다. 시간 제한도 조건 블록 하나다.
- 걸린 조건 블록의 이름은 블록 결과의 `stopped_by`에 들어간다. 끝까지 갔으면 `reached`.
- 목표에 닿는 순간 조건도 걸리면 조건이 이긴다.

### 4.5 모듈

```yaml
# touch_down.yaml — 모듈 하나가 파일 하나
name: TouchDown
inputs:  {pose: Pose, floor_z: Height}
outputs: {contact_z: {type: Height, value: $touch.pose_at_stop.z}}
main:
  Sequence:
    - MoveEE: {pose: $pose}
    - MoveEE: {pose: {z: $floor_z}, keep_xy: true, guards: [닿음], out: $touch}

# 쓰는 곳
- TouchDown: {pose: $target, floor_z: 0.75, out: $td}
- Set: {$top: $td.contact_z}
```

| 무엇 | 규칙 |
|---|---|
| 입력 칸 | 이름과 타입을 반드시 적는다. 없으면 `inputs: {}`. 기본값은 `{type: Count, default: 0}` |
| 출력 칸 | 이름, 타입, 값을 적는다. 값 하나만 낼 때는 `outputs: {type: Pose, value: $p}` |
| 범위 | 모듈 안에서는 입력 칸과 `$params`만 보인다. 부른 쪽 변수는 안 보인다 |
| 잇기 | `out: $td`로 이름을 붙이고 뒤에서 `$td.contact_z`로 꺼낸다 |
| 프로그램 | 프로그램도 모듈이다. `on_abort:`를 적으면 정지 요청·E-stop 때 그 트리가 돈다 |

### 4.6 타입

타입은 **값이 무엇인가**에 붙인 이름이다. 칸에 `number` `text` `list`를 직접 적지 않는다(`bool`만 그대로 쓴다). 블록마다 결과 타입(`PickResult` 같은 것)은 만들지 않는다.

```yaml
# types.yaml — 한 줄이 타입 하나. 파이썬 없이 새 타입을 만든다
Height:     {base: number, unit: m, desc: 높이 z}
Option:     {base: text, choices: [top, side]}
Detections: {base: list, of: ObjectPose}
Pose:       {fields: {x: Distance, y: Distance, z: Height, roll: Angle, pitch: Angle, yaw: Angle}}   # 묶음
```

| 바탕 | 기본 타입 (`task_studio/types.yaml`) |
|---|---|
| 숫자 | `Height` `Distance` `Angle` `Count` `Seconds` `Force` `Torque` `Speed` `Ratio` |
| 글자 | `PartName` `ObjectClass` `StationName` `Message` `Option` `StopReason` |
| 목록 | `JointAngles` `Detections` |
| 묶음 | `Pose` `ObjectPose` `Wrench` `Frame` `JointState` `Station` `Decision` `MoveResult` |

과제는 자기 `types.yaml`로 타입을 더한다. 전부 base_link 기준, m / rad.

| 검사 | 때 | 내용 |
|---|---|---|
| 타입 이름 | 실행 전 | `$변수` 하나를 그대로 꽂았고 그 타입을 알면 칸의 타입과 이름이 같아야 한다. `Height`와 `Distance`는 다르다 |
| 통과시키는 것 | — | 직접 적은 숫자·글자, 계산식(`"$z + 0.02"`), `$params.*`, `Set`으로 계산해 만든 변수 |
| 값의 바탕 | 실행 중 | 모듈에 들어갈 때와 나올 때 숫자인가, 글자인가, 묶음인가를 본다. `choices`가 있으면 그 안에 있는지도 본다 |

묶음을 담는 pydantic 클래스가 있으면(`Pose` 등) `{z: 1.1}`처럼 적어도 그 클래스로 바뀐다.

## 5. 블록 하나 만들기

```python
class MoveEE(Action):                     # 시간이 걸리면 Action, 한 번에 끝나면 Skill, 예/아니오면 Condition
    name, part = "MoveEE", "팔"
    slots, gives = {"pose": "Pose", "arm": "PartName", "straight": "bool", "keep_xy": "bool", "speed": "Speed"}, "MoveResult"

    class Input(BaseModel):               # pydantic 이 값을 검사한다
        pose: Pose
        arm: str = "left"
        straight: bool = False
        keep_xy: bool = False
        speed: float | None = None

    @classmethod
    def requires_for(cls, inp):           # 쓰는 파트. Parallel 에서 겹치면 오류
        return frozenset({f"{inp.arm}_arm"})

    def run(self, ctx, inp):
        arm = ctx.robot.arm(inp.arm)
        motion = arm.move_ee(inp.pose, straight=inp.straight, speed=…)   # 파트는 시작만 한다
        stopped_by = self.drive(ctx, motion)                              # 매 tick: 정지 요청 → 가드 → 한 걸음
        return self.Output(stopped_by=stopped_by, pose_at_stop=arm.ee_pose())
```

| 규칙 | 내용 |
|---|---|
| `slots` | `Input`의 모든 필드에 타입 이름을 적는다. 빠지면 레지스트리를 만들 때 오류 |
| `gives` | 출력의 타입 이름. 내는 것이 없으면 `None` |
| 값 하나를 내는 블록 | `return Value(value=…)`. `out: $x`에 그 값이 그대로 들어간다 |
| 실패 | `Result(status="fail", reason="…")`를 돌려주면 프로그램이 멈춘다 |
| 긴 동작 | `Action.drive()`를 쓴다. 직접 루프를 돌리면 매 tick `ctx.check()`와 `ctx.poll()`을 부른다 |
| 다른 블록 부르기 | `ctx.call("BaseMove", dy=0.1)`. 파트 점유, 이벤트, 겉에 꽂힌 가드가 똑같이 걸린다 |
| 운영자에게 묻기 | `ctx.ask(prompt, ["move", "continue", "stop"])` |
| 실행 내내 들고 있는 값 | `ctx.store` (dict). 블록이 장부처럼 쓴다 |
| 조건 | `check(ctx, inp) → bool`. 가드로 꽂히면 블록 시작 직전에 `arm()`이 한 번 불린다 (기준값, 시작 시각) |
| 등록 | 모듈 파일에 클래스를 두면 `reg.add_module()`이 찾는다 |

## 6. 런타임이 하는 일

| 단계 | 내용 | 파일 |
|---|---|---|
| 1. 등록 | 타입 → 블록 → 조건 블록 → 모듈·프로그램을 레지스트리에 넣는다 | `task_studio/__init__.py`, `core/registry.py` |
| 2. 짓기 | 프로그램에서 부르는 모듈과 조건 블록의 갈림까지 전부 트리로 짓는다 | `runtime/loader.py` |
| 3. 실행 전 검사 | 모르는 블록, 없는 칸, 빠진 칸, 모르는 타입, 다른 타입의 변수, 자기를 부르는 모듈. **하나라도 걸리면 아무것도 움직이지 않는다** | `runtime/loader.py` |
| 4. 실행 | 스레드 하나, 블록은 블로킹. `Parallel`만 스레드를 나눈다 | `runtime/executor.py`, `nodes.py` |
| 5. 끝 | 결과는 `ok` / `stopped` / `aborted` | `runtime/executor.py` |

| 끝나는 까닭 | 결과 | `on_abort` |
|---|---|---|
| 본류를 끝까지 감 | `ok` | 안 돈다 |
| 갈림의 끝이 멈춤, 또는 블록이 실패 | `stopped` | 안 돈다. 로봇은 그 자리에 선다 |
| 정지 요청, E-stop, 프로그램 오류 | `aborted` | 돈다 |

- **변수**: `$이름.칸`. `$`가 든 문자열은 식으로 계산한다 (`"$z + 0.02"`). `$params`는 어디서나 보인다.
- **이벤트**: `run_start` `node_enter` `node_exit` `guard` `branch` `gate` `decision` `block_failed` `run_end`. 노드 id는 부른 자리의 경로라서 같은 모듈을 두 번 불러도 구분된다.
- **로봇 파트**: `parts/robot.py`의 Protocol. 블록은 이 인터페이스만 쓴다. 가짜 로봇과 Vega 어댑터가 같은 인터페이스를 채운다.

## 7. 다음에 할 일

| 순서 | 무엇 | 메모 |
|---|---|---|
| 1 | **Vega 어댑터** | `parts/robot.py`의 인터페이스를 그대로 채운다. 채울 목록은 `task_studio/vega/__init__.py`에 있다. `MoveJoints`로 홈 자세부터 |
| 2 | 실로봇에서 기본 블록 하나씩 | 운영자 입회. `params.yaml`의 숫자를 로봇에서 확인한다 |
| 3 | 추가 개발 안 (8절) | 설정 파일, 실행 서버, 이어 하기, 블록마다 볼거리 |
| 4 | 편집기 | YAML 읽어 들이기, 런타임의 실행 전 검사 붙이기, 타입이 맞는 변수만 보여 주기. 블록 목록을 파일 안에 적지 말고 레지스트리(`Registry.catalog()`)에서 받아 오기 |
| 5 | 없는 기본 블록 | `Navigate`, `GripperMove`, `GraspPose`의 나머지 경우 |

아직 확정하지 않은 결정. 구현하다 걸리면 물어본다.

| 무엇 | 지금 | 물음 |
|---|---|---|
| 블록 실패 | 프로그램이 멈추고 `on_abort`는 안 돈다 | 실패도 `on_abort`를 돌게 할지 |
| 물건을 든 채 멈춤 | 그 자리에 둔다 | 든 채 멈췄을 때 할 일을 정할지 |
| 계산해 만든 변수의 타입 | 모른다고 보고 통과시킨다 | 변수에 타입을 적게 할지 |
| 조건 블록의 "걸리면 할 일" | 걸린 자리의 변수를 그대로 본다 | 걸린 블록의 결과(`$hit`)를 넘겨줄지 |

## 8. 추가 개발 안 (아직 설계만)

| # | 요구 | 지금 구조에서 붙는 자리 |
|---|---|---|
| 1 | 로봇 하드웨어 설정을 밖에서 바꿀 수 있게 (예: IK solver 교체) | `parts/robot.py` 인터페이스 뒤. 어댑터를 설정 파일로 조립한다 |
| 2 | 화면에서 블록·모듈마다 정보 보이기 (예: 비전 블록은 지금 이미지 위의 검출 결과, `MoveEE`는 URDF가 움직이는 미리보기) | 블록이 내는 "볼거리"를 이벤트로 흘린다 |
| 3 | 화면에서 로봇 실행 | 로봇 PC에 실행 서버. 편집기는 그 서버에 붙는다 |
| 4 | 멈춘 곳에서 이어 하기, 블록 A부터 B까지만 하기, 블록 끄기 | 실행기에 "어디서 어디까지"와 변수 스냅샷 |

### 8.1 하드웨어 설정을 밖으로

설정 파일 하나(`robot.yaml`)가 파트마다 어떤 구현을 쓸지 고른다. 코드를 고치지 않고 파일만 바꾼다.

```yaml
# 예시 — task_studio/vega/robot.yaml
arm:
  ik:         {use: task_studio.vega.ik.PinkSolver, damping: 0.05}     # 다른 solver 로 바꾸려면 이 줄만
  trajectory: {use: task_studio.vega.traj.RuckigPlanner}
chassis:      {use: task_studio.vega.chassis.OdomChassis}
camera:       {head: {use: task_studio.vega.zed.ZedCamera}}
```

- 어댑터 안쪽에 작은 인터페이스를 더 둔다: `IKSolver.solve(pose, seed) → q`, `TrajectoryPlanner.plan(q0, q1, speed) → Motion`. 블록과 `parts/robot.py`는 바뀌지 않는다.
- 숫자(속도, 한계)는 지금처럼 `params.yaml`, 구현 선택은 `robot.yaml`로 나눈다.

### 8.2 블록마다 보이는 정보

| 때 | 무엇을 보이나 | 어떻게 |
|---|---|---|
| 실행 전 (미리보기) | `MoveEE`: 지금 자세에서 목표까지 URDF가 움직이는 모습. 비전 블록: 지금 카메라 이미지 위의 검출 결과 | 블록에 `preview(ctx, inp)`를 선택으로 둔다. 로봇을 움직이지 않고 계획·검출만 한다 |
| 실행 중·후 | 실제로 찍힌 이미지와 검출, 실제 간 궤적, 걸린 조건 블록 | 블록이 `ctx.show(kind, …)`로 볼거리를 내면 이벤트(`artifact`)로 기록된다 |

- 볼거리의 종류를 몇 개로 정한다: `image`(+ 상자·점), `trajectory`(관절 각도 열), `pose`, `plot`(힘 그래프), `text`. 화면은 종류마다 보는 법 하나만 가진다.
- URDF 미리보기는 브라우저에서 URDF를 그리고 `trajectory`를 재생한다. 시뮬레이터를 따로 돌리지 않는다.
- 모듈을 누르면 안쪽 블록들의 볼거리를 차례로 모아 보인다.

### 8.3 화면에서 로봇 실행

편집기는 지금 파일 하나짜리 HTML이라 로봇에 닿지 못한다. 로봇 PC에 작은 서버를 둔다.

| 서버가 하는 일 | 내용 |
|---|---|
| 프로그램 받기·검사 | YAML을 받아 런타임의 실행 전 검사를 돌리고 결과를 돌려준다 |
| 블록 목록 주기 | `Registry.catalog()` — 블록, 칸, 타입. 편집기의 왼쪽 목록이 여기서 온다 |
| 실행·정지 | 실행, 일시정지, 정지(`request_stop`). 한 번에 하나만 |
| 이벤트 흘리기 | WebSocket으로 이벤트를 보낸다 → 화면이 도는 블록을 칠한다 |
| 운영자 답 | `Gate`·`ctx.ask`의 물음을 화면에 띄우고 답을 받는다 (`Operator` 인터페이스의 웹 구현) |

안전: 정지 버튼은 항상 보인다. 실행 전에 "가짜 로봇 / 실로봇"을 고른다. 실로봇은 운영자 입회 확인을 받는다. 속도 배율을 화면에서 낮출 수 있다.

### 8.4 이어 하기 · 구간 실행 · 블록 끄기

어려운 점은 **상태**다. 중간부터 하려면 그 앞에서 만들어진 변수와 로봇의 실제 상태가 맞아야 한다.

| 기능 | 방법 | 주의 |
|---|---|---|
| 멈춘 곳에서 이어 하기 | 블록이 끝날 때마다 변수와 `ctx.store`를 스냅샷으로 남긴다. 이어 할 때 멈춘 블록 직전 스냅샷을 되살리고 그 블록부터 돈다 | 노드 id가 부른 자리의 경로라서 `Loop` 몇 번째, 어느 모듈 안인지까지 되살릴 수 있다. 로봇의 실제 상태(물건을 들고 있나)는 되살릴 수 없으니 운영자에게 확인을 받는다 |
| A부터 B까지만 | 시작 블록 A와 끝 블록 B를 고른다. A에 필요한 변수는 지난 실행의 스냅샷에서 가져오거나 화면에서 직접 적는다 | 실행 전 검사가 "A는 `$target`이 필요한데 없다"를 알려 준다 (타입 검사가 쓰는 변수 추적을 그대로 쓴다) |
| 블록 끄기 | 블록에 `disabled: true`. 실행기는 건너뛴다 | 꺼진 블록이 만들던 변수를 뒤에서 쓰면 실행 전 검사에서 알려 준다 |

정해야 할 것.

- 이어 하기를 할 때 멈춘 블록을 **다시** 할지, 그 **다음** 블록부터 할지 (운영자가 그때 고르게 하는 안).
- `Parallel` 안에서 멈췄을 때: 상자 전체를 처음부터 다시 하는 것으로 단순하게 할지.
- 구간 실행에서 조건 블록이 "멈춤"으로 끝나면 구간만 끝낼지 (지금 규칙은 프로그램 전체가 끝난다).

### 8.5 순서 제안

| 순서 | 무엇 | 까닭 |
|---|---|---|
| 1 | 8.1 설정 파일 + Vega 어댑터 | 어댑터를 만들 때 같이 하는 것이 싸다 |
| 2 | 8.3 실행 서버 (가짜 로봇으로 먼저) | 8.2와 8.4가 둘 다 이 서버 위에 올라간다 |
| 3 | 8.4 블록 끄기 → 구간 실행 → 이어 하기 | 쉬운 것부터. 실로봇 디버깅에 바로 쓰인다 |
| 4 | 8.2 볼거리 (이미지 + 검출 → URDF 미리보기) | 종류를 하나씩 늘린다 |
