#!/usr/bin/env python
# 사용: python-pptx, Pillow, lxml 이 있는 파이썬으로 실행. task_studio_slides.html 의 <pre> 코드와 img/ 스크린샷으로 task_studio_slides.pptx 를 만든다.
"""Build demo/task_studio_slides.pptx from a slide spec, plus PIL previews for QA.

Two backends share one element model:
  rect / text / code / table / image / line
Measurement (text wrapping) is done with PIL fonts so both backends agree.
"""
import re, html, sys, os, copy
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.oxml.ns import qn
from lxml import etree
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
DEMO = '/home/maverick/Humanoid/Task_Studio/demo'
HTML = open(os.path.join(DEMO, 'task_studio_slides.html'), encoding='utf-8').read()

COL = dict(bg='171D1A', fg='E9ECE9', muted='9AA49E', line='2C3430', codebg='0F1412', card='1F2724',
           base='5EC29F', task='F1A33A', cond='C29AE6', ctrl='6FA8FF', val='E8D27A', kw='FF9AB8', s='F0C987',
           white='FFFFFF')
SPAN = dict(cm='muted', kw='kw', s='s', k='ctrl', a='base', t='task', c='cond', v='val')
FONT_K = 'Malgun Gothic'
FONT_M = 'Consolas'
SLIDE_W, SLIDE_H = 13.333, 7.5
DPI = 96

# ---------- fonts for measurement / preview ----------
_fc = {}
def pil_font(mono, bold, pt):
    key = (mono, bold, round(pt * 4))
    if key not in _fc:
        px = pt * DPI / 72
        if mono:
            p = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono%s.ttf' % ('-Bold' if bold else '')
            _fc[key] = ImageFont.truetype(p, int(round(px)), layout_engine=ImageFont.Layout.BASIC)
        else:
            p = '/usr/share/fonts/opentype/noto/NotoSansCJK-%s.ttc' % ('Bold' if bold else 'Regular')
            _fc[key] = ImageFont.truetype(p, int(round(px)), index=2, layout_engine=ImageFont.Layout.BASIC)  # KR face
    return _fc[key]

# ---------- run / paragraph model ----------
def R(t, c='fg', b=False, mono=False, i=False, sz=None, scale=1.0):
    return dict(t=t, c=c, b=b, mono=mono, i=i, sz=sz, scale=scale)

def rsz(run, para):
    return (run['sz'] or para['sz']) * run.get('scale', 1.0)

def md(text, c='fg'):
    """`code` -> mono, **bold** -> bold, [[color:text]] -> colored bold."""
    runs = []
    for part in re.split(r'(`[^`]+`|\*\*[^*]+\*\*|\[\[[a-z]+:[^\]]+\]\])', text):
        if not part:
            continue
        if part.startswith('`'):
            runs.append(R(part[1:-1], c=c, mono=True, scale=0.9))
        elif part.startswith('**'):
            runs.append(R(part[2:-2], c=c, b=True))
        elif part.startswith('[['):
            k, v = part[2:-2].split(':', 1)
            runs.append(R(v, c=k, b=True))
        else:
            runs.append(R(part, c=c))
    return runs

def P(runs, sz=13, ls=1.25, after=0, bullet=False, align='l', before=0):
    if isinstance(runs, str):
        runs = md(runs)
    return dict(runs=runs, sz=sz, ls=ls, after=after, bullet=bullet, align=align, before=before)

def parse_pre(idx):
    """Return paragraphs for the idx-th <pre> block of the HTML deck (syntax colored)."""
    pres = re.findall(r'<pre>(.*?)</pre>', HTML, re.S)
    src = pres[idx]
    paras = []
    for line in src.split('\n'):
        plain = re.sub(r'<[^>]+>', '', line)
        if len(plain) > 74:  # squeeze the gap before a trailing comment
            line = re.sub(r' {3,}(<span class="cm">)', r'  \1', line)
        runs = []
        pos = 0
        for m in re.finditer(r'<span class="(\w+)">(.*?)</span>', line):
            if m.start() > pos:
                runs.append(R(html.unescape(line[pos:m.start()]), mono=True))
            runs.append(R(html.unescape(m.group(2)), c=SPAN[m.group(1)], mono=True))
            pos = m.end()
        if pos < len(line):
            runs.append(R(html.unescape(line[pos:]), mono=True))
        if not runs:
            runs = [R('', mono=True)]
        paras.append(P(runs, sz=10, ls=1.18))
    return paras

# ---------- measurement ----------
CJK = re.compile(r'[ᄀ-ᇿ　-〿가-힯一-鿿＀-￯]')

def tokens(run):
    """Split run text into tokens that may not be broken: words+trailing space, or single CJK chars."""
    out = []
    for word in re.findall(r'\S+\s*|\s+', run['t']):
        if CJK.search(word):
            buf = ''
            for ch in word:
                if CJK.match(ch):
                    if buf:
                        out.append(buf); buf = ''
                    out.append(ch)
                else:
                    buf += ch
            if buf:
                out.append(buf)
        else:
            out.append(word)
    return out

def layout_para(para, width_px, bullet_indent_px=0):
    """Greedy line layout. Returns list of lines; a line = list of (x_px, run, text, font)."""
    lines = []
    cur = []
    x = 0.0
    maxw = width_px - bullet_indent_px
    for run in para['runs']:
        f = pil_font(run['mono'], run['b'], rsz(run, para))
        for tok in tokens(run):
            w = f.getlength(tok)
            if x + w > maxw + 0.5 and cur and tok.strip():
                lines.append(cur); cur = []; x = 0.0
                tok = tok.lstrip() if not run['mono'] else tok
                w = f.getlength(tok)
            cur.append((x, run, tok, f))
            x += w
    lines.append(cur)
    return lines

def para_line_px(para):
    return para['sz'] * DPI / 72 * para['ls']

def measure_text_px(paras, width_px, bullet_indent_px=20):
    h = 0.0
    for p in paras:
        ind = bullet_indent_px if p['bullet'] else 0
        n = len(layout_para(p, width_px, ind))
        h += p['before'] * DPI / 72 + n * para_line_px(p) + p['after'] * DPI / 72
    return h

def measure_text_in(paras, width_in, pad=(0.08, 0.05, 0.08, 0.05)):
    """Height in inches needed for paragraphs in a box of width_in with (l,t,r,b) padding."""
    wpx = (width_in - pad[0] - pad[2]) * DPI
    return measure_text_px(paras, wpx) / DPI + pad[1] + pad[3]

def max_line_width_in(paras):
    w = 0
    for p in paras:
        x = 0
        for run in p['runs']:
            f = pil_font(run['mono'], run['b'], rsz(run, p))
            x += f.getlength(run['t'])
        w = max(w, x)
    return w / DPI

# ---------- element constructors ----------
def rect(x, y, w, h, fill=None, line=None, radius=0.08, lw=1.0):
    return dict(kind='rect', x=x, y=y, w=w, h=h, fill=fill, line=line, radius=radius, lw=lw)

def text(x, y, w, h, paras, pad=(0.08, 0.05, 0.08, 0.05), fill=None, line=None, radius=0.08, anchor='t', name=None):
    if isinstance(paras, dict):
        paras = [paras]
    return dict(kind='text', x=x, y=y, w=w, h=h, paras=paras, pad=pad, fill=fill, line=line, radius=radius, anchor=anchor, name=name)

def code(x, y, w, h, idx):
    paras = parse_pre(idx)
    pad = (0.16, 0.12, 0.12, 0.12)
    h = min(h, measure_text_in(paras, w, pad) + 0.04)
    return text(x, y, w, h, paras, pad=pad, fill='codebg', line='line', radius=0.08, name='code')

def card(x, y, w, paras, fill='card', h=None, pad=(0.16, 0.1, 0.16, 0.1)):
    if isinstance(paras, dict):
        paras = [paras]
    hh = h or measure_text_in(paras, w, pad)
    return text(x, y, w, hh, paras, pad=pad, fill=fill, radius=0.08, name='card')

def table(x, y, w, cols, rows, header=True, sz=12, h=None, pad=(0.08, 0.045, 0.08, 0.045), ls=1.2):
    """rows: list of list of cell content (str md or runs). cols: relative widths."""
    tot = sum(cols)
    colw = [w * c / tot for c in cols]
    cells = []
    for ri, row in enumerate(rows):
        crow = []
        for ci, c in enumerate(row):
            is_h = header and ri == 0
            if isinstance(c, str):
                runs = md(c, c='muted' if is_h else 'fg')
            else:
                runs = c
            para = P(runs, sz=(sz - 2) if is_h else sz, ls=ls)
            crow.append([para])
        cells.append(crow)
    rowh = []
    for crow in cells:
        rh = 0
        for ci, paras in enumerate(crow):
            rh = max(rh, measure_text_in(paras, colw[ci], pad))
        rowh.append(rh)
    el = dict(kind='table', x=x, y=y, w=w, colw=colw, cells=cells, rowh=rowh, header=header, pad=pad)
    el['h'] = sum(rowh)
    return el

def image(x, y, w, h, path):
    return dict(kind='image', x=x, y=y, w=w, h=h, path=path)

def line(x1, y1, x2, y2, c='ctrl', lw=1.5, arrow=False):
    return dict(kind='line', x1=x1, y1=y1, x2=x2, y2=y2, c=c, lw=lw, arrow=arrow)

def stack(x, y, w, items, gap=0.16):
    """items: callables (x,y,w)->element. Returns elements placed vertically."""
    out = []
    for it in items:
        el = it(x, y, w)
        out.append(el)
        y += el['h'] + gap
    return out

# ---------- slide chrome ----------
ML, MR, MT = 0.75, 0.75, 0.5
CW = SLIDE_W - ML - MR
CY = 1.55  # content top
CH = SLIDE_H - CY - 0.45

def chrome(eyebrow, title, notes=None):
    els = [
        text(ML, MT, CW, 0.3, P([R(eyebrow, c='base', b=True, sz=10.5)], sz=10.5), pad=(0, 0, 0, 0), name='eyebrow'),
        text(ML, MT + 0.3, CW, 0.65, P([R(title, b=True, sz=24)], sz=24, ls=1.15), pad=(0, 0, 0, 0), name='title'),
    ]
    return dict(els=els, notes=notes)

def add(sl, *els):
    for e in els:
        if isinstance(e, list):
            sl['els'].extend(e)
        else:
            sl['els'].append(e)

# ---------- slides ----------
slides = []

# 1 title ------------------------------------------------------------------
s = dict(els=[], notes='엔지니어 대상. 블록 하나의 계약, 값 타입, 노드 8개와 선 3종만 다룬다.')
add(s, text(ML, 1.65, 7.6, 0.3, P([R('TASK STUDIO · 설계 공유 · 2026-11', c='base', b=True, sz=11)], sz=11), pad=(0,0,0,0)))
add(s, text(ML, 2.05, 7.9, 1.9, [P([R('로봇 동작을 블록으로 정의하고,', b=True, sz=38)], sz=38, ls=1.18), P([R('블록을 어떻게 잇는가', b=True, sz=38)], sz=38, ls=1.18)], pad=(0,0,0,0)))
add(s, text(ML, 4.15, 7.4, 1.4, P('블록 하나의 계약(입력·출력·실행), 블록 사이를 흐르는 값의 타입, 그리고 블록을 엮는 노드 8개와 선 3종. 이 세 가지만 다룬다.', sz=16, ls=1.4), pad=(0,0,0,0)))
add(s, text(ML, 6.7, 8, 0.3, P([R('Dexmate Vega · 실로봇 · 로봇 edge에서 실행', c='muted', sz=11)], sz=11), pad=(0,0,0,0)))
# motif: three blocks with a guard, right side
bx, by = 8.7, 2.35
def mini_card(x, y, w, h, name, body, c, num):
    return [rect(x, y, w, h, fill='codebg', line=c, radius=0.1, lw=1.5),
            text(x, y, w, 0.34, P([R(name, b=True, mono=True, sz=10.5), R('   ' + num, c='muted', sz=9)], sz=10.5), pad=(0.12, 0.07, 0.08, 0)),
            text(x, y + 0.32, w, h - 0.32, [P([R(l, c='muted', mono=True, sz=8.5)], sz=8.5, ls=1.25) for l in body], pad=(0.12, 0.02, 0.08, 0.04))]
add(s, mini_card(bx, by, 1.75, 1.05, 'DetectObject', ['cls = case', '→ $det : ObjectPose'], 'task', '②'))
add(s, line(bx + 1.75, by + 0.5, bx + 2.05, by + 0.5, c='val', lw=2, arrow=True))
add(s, mini_card(bx + 2.05, by, 1.55, 1.05, 'GraspPose', ['det ← $det', '→ $aim : Pose'], 'base', '①'))
add(s, line(bx + 1.0, by + 1.05, bx + 1.0, by + 1.5, c='ctrl', lw=2, arrow=True))
add(s, mini_card(bx, by + 1.5, 2.1, 1.3, 'SuctionPick', ['pose ← $aim', 'guards: [SafetyFloor]', '→ $pick : PickResult'], 'task', '②'))
add(s, line(bx + 2.1, by + 1.95, bx + 2.45, by + 1.95, c='ctrl', lw=2, arrow=True))
add(s, mini_card(bx + 2.45, by + 1.5, 1.6, 1.3, 'SuctionPlace', ['pose ← $drop', '→ $place'], 'task', '②'))
add(s, rect(bx + 0.2, by + 2.98, 1.3, 0.3, fill='bg', line='cond', radius=0.15, lw=1.5))
add(s, text(bx + 0.2, by + 2.98, 1.3, 0.3, P([R('SafetyFloor', c='cond', mono=True, sz=8.5)], sz=8.5, align='c'), pad=(0, 0.04, 0, 0), anchor='m'))
add(s, text(bx + 1.6, by + 2.98, 2.6, 0.3, P([R('가드: 동작이 도는 동안 계속 본다', c='muted', sz=9)], sz=9), pad=(0, 0.04, 0, 0)))
slides.append(s)

# 2 블록의 정의 --------------------------------------------------------------
s = chrome('1 · 블록의 정의', '블록은 파이썬 클래스 하나. 종류는 동작과 조건 둘뿐',
           '스킬은 트리를 모른다. run()은 그냥 함수. 실패는 예외가 아니라 Result.reason.')
LW = 6.95; RX = ML + LW + 0.3; RW = CW - LW - 0.3
add(s, code(ML, CY, LW, CH, 0))
add(s, stack(RX, CY, RW, [
    lambda x, y, w: table(x, y, w, [0.9, 2, 2], [
        ['', '동작', '조건'],
        [[R('실행', c='muted')], '`run()` 끝날 때까지 블로킹', '`check()` 지금 상태를 보고 즉시'],
        [[R('출력', c='muted')], '`ActionResult` + 스킬별 필드', 'bool'],
        [[R('꽂히는 곳', c='muted')], '트리의 잎', '동작의 `guards`, 또는 `Condition` 노드'],
    ], sz=12),
    lambda x, y, w: card(x, y, w, P('스킬은 트리를 모른다. `run()`은 그냥 함수다. 엮는 방식이 바뀌어도 스킬은 그대로.', sz=13)),
    lambda x, y, w: card(x, y, w, P('실패는 예외가 아니라 `Result.reason`. 어떻게 복구할지는 트리가 정한다.', sz=13)),
    lambda x, y, w: card(x, y, w, P('입·출력이 pydantic이라 스키마가 곧 포트다. 편집기 툴박스와 타입 검사가 여기서 나온다.', sz=13)),
], gap=0.2))
slides.append(s)

# 3 동작의 공통 계약 ----------------------------------------------------------
s = chrome('2 · 동작의 공통 계약', '모든 동작은 guards·timeout을 받고 stopped_by를 돌려준다',
           '가드가 울리는 건 실패가 아니다. ctx.check()는 선점(운영자·안전), 가드는 그 동작을 멈추는 조건.')
LW = 6.8; RX = ML + LW + 0.3; RW = CW - LW - 0.3
add(s, code(ML, CY, LW, CH, 1))
add(s, stack(RX, CY, RW, [
    lambda x, y, w: table(x, y, w, [1.35, 2.6, 0.75], [
        ['`stopped_by`', '뜻', 'status'],
        ['`reached`', '목표에 도달', 'ok'],
        ['`<가드 이름>`', '가드가 울려 멈춤. 예: `ForceOver` = 접촉', 'ok'],
        ['`unreachable`', 'IK 해 없음, 관절 한계', 'fail'],
        ['`timeout`', '시간 초과', 'fail'],
        ['`aborted`', '`ctx.check()`가 예외를 던짐', 'aborted'],
    ], sz=12),
    lambda x, y, w: card(x, y, w, P('**가드가 울리는 건 실패가 아니다.** "창에 들어올 때까지 기어가라"는 BaseMove + BEVInWindow 가드이고, 가드가 울리면 성공이다.', sz=12.5)),
    lambda x, y, w: card(x, y, w, P('`ctx.check()`와 가드는 다르다. 전자는 운영자·안전(선점), 후자는 그 동작을 멈추는 조건. 결과도 `aborted` vs `stopped_by`로 다르다.', sz=12.5)),
    lambda x, y, w: text(x, y, w, measure_text_in([P('x', sz=11)], w, (0,0,0,0)) * 4, P('숫자(오프셋·높이·힘·속도)는 전부 입력 필드. 기본값은 params.yaml, 프로그램이 주면 그 값이 이긴다. 기존 동작 + 조건으로 적을 수 있으면 새 블록을 만들지 않는다.', sz=11, ls=1.3), pad=(0.04,0,0.04,0)) | {'paras': [P([R('숫자(오프셋·높이·힘·속도)는 전부 입력 필드. 기본값은 params.yaml, 프로그램이 주면 그 값이 이긴다. 기존 동작 + 조건으로 적을 수 있으면 새 블록을 만들지 않는다.', c='muted')], sz=11, ls=1.3)]},
], gap=0.18))
slides.append(s)

# 4 블록 하나 짜는 법 ---------------------------------------------------------
s = chrome('3 · 블록 하나 짜는 법', '동작 하나 25줄, 조건 하나 10줄',
           'Skill 상속이 곧 레지스트리 등록. 로더가 Input(**args)로 검증하므로 틀린 필드는 로드 시점에 터진다.')
LW = 6.3; RX = ML + LW + 0.3; RW = CW - LW - 0.3
add(s, code(ML, CY, LW, CH, 2))
codeh = measure_text_in(parse_pre(3), RW, (0.16, 0.12, 0.12, 0.12))
add(s, code(RX, CY, RW, codeh, 3))
by = CY + codeh + 0.2
bul = [P([R('등록과 노출', c='muted', b=True, sz=12)], sz=12, after=4)] + [
    P('`Skill` 상속 = 레지스트리 등록. import 되면 끝.', sz=11.5, bullet=True, after=2),
    P('로더는 `MoveEE: {…}`를 레지스트리에서 찾아 `Input(**args)`로 검증. 틀린 필드는 로드 시점에 터진다.', sz=11.5, bullet=True, after=2),
    P('툴박스·포트 타입은 `Input.model_json_schema()`에서 자동.', sz=11.5, bullet=True, after=2),
    P('하드웨어는 `ctx.robot.*` 인터페이스로만. dexcontrol은 `vega/` 안에만.', sz=11.5, bullet=True),
]
add(s, text(RX, by, RW, CY + CH - by, bul, pad=(0.16, 0.12, 0.16, 0.1), fill=None, line='line', radius=0.08, name='box'))
slides.append(s)

# 4b 지금 정의한 블록 -----------------------------------------------------------
s = chrome('4 · 지금 정의한 블록', '원자 블록은 기본 층에, 복합 블록은 과제 층에',
           '원자 = 액추에이터 하나, 판단 없음, 1~5초. 복합 = 원자 여럿을 묶음, 5~30초, 전부 과제 층. 기존 원자+조건으로 적을 수 있으면 새 블록을 만들지 않는다.')
LW = 6.5; RX = ML + LW + 0.3; RW = CW - LW - 0.3
base_rows = [
    ['파트', '스킬 (입력)', '출력'],
    ['팔·몸통·머리', '`MoveJoints`(관절군, q, 속도)', 'stopped_by'],
    ['팔', '`MoveEE`(Pose, straight, keep_xy)', 'stopped_by, 멈춘 Pose'],
    ['섀시', '`BaseMove`(dx dy dyaw) · `Navigate`(지도 Pose)', 'stopped_by, 이동량 / 도착 Pose'],
    ['석션', '`SuctionOn` · `SuctionOff`(blow)', 'ok'],
    ['그리퍼', '`GripperMove`(폭, 힘)', 'stopped_by, 물체 감지'],
    ['머리 카메라', '`CaptureFrame` · `Detect`(검출기, 클래스)', 'Frame / [ObjectPose]'],
    ['손목 센서', '`ReadWrench` · `TareWrench`', 'Wrench / 기준값'],
    ['(계산)', '`OffsetPose`(Pose, dx dy dz dyaw) · `GraspPose`(ObjectPose, 접근, 잡는 점)', 'Pose'],
    ['운영자', '`Gate`(질문, 허용 명령)', 'Decision'],
    ['타이머', '`Wait`(timeout, 가드)', 'stopped_by'],
    [[R('조건', c='cond', b=True)], '`ForceOver`(축, 문턱 N, relative) · `Sealed` · `Timeout`(초) · `Reachable`(Pose)', 'bool'],
]
tb = table(ML + 0.16, CY + 0.5, LW - 0.32, [1.4, 3.25, 1.55], base_rows, sz=11)
add(s, rect(ML, CY, LW, tb['h'] + 0.7, fill=None, line='base', radius=0.1, lw=1.5))
add(s, text(ML + 0.16, CY + 0.12, LW - 0.32, 0.32, P([R('① 기본 · 원자 — 액추에이터 하나, 판단 없음, 1~5초', c='base', b=True, sz=10.5)], sz=10.5), pad=(0, 0.02, 0, 0)))
add(s, tb)
t1 = table(RX + 0.16, CY + 0.42, RW - 0.32, [1.0, 3.5], [
    ['바코드 리더', '`ReadCode`(시간 창) → 문자열'],
    [[R('조건', c='cond', b=True)], '`SafetyFloor`(z_min) · `BEVInWindow`(클래스, 창)'],
], header=False, sz=11)
add(s, rect(RX, CY, RW, t1['h'] + 0.62, fill=None, line='task', radius=0.1, lw=1.5))
add(s, text(RX + 0.16, CY + 0.12, RW - 0.32, 0.32, P([R('② 과제(LGES) · 원자 — 작업셀을 알아야 하는 것', c='task', b=True, sz=10.5)], sz=10.5), pad=(0, 0.02, 0, 0)))
add(s, t1)
y2 = CY + t1['h'] + 0.62 + 0.14
t2 = table(RX + 0.16, y2 + 0.42, RW - 0.32, [1.9, 2.6], [
    ['스킬', '구성'],
    ['`DetectObject`(cls, n)', 'Detect n번 → 중앙값 → ObjectPose'],
    ['`ResolvePose`(det, item)', 'GraspPose + 품목별 OffsetPose (objects.yaml)'],
    ['`SuctionPick`(pose, expected_z)', '위로 → MoveEE[ForceOver, SafetyFloor] → SuctionOn → Wait[Sealed] → 들기'],
    ['`SuctionPlace`(pose, expected_z, release_above)', '같은 뼈대 + early_contact 판정 + SuctionOff'],
    ['`GoToStation`(station)', 'stations.yaml 좌표 → Navigate, 없으면 BaseMove + 보정'],
    ['`ExpectedZ`(station, item, layers)', '열별 접촉 z 기록 → 다음 예상 z'],
    ['`ParkDuringLeg`', 'Parallel[MoveEE(park), GoToStation]'],
], sz=11)
add(s, rect(RX, y2, RW, t2['h'] + 0.58, fill=None, line='task', radius=0.1, lw=1.5))
add(s, text(RX + 0.16, y2 + 0.12, RW - 0.32, 0.32, P([R('② 과제(LGES) · 복합 — 원자 여럿을 묶음, 5~30초', c='task', b=True, sz=10.5)], sz=10.5), pad=(0, 0.02, 0, 0)))
add(s, t2)
slides.append(s)

# 5 값 타입 ------------------------------------------------------------------
s = chrome('5 · 블록 사이를 흐르는 값', '전부 pydantic 모델. base_link 기준, m / rad',
           '타입은 그것을 출력하는 블록과 같은 층에 둔다. 과제 타입은 기본 타입을 상속한다.')
LW = 6.5; RX = ML + LW + 0.3; RW = CW - LW - 0.3
base_rows = [
    ['타입', '필드', '만드는 곳 → 쓰는 곳'],
    ['원시값', 'float int str bool list', '숫자 입력, 식'],
    ['`Pose`', 'x y z, roll pitch yaw', 'GraspPose/OffsetPose → MoveEE, Navigate'],
    ['`JointState`', 'group, q[]', 'MoveJoints'],
    ['`Wrench`', 'fx fy fz tx ty tz, t', 'ReadWrench → ForceOver'],
    ['`Frame`', 'rgb, depth, q_torso, q_head, t', 'CaptureFrame → Detect'],
    ['`ObjectPose`', 'cls: str, pose, size(L W H), conf', 'Detect → GraspPose'],
    ['`Station`', 'name, pose (지도 좌표)', '→ Navigate'],
    ['`Result` / `ActionResult`', 'status, reason / + stopped_by, pose_at_stop', '모든 블록 / 모든 동작'],
    ['`Decision`', 'choice, args', 'Gate →'],
]
tb = table(ML + 0.16, CY + 0.5, LW - 0.32, [1.6, 2.25, 2.35], base_rows, sz=12)
add(s, rect(ML, CY, LW, tb['h'] + 0.7, fill=None, line='base', radius=0.1, lw=1.5))
add(s, text(ML + 0.16, CY + 0.12, LW - 0.32, 0.32, P([R(' ① 기본 · task_studio/core/types.py ', c='base', b=True, sz=10.5)], sz=10.5), pad=(0, 0.02, 0, 0)))
add(s, tb)
task_rows = [
    ['`PickResult`', 'ActionResult + contact_z, sealed'],
    ['`PlaceResult`', 'ActionResult + contact_z, early_contact'],
    ['`ItemSpec`', 'item, release_above, 컵 오프셋, 기대 바코드'],
    ['`StackState`', 'src_layers, tgt_layers'],
    ['`LegStation`', 'Station + 학습된 leg 거리'],
]
tt = table(RX + 0.16, CY + 0.5, RW - 0.32, [1.4, 2.75], task_rows, header=False, sz=12)
add(s, rect(RX, CY, RW, tt['h'] + 0.7, fill=None, line='task', radius=0.1, lw=1.5))
add(s, text(RX + 0.16, CY + 0.12, RW - 0.32, 0.32, P([R(' ② 과제 · tasks/lges/types.py ', c='task', b=True, sz=10.5)], sz=10.5), pad=(0, 0.02, 0, 0)))
add(s, tt)
ry = CY + tt['h'] + 0.7 + 0.22
add(s, stack(RX, ry, RW, [
    lambda x, y, w: card(x, y, w, P('타입은 그것을 **출력하는 블록과 같은 층**에 둔다. 기본은 과제 타입을 모른다.', sz=12.5)),
    lambda x, y, w: card(x, y, w, P('과제 타입은 기본 타입을 **상속**해 필드를 더한다. 자식 타입은 부모 구멍에 꽂힌다 (LegStation → Station 자리).', sz=12.5)),
    lambda x, y, w: card(x, y, w, P('블록의 입출력 스키마가 곧 **타입 검사**다. Pose 구멍에 ObjectPose는 로드 시점에 거절된다.', sz=12.5)),
], gap=0.16))
slides.append(s)

# 6 잇는 법 ------------------------------------------------------------------
s = chrome('6 · 잇는 법', '선 세 종류, 노드 여덟 개',
           '실패 처리는 블록 안이 아니라 트리 모양에 있다. 식은 산술·비교·논리만. 프로그램 = main + on_abort.')
LW = 5.6; RX = ML + LW + 0.3; RW = CW - LW - 0.3
add(s, stack(ML, CY, LW, [
    lambda x, y, w: table(x, y, w, [0.8, 2.6, 2.0], [
        ['선', '뜻', 'YAML'],
        ['**순서선**', '부모 노드가 자식을 어떤 순서·정책으로 돌리나', '노드 아래 들여쓴 목록'],
        ['**값선**', '한 블록의 출력이 다른 블록의 입력으로. 블랙보드의 `$변수`', '`out: $det` → `det: $det`'],
        ['**가드선**', '동작이 도는 동안 조건을 계속 본다', '`guards: [ForceOver: {…}]`'],
    ], sz=12),
    lambda x, y, w: card(x, y, w, P('**실패 처리는 블록 안이 아니라 트리 모양에 있다.** 블록이 fail을 돌려주면 Sequence가 멈추고, 위의 Fallback이 다음 자식(재검출, 또는 Gate)을 시도한다.', sz=12.5)),
    lambda x, y, w: card(x, y, w, P('식은 산술·비교·논리만 (`$stack.src - 1`). 과제 지식이 드는 계산은 식이 아니라 블록이다. 그래야 YAML과 그래프가 1:1.', sz=12.5)),
    lambda x, y, w: card(x, y, w, P('프로그램 파일 = `main` 트리 + `on_abort` 트리. 어디서 멈추든 `on_abort`가 돈다.', sz=12.5)),
], gap=0.18))
add(s, table(RX, CY, RW, [1.75, 2.45, 1.5], [
    ['노드', '뜻', '지금 코드에서는'],
    ['`Sequence`', '차례로, 하나 실패하면 실패', '함수 본문'],
    ['`Fallback`', '차례로, 하나 성공하면 성공', '재검출 → 안 되면 운영자'],
    ['`Retry(n)`', '실패하면 n번 다시', 'MAX_PHASE_ATTEMPTS'],
    ['`Parallel(policy)`', '동시에. 전부 / 하나 끝나면. `requires` 겹치면 로드 시 거절', '_park_during_legs'],
    ['`Loop(while)`', '반복, 블랙보드 값으로 종료', 'while src ≥ 1'],
    ['`Condition`', '조건 블록 또는 식을 한 번 검사', 'if descent_reachable()'],
    ['`Gate(prompt, allowed)`', '운영자 결정까지 멈춤. autonomy 레벨로 자동 통과 가능', 'input("Continue?")'],
    ['`Set`', '블랙보드 값 바꾸기', 'src -= 1'],
], sz=12))
slides.append(s)

# 7 프로그램 YAML --------------------------------------------------------------
s = chrome('7 · 프로그램 = 트리 하나를 YAML로', '물건 하나를 보고, 집고, 놓는다',
           '같은 YAML을 다음 장에서 그래프로 그린다. 입력 $item, $drop, $park, $params는 호출하는 쪽이 준다.')
LW = 7.3; RX = ML + LW + 0.3; RW = CW - LW - 0.3
add(s, code(ML, CY, LW, CH, 4))
add(s, stack(RX, CY, RW, [
    lambda x, y, w: card(x, y, w, P('[[ctrl:Parallel]]  머리·몸통 MoveJoints를 동시에. `requires`가 겹치지 않아 로드가 허용한다.', sz=12.5)),
    lambda x, y, w: card(x, y, w, P('[[val:값선]]  `$det` → GraspPose → `$aim` → OffsetPose → `$aim2` → SuctionPick. 블록 출력이 다음 블록 입력으로.', sz=12.5)),
    lambda x, y, w: card(x, y, w, P('[[cond:가드]]  SuctionPick은 SafetyFloor를 매 tick 본다. 바닥 아래로 내려가면 멈추고 `stopped_by`로 알린다.', sz=12.5)),
    lambda x, y, w: card(x, y, w, P('[[base:①]] [[task:②]]  MoveJoints·GraspPose·OffsetPose·MoveEE는 기본, DetectObject·SuctionPick/Place는 과제 블록.', sz=12.5)),
    lambda x, y, w: card(x, y, w, P('[[ctrl:on_abort]]  어디서 멈추든 이 트리가 돈다. 팔을 수직으로 빼고 홈으로.', sz=12.5)),
], gap=0.16))
slides.append(s)

# 8 프로그램 그래프 -------------------------------------------------------------
s = chrome('7 · 프로그램 = 트리 하나를 YAML로', '같은 YAML을 그래프로 그리면',
           'demo/task_studio_graph.html 이 YAML에서 그린 화면. 제어 노드는 점선 상자, 블록은 카드, 값선은 타입별 색, 가드는 카드 아래 육각형.')
im = Image.open(os.path.join(DEMO, 'img', 'graph_embed_crop.png'))
gw = CW; gh = gw * im.size[1] / im.size[0]
add(s, image(ML, CY, gw, gh, os.path.join(DEMO, 'img', 'graph_embed_crop.png')))
cy2 = CY + gh + 0.2
add(s, text(ML, cy2, CW, CY + CH - cy2, P([R('제어 노드', c='ctrl', b=True), R(' 점선 상자 · ', c='muted'), R('① 기본', c='base', b=True), R(' '), R('② 과제', c='task', b=True), R(' 카드 · 값선은 타입별 색 · ', c='muted'), R('가드', c='cond', b=True), R('는 카드 아래 육각형. 뷰어(demo/task_studio_graph.html)가 앞 장의 YAML에서 그린 화면.', c='muted')], sz=12), pad=(0,0,0,0)))
slides.append(s)

# 9 과제 층이 블록을 더하는 법 ---------------------------------------------------
s = chrome('8 · 과제 층이 블록을 더하는 법', '원자 블록을 더하거나, 묶어서 복합 블록을 만든다',
           '복합 블록도 같은 Skill 계약. 파이썬(Skill.call) 또는 YAML 매크로. 기본 층은 원자 블록까지만.')
LW = 7.0; RX = ML + LW + 0.3; RW = CW - LW - 0.3
add(s, code(ML, CY, LW, CH, 5))
add(s, stack(RX, CY, RW, [
    lambda x, y, w: card(x, y, w, [P([R('어느 층에 두나', c='muted', b=True, sz=11.5)], sz=11.5, after=3),
                                  P('배터리·케이스·bin·스테이션·층·바코드·테이블 높이가 이름에 나오면 [[task:② 과제]]. 아니면 [[base:① 기본]]. 헷갈리면 과제에 두고, 두 번째 PoC에서 다시 쓰고 싶을 때 기본으로 내린다. import 방향은 과제 → 기본 한쪽뿐.', sz=11.5, ls=1.3)], fill=None) | {'line': 'line'},
    lambda x, y, w: (lambda t: dict(kind='group', h=t['h'] + 0.5, els=[rect(x, y, w, t['h'] + 0.5, fill=None, line='line', radius=0.08),
        text(x + 0.16, y + 0.08, w - 0.32, 0.3, P([R('과제가 더하는 것 (LGES)', c='muted', b=True, sz=11.5)], sz=11.5), pad=(0,0.02,0,0)), t]))(
        table(x + 0.16, y + 0.4, w - 0.32, [0.9, 3.5], [
            ['원자 동작', '`ReadCode` 바코드 리더'],
            ['원자 조건', '`SafetyFloor`, `BEVInWindow`'],
            ['복합', '`DetectObject` `SuctionPick/Place` `GoToStation` `ExpectedZ` `ItemSpec` `DestStation` `SlotPose` `ParkDuringLeg`'],
            ['타입', '`PickResult` `PlaceResult` `ItemSpec` `StackState` `LegStation`'],
            ['데이터', '`params.yaml`(홈 자세·컵 길이·z_min) `objects.yaml` `stations.yaml` 검출 모델, 지도'],
        ], header=False, sz=11)),
    lambda x, y, w: card(x, y, w, P('복합 블록은 파이썬(`Skill.call`로 이어 붙임) 또는 YAML 매크로. 쓰는 쪽에서는 구분되지 않는다. 기본 층은 원자 블록까지만, 조합은 과제가 한다. 다음 PoC는 `tasks/<이름>/`을 새로 만든다.', sz=11.5, ls=1.3)),
], gap=0.16))
slides.append(s)

# 10 데모 ---------------------------------------------------------------------
s = chrome('9 · 데모 (가짜 로봇)', 'YAML을 그리고, 실행하면 노드가 칠해지고, 이벤트가 쌓인다',
           '발표 때는 demo/task_studio_graph.html 을 브라우저로 연다. 예시 전환, 첫 검출 실패 → Fallback → Gate, 이벤트 JSONL.')
im = Image.open(os.path.join(DEMO, 'img', 'graph_full.png'))
gh = CH - 0.05; gw = gh * im.size[0] / im.size[1]
add(s, image(ML, CY, gw, gh, os.path.join(DEMO, 'img', 'graph_full.png')))
RX = ML + gw + 0.25; RW = CW - gw - 0.25
add(s, stack(RX, CY, RW, [
    lambda x, y, w: card(x, y, w, P('`demo/` 폴더의 그래프 뷰어 HTML을 브라우저로 연다. 실행을 누르면 가짜 로봇이 트리를 돌며 노드를 칠한다.', sz=11.5, ls=1.3)),
    lambda x, y, w: card(x, y, w, P('예시를 "Task 3 아이템 하나"로 바꾸면 실제 과제 크기가 된다.', sz=11.5, ls=1.3)),
    lambda x, y, w: card(x, y, w, P('"첫 검출 실패"를 켜면 DetectObject가 한 번 실패해 Fallback → Gate(운영자 버튼)로 넘어간다.', sz=11.5, ls=1.3)),
    lambda x, y, w: card(x, y, w, P('이벤트 탭이 실행기가 쓰는 JSONL 한 줄씩. 같은 이벤트로 그래프 칠하기·리플레이를 한다.', sz=11.5, ls=1.3)),
], gap=0.14))
slides.append(s)

# ---------- flatten groups ----------
def flat(els):
    out = []
    for e in els:
        if e['kind'] == 'group':
            out.extend(flat(e['els']))
        else:
            out.append(e)
    return out
for s in slides:
    s['els'] = flat(s['els'])

# ---------- QA: overflow checks ----------
def qa():
    bad = 0
    for si, s in enumerate(slides, 1):
        for e in s['els']:
            if e['kind'] == 'text':
                need = measure_text_in(e['paras'], e['w'], e['pad'])
                if need > e['h'] + 0.02:
                    print(f'  slide {si}: text {e.get("name")} needs {need:.2f}in, has {e["h"]:.2f}in :: {e["paras"][0]["runs"][0]["t"][:40]!r}')
                    bad += 1
                if e.get('name') == 'code':
                    mw = max_line_width_in(e['paras']) + e['pad'][0] + e['pad'][2]
                    if mw > e['w']:
                        print(f'  slide {si}: code line width {mw:.2f}in > box {e["w"]:.2f}in')
                        bad += 1
            if e['kind'] in ('text', 'rect', 'table', 'image'):
                if e['x'] + e['w'] > SLIDE_W - 0.3 + 1e-6 or e['y'] + e['h'] > SLIDE_H - 0.2 + 1e-6:
                    print(f'  slide {si}: {e["kind"]} {e.get("name")} runs off slide: right={e["x"]+e["w"]:.2f} bottom={e["y"]+e["h"]:.2f}')
                    bad += 1
    print('QA issues:', bad)

# ---------- PIL preview ----------
def rgb(k):
    h = COL[k]
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def draw_paras(dr, paras, x, y, w, h, pad, anchor='t'):
    xpx = x * DPI + pad[0] * DPI; wpx = (w - pad[0] - pad[2]) * DPI
    total = measure_text_px(paras, wpx)
    ypx = y * DPI + pad[1] * DPI
    if anchor == 'm':
        ypx = y * DPI + ((h * DPI) - total) / 2
    for p in paras:
        ypx += p['before'] * DPI / 72
        ind = 20 if p['bullet'] else 0
        lines = layout_para(p, wpx, ind)
        lh = para_line_px(p)
        for li, ln in enumerate(lines):
            lw = sum(f.getlength(t) for _, _, t, f in ln)
            off = 0
            if p['align'] == 'c':
                off = (wpx - ind - lw) / 2
            if p['bullet'] and li == 0:
                dr.text((xpx + 4, ypx + lh * 0.1), '•', font=pil_font(False, False, p['sz']), fill=rgb('base'))
            for lx, run, t, f in ln:
                dr.text((xpx + ind + off + lx, ypx + (lh - f.size) / 2), t, font=f, fill=rgb(run['c']))
            ypx += lh
        ypx += p['after'] * DPI / 72

def preview(s, path):
    W, H = int(SLIDE_W * DPI), int(SLIDE_H * DPI)
    im = Image.new('RGB', (W, H), rgb('bg'))
    dr = ImageDraw.Draw(im)
    for e in s['els']:
        k = e['kind']
        if k in ('rect', 'text'):
            box = [e['x'] * DPI, e['y'] * DPI, (e['x'] + e['w']) * DPI, (e['y'] + e['h']) * DPI]
            if e.get('fill') or e.get('line'):
                dr.rounded_rectangle(box, radius=e.get('radius', 0) * DPI, fill=rgb(e['fill']) if e.get('fill') else None,
                                     outline=rgb(e['line']) if e.get('line') else None, width=max(1, int(e.get('lw', 1))))
            if k == 'text':
                draw_paras(dr, e['paras'], e['x'], e['y'], e['w'], e['h'], e['pad'], e.get('anchor', 't'))
        elif k == 'table':
            y = e['y']
            for ri, crow in enumerate(e['cells']):
                rh = e['rowh'][ri]
                x = e['x']
                for ci, paras in enumerate(crow):
                    draw_paras(dr, paras, x, y, e['colw'][ci], rh, e['pad'])
                    x += e['colw'][ci]
                yb = (y + rh) * DPI
                dr.line([e['x'] * DPI, yb, (e['x'] + e['w']) * DPI, yb], fill=rgb('line'), width=1)
                y += rh
        elif k == 'image':
            pic = Image.open(e['path']).convert('RGB').resize((int(e['w'] * DPI), int(e['h'] * DPI)))
            im.paste(pic, (int(e['x'] * DPI), int(e['y'] * DPI)))
        elif k == 'line':
            dr.line([e['x1'] * DPI, e['y1'] * DPI, e['x2'] * DPI, e['y2'] * DPI], fill=rgb(e['c']), width=int(e['lw'] * 1.3))
            if e['arrow']:
                x2, y2 = e['x2'] * DPI, e['y2'] * DPI
                if abs(e['x2'] - e['x1']) > abs(e['y2'] - e['y1']):
                    dr.polygon([(x2, y2), (x2 - 7, y2 - 4), (x2 - 7, y2 + 4)], fill=rgb(e['c']))
                else:
                    dr.polygon([(x2, y2), (x2 - 4, y2 - 7), (x2 + 4, y2 - 7)], fill=rgb(e['c']))
    im.save(path)

# ---------- PPTX backend ----------
def set_font(run_el, run, para):
    f = run_el.font
    f.size = Pt(rsz(run, para))
    f.bold = bool(run['b'])
    f.italic = bool(run['i'])
    f.color.rgb = RGBColor.from_string(COL[run['c']])
    f.name = FONT_M if run['mono'] else FONT_K
    rPr = run_el._r.get_or_add_rPr()
    latin = rPr.find(qn('a:latin'))
    ea = etree.SubElement(rPr, qn('a:ea'))
    ea.set('typeface', FONT_K)
    latin.addnext(ea)

def fill_tf(tf, paras, pad, anchor='t', wrap=True):
    tf.word_wrap = wrap
    tf.margin_left = Inches(pad[0]); tf.margin_top = Inches(pad[1])
    tf.margin_right = Inches(pad[2]); tf.margin_bottom = Inches(pad[3])
    tf.vertical_anchor = {'t': MSO_ANCHOR.TOP, 'm': MSO_ANCHOR.MIDDLE, 'b': MSO_ANCHOR.BOTTOM}[anchor]
    bodyPr = tf._txBody.find(qn('a:bodyPr'))
    for ch in list(bodyPr):
        if ch.tag in (qn('a:spAutoFit'), qn('a:normAutofit')):
            bodyPr.remove(ch)
    for pi, p in enumerate(paras):
        para = tf.paragraphs[0] if pi == 0 else tf.add_paragraph()
        para.line_spacing = p['ls']
        para.space_after = Pt(p['after'])
        para.space_before = Pt(p['before'])
        para.alignment = {'l': PP_ALIGN.LEFT, 'c': PP_ALIGN.CENTER, 'r': PP_ALIGN.RIGHT}[p['align']]
        pPr = para._p.get_or_add_pPr()
        if p['bullet']:
            pPr.set('marL', str(int(Inches(0.2)))); pPr.set('indent', str(-int(Inches(0.2))))
            bu = etree.SubElement(pPr, qn('a:buClr')); c = etree.SubElement(bu, qn('a:srgbClr')); c.set('val', COL['base'])
            bf = etree.SubElement(pPr, qn('a:buFont')); bf.set('typeface', 'Arial')
            bc = etree.SubElement(pPr, qn('a:buChar')); bc.set('char', '•')
        else:
            etree.SubElement(pPr, qn('a:buNone'))
        # default run props for empty paragraphs
        for run in p['runs']:
            r = para.add_run()
            r.text = run['t']
            set_font(r, run, p)
        if not p['runs'] or all(run['t'] == '' for run in p['runs']):
            endPr = etree.SubElement(para._p, qn('a:endParaRPr')); endPr.set('sz', str(int(p['sz'] * 100)))

def add_rect(slide, e, with_text=None):
    shp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE if e.get('radius') else MSO_SHAPE.RECTANGLE,
                                 Inches(e['x']), Inches(e['y']), Inches(e['w']), Inches(e['h']))
    if e.get('radius'):
        shp.adjustments[0] = min(0.5, e['radius'] / min(e['w'], e['h']))
    if e.get('fill'):
        shp.fill.solid(); shp.fill.fore_color.rgb = RGBColor.from_string(COL[e['fill']])
    else:
        shp.fill.background()
    if e.get('line'):
        shp.line.color.rgb = RGBColor.from_string(COL[e['line']]); shp.line.width = Pt(e.get('lw', 1))
    else:
        shp.line.fill.background()
    shp.shadow.inherit = False
    return shp

def build_pptx(path):
    prs = Presentation()
    prs.slide_width = Inches(SLIDE_W); prs.slide_height = Inches(SLIDE_H)
    blank = prs.slide_layouts[6]
    for si, s in enumerate(slides, 1):
        slide = prs.slides.add_slide(blank)
        bg = slide.background.fill; bg.solid(); bg.fore_color.rgb = RGBColor.from_string(COL['bg'])
        for e in s['els']:
            k = e['kind']
            if k == 'rect':
                add_rect(slide, e)
            elif k == 'text':
                if e.get('fill') or e.get('line'):
                    shp = add_rect(slide, e)
                    fill_tf(shp.text_frame, e['paras'], e['pad'], e.get('anchor', 't'))
                else:
                    tb = slide.shapes.add_textbox(Inches(e['x']), Inches(e['y']), Inches(e['w']), Inches(e['h']))
                    fill_tf(tb.text_frame, e['paras'], e['pad'], e.get('anchor', 't'))
                    if e.get('name'):
                        tb.name = e['name']
            elif k == 'table':
                nrows, ncols = len(e['cells']), len(e['colw'])
                gf = slide.shapes.add_table(nrows, ncols, Inches(e['x']), Inches(e['y']), Inches(e['w']), Inches(e['h']))
                tbl = gf.table
                tbl.first_row = False; tbl.horz_banding = False; tbl.vert_banding = False
                # drop table style id so no stock style applies
                tblPr = tbl._tbl.tblPr
                sid = tblPr.find(qn('a:tableStyleId'))
                if sid is not None:
                    tblPr.remove(sid)
                for ci, cw in enumerate(e['colw']):
                    tbl.columns[ci].width = Inches(cw)
                for ri, crow in enumerate(e['cells']):
                    tbl.rows[ri].height = Inches(e['rowh'][ri])
                    for ci, paras in enumerate(crow):
                        cell = tbl.cell(ri, ci)
                        cell.margin_left = Inches(e['pad'][0]); cell.margin_right = Inches(e['pad'][2])
                        cell.margin_top = Inches(e['pad'][1]); cell.margin_bottom = Inches(e['pad'][3])
                        cell.vertical_anchor = MSO_ANCHOR.TOP
                        tf = cell.text_frame
                        tf.word_wrap = True
                        for pi, p in enumerate(paras):
                            para = tf.paragraphs[0] if pi == 0 else tf.add_paragraph()
                            para.line_spacing = p['ls']
                            for run in p['runs']:
                                r = para.add_run(); r.text = run['t']; set_font(r, run, p)
                        tcPr = cell._tc.get_or_add_tcPr()
                        for ch in list(tcPr):
                            tcPr.remove(ch)
                        for side in ('lnL', 'lnR', 'lnT'):
                            ln = etree.SubElement(tcPr, qn('a:' + side)); ln.set('w', '0'); etree.SubElement(ln, qn('a:noFill'))
                        lnB = etree.SubElement(tcPr, qn('a:lnB')); lnB.set('w', '6350')
                        sf = etree.SubElement(lnB, qn('a:solidFill')); c = etree.SubElement(sf, qn('a:srgbClr')); c.set('val', COL['line'])
                        etree.SubElement(tcPr, qn('a:noFill'))
                        # keep margins/anchor attributes
                        tcPr.set('marL', str(int(Inches(e['pad'][0])))); tcPr.set('marR', str(int(Inches(e['pad'][2]))))
                        tcPr.set('marT', str(int(Inches(e['pad'][1])))); tcPr.set('marB', str(int(Inches(e['pad'][3]))))
                        tcPr.set('anchor', 't')
            elif k == 'image':
                slide.shapes.add_picture(e['path'], Inches(e['x']), Inches(e['y']), Inches(e['w']), Inches(e['h']))
            elif k == 'line':
                cn = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(e['x1']), Inches(e['y1']), Inches(e['x2']), Inches(e['y2']))
                cn.line.color.rgb = RGBColor.from_string(COL[e['c']]); cn.line.width = Pt(e['lw'])
                if e['arrow']:
                    ln = cn.line._get_or_add_ln()
                    te = etree.SubElement(ln, qn('a:tailEnd')); te.set('type', 'triangle'); te.set('w', 'med'); te.set('len', 'med')
        if s.get('notes'):
            slide.notes_slide.notes_text_frame.text = s['notes']
    prs.save(path)

if __name__ == '__main__':
    qa()
    PREV = os.path.join(os.environ.get('TMPDIR', '/tmp'), 'slides_prev'); os.makedirs(PREV, exist_ok=True)
    for si, s in enumerate(slides, 1):
        preview(s, os.path.join(PREV, f'slide-{si:02d}.png'))
    out = os.path.join(DEMO, 'task_studio_slides.pptx')
    build_pptx(out)
    print('wrote', out, len(slides), 'slides')
