"""프로그램 하나를 돌린다.

    python -m task_studio.tools.run <과제> <프로그램> --robot mock
    python -m task_studio.tools.run <과제> <프로그램> --robot mock --set 입력='{"a":1}' --console
    python -m task_studio.tools.run <과제> <프로그램> --robot mock --answers '["continue", {"move": {"dy": 0.5}}, "continue"]'

--robot mock : 가짜 로봇 + 그 과제의 가짜 작업셀 (tasks/<과제>/mock_cell.py). 시간은 흘리기만 한다.
--robot vega : 실로봇. 아직 없다.
"""
from __future__ import annotations

import argparse
import importlib
import json
import signal
import sys
import time
from pathlib import Path

from ..core.context import ConsoleOperator, EventLog, RealClock, ScriptedOperator, VirtualClock
from ..core.types import Decision
from ..runtime.executor import Executor


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("task", help="과제 이름 (tasks/<이름>)")
    ap.add_argument("program", help="프로그램 이름 (programs/<이름>.yaml)")
    ap.add_argument("--robot", choices=["mock", "vega"], default="mock")
    ap.add_argument("--set", action="append", default=[], metavar="입력=값", help="프로그램 입력 (JSON 값). 예: stack='{\"src\":1,\"tgt\":1}'")
    ap.add_argument("--param", action="append", default=[], metavar="이름=값", help="params 덮어쓰기")
    ap.add_argument("--events", default=None, help="이벤트 JSONL 경로 (기본: runs/<프로그램>_<시각>.jsonl)")
    ap.add_argument("--console", action="store_true", help="게이트를 키보드로 답한다 (기본: mock 은 continue 로 자동 통과)")
    ap.add_argument("--answers", default=None, help="운영자 답을 차례로 (JSON 목록). 선택지 이름 또는 {\"move\": {\"dy\": 0.5}}")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    task = importlib.import_module(f"tasks.{a.task}")
    kv = lambda items: {k: json.loads(v) for k, v in (s.split("=", 1) for s in items)}
    params = task.params(**kv(a.param))
    if a.robot == "vega":
        from .. import vega
        robot, clock = vega.connect(params), RealClock()
    else:
        clock = VirtualClock()
        robot, _ = importlib.import_module(f"tasks.{a.task}.mock_cell").make(params, clock)
    path = a.events or f"runs/{a.program}_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
    events = EventLog(path, clock)
    answers = [Decision(choice="move", args=x["move"]) if isinstance(x, dict) else x for x in json.loads(a.answers or "[]")]
    operator = ConsoleOperator() if (a.console or a.robot == "vega") else ScriptedOperator(answers, default="continue")
    ex = Executor(task.registry(), robot, params, operator, events, clock)
    signal.signal(signal.SIGINT, lambda *_: ex.request_stop())      # Ctrl-C = 정지 요청 → on_abort

    if not a.quiet:
        seen = [0]

        def show() -> None:
            for r in events.records[seen[0]:]:
                if r["ev"] in ("node_exit", "guard", "gate", "decision", "error", "run_end") and r.get("type") not in ("Sequence",):
                    depth = r.get("node", "").count("/") + r.get("node", "").count("[")
                    rest = {k: v for k, v in r.items() if k not in ("t", "ev", "node", "type")}
                    print(f"{r['t']:8.2f}  {'  ' * min(depth, 12)}{r.get('type', r['ev'])}  {rest}")
            seen[0] = len(events.records)
        emit = events.emit
        events.emit = lambda ev, **d: (emit(ev, **d), show())[0]    # type: ignore[method-assign]

    result = ex.run(a.program, kv(a.set))
    events.close()
    print(f"\n끝: {result.status}{' — ' + result.reason if result.reason else ''}   이벤트: {Path(path).resolve()}")
    return 0 if result.status == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
