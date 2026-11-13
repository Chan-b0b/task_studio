"""런타임 규칙 시험: 조건 블록(본류 계속 / 하고 계속 / 멈춤), 모듈 가드, If, Gate, Loop, Parallel, 모듈 범위, 식."""
import pytest

import task_studio
from task_studio.core.blackboard import Blackboard, ProgramError, Unset, evaluate
from task_studio.core.context import EventLog, ScriptedOperator, VirtualClock
from task_studio.core.types import Decision
from task_studio.mock.robot import MockRobot, World
from task_studio.runtime.executor import Executor


class Table(World):
    def contact_ee_z(self, wx, wy, holding):
        return 0.90


CONDS = """
conditions:
  곧_끝:      {check: {Timeout: {s: 1}}, then: continue}
  하고_계속:   {check: {Timeout: {s: 1}}, then: [Set: {$side: "1"}, continue]}
  멈춤:       {check: {Timeout: {s: 1}}}
  하고_멈춤:   {check: {Timeout: {s: 1}}, then: [Set: {$side: "1"}]}
  시간_초과:   {check: Timeout}
  닿음:       {check: {ForceOver: {threshold: 10.0}}, then: continue}
"""


def run(tmp_path, main: str, extra: dict[str, str] | None = None, inputs=None, world=None, answers=None):
    reg = task_studio.base_registry()
    for name, text in {**(extra or {}), "prog": CONDS + main}.items():
        if "inputs:" not in text:
            text = "inputs: {}\n" + text
        (tmp_path / f"{name}.yaml").write_text(text, encoding="utf-8")
        reg.add_yaml(tmp_path / f"{name}.yaml")
    clock = VirtualClock()
    ex = Executor(reg, MockRobot(clock, world or World()), task_studio.base_params(),
                  ScriptedOperator(answers), EventLog(clock=clock), clock)
    return ex, ex.run("prog", inputs)


def ran(ex, type_):
    return [e for e in ex.events.of("node_exit") if e["type"] == type_]


PROG = """
main:
  Sequence:
    - Wait: {s: 5, guards: [%s]}
    - Set: {$after: "1"}
"""


# ---------------------------------------------------------------- 조건 블록
def test_condition_block_continue_keeps_main_stream(tmp_path):
    ex, r = run(tmp_path, PROG % "곧_끝")
    assert r.status == "ok" and ex.scope.get("after") == 1
    assert ran(ex, "Wait")[0]["stopped_by"] == "곧_끝"
    assert ex.clock.now() == pytest.approx(1.0, abs=0.02)        # 5 초를 다 기다리지 않았다


def test_condition_block_does_its_steps_then_continues(tmp_path):
    ex, r = run(tmp_path, PROG % "하고_계속")
    assert r.status == "ok" and ex.scope.get("side") == 1 and ex.scope.get("after") == 1


def test_condition_block_without_end_stops_the_program(tmp_path):
    ex, r = run(tmp_path, PROG % "멈춤")
    assert r.status == "stopped" and r.reason == "멈춤" and not ex.scope.has("after")
    ex, r = run(tmp_path, PROG % "하고_멈춤")
    assert r.status == "stopped" and ex.scope.get("side") == 1 and not ex.scope.has("after")


def test_stop_ends_the_whole_program_through_boxes(tmp_path):
    # 모듈 안의 Loop 안에서 멈춰도 바깥 본류까지 전부 끝난다
    ex, r = run(tmp_path, "main:\n  Sequence:\n    - Box: {}\n    - Set: {$after: \"1\"}\n",
                extra={"Box": "inputs: {}\nmain:\n  Sequence:\n    - Loop:\n        n: 3\n        body:\n          - Wait: {s: 5, guards: [멈춤]}\n"})
    assert r.status == "stopped" and not ex.scope.has("after") and len(ran(ex, "Wait")) == 1


def test_condition_value_given_at_the_use_site(tmp_path):
    ex, r = run(tmp_path, "main:\n  Sequence:\n    - BaseMove: {dy: 1.0, speed: 0.1, guards: [{시간_초과: {s: 2.0}}]}\n")
    assert r.status == "stopped" and r.reason == "시간_초과"
    assert ex.robot.chassis.y == pytest.approx(0.2, abs=0.01)    # 2 초 동안 간 만큼에서 멈췄다


def test_condition_on_a_module_covers_every_motion_inside(tmp_path):
    ex, r = run(tmp_path, "main:\n  Sequence:\n    - Box: {guards: [곧_끝]}\n    - Set: {$after: \"1\"}\n",
                extra={"Box": "main:\n  Sequence:\n    - Wait: {s: 5}\n    - Wait: {s: 5}\n"})
    assert r.status == "ok" and ex.scope.get("after") == 1
    assert [e["stopped_by"] for e in ran(ex, "Wait")] == ["곧_끝", "곧_끝"]
    assert ex.clock.now() == pytest.approx(2.0, abs=0.05)


def test_force_condition_stops_descent_at_contact(tmp_path):
    ex, r = run(tmp_path, """
main:
  Sequence:
    - MoveEE: {pose: {z: 0.80}, keep_xy: true, speed: 0.08, guards: [닿음], out: $touch}
""", world=Table())
    assert r.status == "ok"
    touch = ex.scope.get("touch")
    assert touch.stopped_by == "닿음" and 0.894 < touch.pose_at_stop.z < 0.898   # 10 N = 3.3 mm 눌림


def test_block_failure_stops_the_program(tmp_path):
    ex, r = run(tmp_path, "main:\n  Sequence:\n    - MoveEE: {pose: {x: 2.0, y: 0.0, z: 1.0}}\n    - Set: {$after: \"1\"}\n")
    assert r.status == "stopped" and r.reason == "unreachable" and not ex.scope.has("after")


# ---------------------------------------------------------------- If / Gate / Loop
def test_if_branch_endings(tmp_path):
    prog = """
inputs: {n: Count}
main:
  Sequence:
    - If: {expr: "$n == 1", then: [Set: {$did: "1"}, continue], else: continue}
    - If: {expr: "$n == 2", then: [Set: {$bye: "1"}]}
    - If: {expr: "$n == 3", then: stop}
    - Set: {$after: "1"}
"""
    ex, r = run(tmp_path, prog, inputs={"n": 1})
    assert r.status == "ok" and ex.scope.get("did") == 1 and ex.scope.get("after") == 1
    ex, r = run(tmp_path, prog, inputs={"n": 2})                 # 끝을 안 적은 가지 = 하고 멈춤
    assert r.status == "stopped" and ex.scope.get("bye") == 1 and not ex.scope.has("after")
    ex, r = run(tmp_path, prog, inputs={"n": 3})
    assert r.status == "stopped" and r.reason == "$n == 3"


def test_gate_choices_branch(tmp_path):
    prog = """
main:
  Sequence:
    - Gate:
        prompt: "어디로?"
        out: $d
        choices:
          left:  [Set: {$went: "'left'"}, continue]
          right: [Set: {$went: "'right'"}, continue]
          stop:  stop
    - Set: {$after: "1"}
on_abort:
  Sequence:
    - MoveJoints: {group: head, q: [0.0, 0.0]}
"""
    ex, r = run(tmp_path, prog, answers=["right"])
    assert r.status == "ok" and ex.scope.get("went") == "right" and ex.scope.get("d").choice == "right"
    ex, r = run(tmp_path, prog, answers=["stop"])                # 멈춤은 on_abort 를 돌지 않는다
    assert r.status == "stopped" and not ex.scope.has("after") and not ran(ex, "MoveJoints")


def test_stop_request_runs_on_abort(tmp_path):
    prog = """
inputs: {}
main:
  Sequence:
    - Gate: {prompt: "계속?", choices: {go: continue}}
    - Wait: {s: 5}
on_abort:
  Sequence:
    - MoveJoints: {group: head, q: [0.0, 0.0]}
"""
    reg = task_studio.base_registry()
    (tmp_path / "prog.yaml").write_text(prog, encoding="utf-8")
    reg.add_yaml(tmp_path / "prog.yaml")
    clock = VirtualClock()
    ex = Executor(reg, MockRobot(clock, World()), task_studio.base_params(), None, EventLog(clock=clock), clock)
    ex.operator = ScriptedOperator([lambda *_: (ex.request_stop(), "go")[1]])
    r = ex.run("prog")
    assert r.status == "aborted" and r.reason == "stop" and ran(ex, "MoveJoints")


def test_loop_n_and_again(tmp_path):
    ex, r = run(tmp_path, """
main:
  Sequence:
    - Set: {$sum: "0", $k: "0"}
    - Loop: {n: 3, body: [Set: {$sum: "$sum + 1"}]}
    - Loop:
        - Set: {$k: "$k + 1"}
        - If: {expr: "$k < 4", then: again, else: continue}
""")
    assert r.status == "ok" and ex.scope.get("sum") == 3 and ex.scope.get("k") == 4
    ex, r = run(tmp_path, "main:\n  Sequence:\n    - If: {expr: \"1 == 1\", then: again}\n")
    assert r.status == "aborted" and "again" in r.reason         # Loop 밖의 again 은 프로그램 오류


def test_parallel_runs_together_and_rejects_shared_part(tmp_path):
    ex, r = run(tmp_path, """
main:
  Parallel:
    - BaseMove: {dy: 0.2, speed: 0.1}
    - MoveJoints: {group: head, q: [0.0, 0.5]}
""")
    assert r.status == "ok" and ex.robot.chassis.y == pytest.approx(0.2) and ex.robot.joints.q("head") == [0.0, 0.5]
    ex, r = run(tmp_path, """
main:
  Parallel:
    - BaseMove: {dy: 0.2, speed: 0.1}
    - BaseMove: {dx: 0.2, speed: 0.1}
""")
    assert r.status == "aborted" and "파트 충돌" in r.reason


def test_parallel_any_cancels_the_slower_child(tmp_path):
    ex, r = run(tmp_path, """
main:
  Parallel:
    policy: any
    children:
      - Wait: {s: 0.5}
      - BaseMove: {dy: 5.0, speed: 0.1}
""")
    assert r.status == "ok" and ex.robot.chassis.y < 1.0


# ---------------------------------------------------------------- 모듈
def test_module_sees_only_its_inputs_and_gives_outputs(tmp_path):
    ex, r = run(tmp_path, """
main:
  Sequence:
    - Set: {$secret: "7"}
    - Double: {x: 21, out: $d}
    - Lift: {to: {z: 1.2}, out: $z}
    - Peek: {}
""", extra={
        "Double": "inputs: {x: Count}\noutputs: {twice: {type: Count, value: $y}, big: {type: bool, value: \"$y > 40\"}}\nmain:\n  Sequence:\n    - Set: {$y: \"$x * 2\"}\n",
        "Lift": "inputs: {to: Pose}\noutputs: {type: Height, value: $to.z}\nmain:\n  Sequence: []\n",        # dict → Pose, 값 하나를 낸다
        "Peek": "inputs: {}\nmain:\n  Sequence:\n    - If: {expr: \"$secret == 7\", then: continue}\n",
    })
    d = ex.scope.get("d")
    assert d.twice == 42 and d.big is True and not ex.scope.has("y") and ex.scope.get("z") == 1.2
    assert r.status == "stopped" and r.reason == "unset $secret"  # 부른 쪽 변수는 모듈 안에서 안 보인다


def test_module_input_slots_are_checked(tmp_path):
    box = {"Box": "inputs: {pose: Pose, n: {type: Count, default: 1}}\nmain:\n  Sequence: []\n"}
    for call, why in [("Box: {}", "빠진 칸"), ("Box: {pose: {z: 1.0}, m: 2}", "없는 칸"),
                      ("Box: {pose: 3}", "Pose(struct) 이어야"), ("Box: {pose: {z: 1.0}, n: abc}", "Count(number) 이어야")]:
        ex, r = run(tmp_path, "main:\n  Sequence:\n    - " + call + "\n", extra=box)
        assert r.status == "aborted" and why in r.reason, (call, r.reason)
    ex, r = run(tmp_path, "main:\n  Sequence:\n    - Box: {pose: {z: 1.0}}\n", extra=box)
    assert r.status == "ok"
    (tmp_path / "NoSlots.yaml").write_text("main:\n  Sequence: []\n", encoding="utf-8")
    with pytest.raises(ProgramError, match="inputs"):            # 입력 칸을 안 적은 모듈은 읽을 때 오류
        task_studio.base_registry().add_yaml(tmp_path / "NoSlots.yaml")


def test_python_block_calls_other_blocks(tmp_path):
    # OperatorDrive: 운영자가 move 를 낼 때마다 BaseMove 를 부른다
    ex, r = run(tmp_path, "main:\n  Sequence:\n    - OperatorDrive: {prompt: \"세운다\"}\n",
                answers=[Decision(choice="move", args={"dy": 0.3}), "continue"])
    assert r.status == "ok" and ex.robot.chassis.y == pytest.approx(0.3)
    assert [e["node"] for e in ran(ex, "BaseMove")] == ["prog.Sequence[0].OperatorDrive>BaseMove"]
    ex, r = run(tmp_path, "main:\n  Sequence:\n    - OperatorDrive: {}\n", answers=["stop"])
    assert r.status == "stopped" and r.reason == "operator_stop"


# ---------------------------------------------------------------- 프로그램 오류 · 식
def test_program_mistakes_are_caught_before_anything_moves(tmp_path):
    first = "    - BaseMove: {dy: 0.2, speed: 0.1}\n"
    for bad, extra in [
            ("    - NoSuchBlock: {}\n", None),
            ("    - Sealed: {}\n", None),                                      # 조건을 동작 자리에
            ("    - MoveEE: {pose: {z: 1.0}, sped: 0.1}\n", None),             # 없는 입력
            ("    - Wait: {s: 1, guards: [없는_조건]}\n", None),                # 모르는 조건 블록
            ("    - Wait: {s: 1, guards: [{곧_끝: {sec: 1}}]}\n", None),        # 조건 블록에 없는 값
            ("    - If: {expr: \"1 == 1\", then: later}\n", None),             # 모르는 끝
            ("    - Box: {}\n", {"Box": "main:\n  Sequence:\n    - NoSuchBlock: {}\n"}),   # 모듈 안쪽
    ]:
        ex, r = run(tmp_path, "main:\n  Sequence:\n" + first + bad, extra=extra)
        assert r.status == "aborted" and r.reason.startswith("program_error"), bad
        assert ex.robot.chassis.y == 0.0 and not ran(ex, "BaseMove"), bad      # 앞의 블록도 돌지 않았다


def test_expressions_are_arithmetic_only():
    bb = Blackboard({"a": {"b": 3}, "s": "case"})
    assert evaluate("$a.b * 2 + 1", bb) == 7
    assert evaluate("$s == 'case' and $a.b <= 3", bb) is True
    for bad in ["__import__('os')", "$a.b.__class__", "open('x')", "[x for x in (1,)]"]:
        with pytest.raises((ProgramError, Unset)):
            evaluate(bad, bb)


# ---------------------------------------------------------------- 가드는 어느 블록에나 꽂는다
def test_condition_on_an_instant_block_is_checked_right_after_it(tmp_path):
    # 한 번에 끝나는 블록(SuctionOn): 끝난 직후에 조건을 한 번 본다
    ex, r = run(tmp_path, "main:\n  Sequence:\n    - SuctionOn: {guards: [{하고_계속: {s: 0}}]}\n    - Set: {$after: \"1\"}\n")
    assert r.status == "ok" and ex.scope.get("side") == 1 and ex.scope.get("after") == 1
    assert ran(ex, "SuctionOn")[0]["stopped_by"] == "하고_계속"


def test_condition_on_a_python_block_covers_the_blocks_it_calls(tmp_path):
    # 파이썬 블록(OperatorDrive)에 꽂으면 그 안에서 부른 BaseMove 가 걸린다 → 블록을 접고 조건 블록의 갈림으로
    ex, r = run(tmp_path, "main:\n  Sequence:\n    - OperatorDrive: {prompt: p, guards: [{시간_초과: {s: 0.5}}]}\n    - Set: {$after: \"1\"}\n",
                answers=[Decision(choice="move", args={"dy": 5.0}), "continue"])
    assert r.status == "stopped" and r.reason == "시간_초과" and not ex.scope.has("after")
    assert 0.0 < ex.robot.chassis.y < 5.0                        # 가다가 멈췄다


# ---------------------------------------------------------------- 타입: 값이 무엇인가에 붙인 이름
def test_slot_types_are_names_not_primitives(tmp_path):
    for bad in ("number", "text", "list", "any"):               # 칸에 숫자·글자·목록을 직접 적지 않는다
        ex, r = run(tmp_path, "main:\n  Sequence:\n    - Box: {x: 1}\n", extra={"Box": "inputs: {x: %s}\nmain:\n  Sequence: []\n" % bad})
        assert r.status == "aborted" and "모르는 타입" in r.reason
    (tmp_path / "NoType.yaml").write_text("inputs: {}\noutputs: {z: $a}\nmain:\n  Sequence: []\n", encoding="utf-8")
    with pytest.raises(ProgramError, match="type"):              # 출력 칸에도 타입을 적는다
        task_studio.base_registry().add_yaml(tmp_path / "NoType.yaml")


def test_variable_of_another_type_is_caught_before_anything_moves(tmp_path):
    mods = {"Up": "inputs: {z: Height}\nmain:\n  Sequence:\n    - Set: {$seen: \"1\"}\n",
            "Mk": "inputs: {}\noutputs: {gap: {type: Distance, value: $g}, top: {type: Height, value: $h}}\nmain:\n  Sequence:\n    - Set: {$g: \"0.1\", $h: \"0.9\"}\n"}
    head = "main:\n  Sequence:\n    - BaseMove: {dy: 0.3}\n    - Mk: {out: $m}\n"
    ex, r = run(tmp_path, head + "    - Up: {z: $m.gap}\n", extra=mods)                 # Distance 변수를 Height 칸에
    assert r.status == "aborted" and "Height 인데" in r.reason and "Distance" in r.reason
    assert ex.robot.chassis.y == 0.0                                                    # 아무것도 움직이지 않았다
    for ok in ("$m.top", "0.5", '"$m.gap + 0.5"'):                                      # 같은 타입 / 직접 적은 숫자 / 계산식은 통과
        ex, r = run(tmp_path, head + "    - Up: {z: %s}\n" % ok, extra=mods)
        assert r.status == "ok", (ok, r.reason)
    # 묶음의 칸을 따라간다: MoveEE 의 결과(MoveResult).pose_at_stop(Pose).z 는 Height
    ex, r = run(tmp_path, "main:\n  Sequence:\n    - Wait: {s: 0.1, out: $w}\n    - Up: {z: $w.elapsed}\n", extra=mods)
    assert r.status == "aborted" and "Seconds" in r.reason
    # 파이썬 블록의 칸도 같은 검사
    ex, r = run(tmp_path, "main:\n  Sequence:\n    - Mk: {out: $m}\n    - Wait: {s: $m.top}\n", extra=mods)
    assert r.status == "aborted" and "Seconds 인데" in r.reason


def test_every_block_declares_its_slot_types():
    reg = task_studio.base_registry()                            # 안에서 check_skills 가 돈다
    assert all(set(c.slots) == set(c.Input.model_fields) for c in reg.skills.values())
    assert reg.types["Pose"].fields["z"] == "Height"
