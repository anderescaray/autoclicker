"""Generate docs/images/how-it-works.svg: an animated explanation of the run loop (CSS only, plays on GitHub).

Run:  python tools/make_how_it_works_svg.py
"""

from pathlib import Path

T = 12.8          # full cycle, seconds
ITEM = 3.2        # one item
RH = 34           # row height
REST, ROW, OK = (430, 300), (150, 121), (300, 238)


def pct(t):
    return f"{max(0.0, min(100.0, t / T * 100)):.2f}%"


def frames(name, points, prop):
    """points: [(t, value)] -> @keyframes with steps at those times."""
    body = " ".join(f"{pct(t)} {{ {prop}: {v}; }}" for t, v in points)
    return f"@keyframes {name} {{ {body} }}"


css = []
anim = []


def add(name, sel, points, prop, ease="ease-in-out"):
    css.append(frames(name, points, prop))
    anim.append(f"{sel} {{ animation: {name} {T}s {ease} infinite; }}")


# cursor path, clicks, dialog, selection, rows, counter, stages
cur, dlg, sel, rip_row, rip_ok = [], [], [], [], []
for k in range(3):
    t0 = k * ITEM
    cur += [(t0, REST), (t0 + 0.8, REST), (t0 + 1.2, ROW), (t0 + 1.4, ROW), (t0 + 1.75, OK), (t0 + 2.05, OK),
            (t0 + 2.4, REST)]
    dlg += [(t0 + 1.3, 0), (t0 + 1.45, 1), (t0 + 2.0, 1), (t0 + 2.15, 0)]
    sel += [(t0 + 1.25, 0), (t0 + 1.3, 1), (t0 + 2.3, 1), (t0 + 2.4, 0)]
    rip_row += [(t0 + 1.2, "0; transform: scale(0.3)"), (t0 + 1.25, "0.8; transform: scale(0.3)"),
                (t0 + 1.6, "0; transform: scale(1.6)")]
    rip_ok += [(t0 + 1.95, "0; transform: scale(0.3)"), (t0 + 2.0, "0.8; transform: scale(0.3)"),
               (t0 + 2.35, "0; transform: scale(1.6)")]
cur += [(T, REST)]
add("cur", "#cursor", [(t, f"translate({x}px, {y}px)") for t, (x, y) in cur], "transform")
add("dlg", "#dialog", [(0, 0)] + dlg + [(T, 0)], "opacity")
add("sel", "#selected", [(0, 0)] + sel + [(T, 0)], "opacity")
add("ripr", "#rip-row", [(0, "0; transform: scale(0.3)")] + rip_row + [(T, "0; transform: scale(0.3)")], "opacity", "ease-out")
add("ripo", "#rip-ok", [(0, "0; transform: scale(0.3)")] + rip_ok + [(T, "0; transform: scale(0.3)")], "opacity", "ease-out")

rows = [(0, 0)]
for k in range(3):
    t0 = k * ITEM
    rows += [(t0 + 2.5, -k * RH), (t0 + 3.0, -(k + 1) * RH)]
rows += [(T - 0.4, -3 * RH), (T - 0.39, 0), (T, 0)]
add("rows", "#rows", [(t, f"translateY({y}px)") for t, y in rows], "transform")
add("listin", "#rows-fade", [(0, 0), (0.3, 1), (T - 0.45, 1), (T - 0.4, 0), (T, 0)], "opacity")

stages = {1: [], 2: [], 3: [], 4: [], 5: []}
for k in range(3):
    t0 = k * ITEM
    for st, (a, b) in {1: (0, 0.4), 2: (0.4, 0.8), 3: (0.8, 2.4), 4: (2.4, 3.2)}.items():
        stages[st] += [(t0 + a, 0), (t0 + a + 0.05, 1), (t0 + b - 0.05, 1), (t0 + b, 0)]
t3 = 3 * ITEM
stages[1] += [(t3, 0), (t3 + 0.05, 1), (t3 + 0.4, 1), (t3 + 0.45, 0)]
stages[2] += [(t3 + 0.45, 0), (t3 + 0.5, 1), (t3 + 0.9, 1), (t3 + 0.95, 0)]
stages[5] += [(t3 + 0.95, 0), (t3 + 1.0, 1), (T - 0.45, 1), (T - 0.4, 0)]
for st, pts in stages.items():
    add(f"st{st}", f"#hl{st}", [(0, 0)] + pts + [(T, 0)], "opacity", "linear")
add("done", "#done", [(0, 0), (t3 + 1.0, 0), (t3 + 1.2, 1), (T - 0.45, 1), (T - 0.4, 0), (T, 0)], "opacity")
for n in range(4):
    on = 0 if n == 0 else (n - 1) * ITEM + 3.0
    off = n * ITEM + 3.0 if n < 3 else T - 0.4
    add(f"c{n}", f"#count{n}", [(0, 0), (max(on - 0.01, 0), 0), (on, 1), (off - 0.01, 1), (off, 0), (T, 0)], "opacity", "step-end")

items = ["REQ-1001   Purchase order    Alice", "REQ-1002   Expense report    Bob",
         "REQ-1003   Access request    Carmen"]
row_svg = "".join(
    f'<text x="58" y="{128 + i * RH}" class="mono">{t}</text>'
    f'<line x1="44" x2="404" y1="{140 + i * RH}" y2="{140 + i * RH}" class="sep"/>' for i, t in enumerate(items))

stage_rows = [(1, "Find the list", "by its header (the anchor)"),
              (2, "Is the first row empty?", "yes → done, no → go on"),
              (3, "Do your recorded clicks", "each target is found on screen first"),
              (4, "Wait until the list changes", "so no item is done twice")]
stage_svg = ""
for i, (n, title, sub) in enumerate(stage_rows):
    y = 70 + i * 62
    stage_svg += (f'<rect id="hl{n}" x="500" y="{y}" width="370" height="50" rx="10" class="hl"/>'
                  f'<rect x="500" y="{y}" width="370" height="50" rx="10" class="stage"/>'
                  f'<circle cx="527" cy="{y + 25}" r="12" class="num"/>'
                  f'<text x="527" y="{y + 29.5}" class="numt">{n}</text>'
                  f'<text x="550" y="{y + 22}" class="st">{title}</text>'
                  f'<text x="550" y="{y + 39}" class="sub">{sub}</text>')

svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 380" width="900" height="380" role="img"
  aria-label="Animation: AutoClicker Visual finds the list, clicks through one item, waits for the list to move up, and repeats until it is empty">
<style>
  text {{ font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }}
  .mono {{ font-family: ui-monospace, Consolas, Menlo, monospace; font-size: 12.5px; fill: #1f2735; white-space: pre; }}
  .sep {{ stroke: #eef0f4; }}
  .stage {{ fill: none; stroke: #dfe3ea; }}
  .hl {{ fill: #e8f1fe; stroke: #0a74f0; stroke-width: 1.5; opacity: 0; }}
  #hl5 {{ fill: #e6f6ee; stroke: #19a974; }}
  .num {{ fill: #0a74f0; }}
  .numt {{ fill: #fff; font-size: 12px; font-weight: 700; text-anchor: middle; }}
  .st {{ font-size: 14px; font-weight: 600; fill: #131a29; }}
  .sub {{ font-size: 11.5px; fill: #6c7486; }}
  .label {{ font-size: 11px; font-weight: 600; }}
  #dialog, #selected, #done, #rip-row, #rip-ok, [id^=count] {{ opacity: 0; }}
  #rip-row, #rip-ok {{ transform-box: fill-box; transform-origin: center; }}
  {" ".join(css)}
  {" ".join(anim)}
  @media (prefers-reduced-motion: reduce) {{ * {{ animation: none !important; }} #hl1, #count0 {{ opacity: 1; }} }}
</style>
<rect width="900" height="380" rx="18" fill="#f4f5f8"/>
<text x="30" y="40" class="st" style="font-size:15px">Any desktop app with a list of pending items</text>
<text x="500" y="40" class="st" style="font-size:15px">What AutoClicker Visual does, for every item</text>

<!-- the target app -->
<rect x="30" y="58" width="390" height="292" rx="10" fill="#fff" stroke="#d5dae3"/>
<rect x="40" y="68" width="370" height="30" rx="4" fill="#2f5d8a"/>
<text x="52" y="88" style="font-size:13.5px;font-weight:700;fill:#fff">Pending requests</text>
<rect x="36" y="64" width="378" height="38" rx="7" fill="none" stroke="#f0a020" stroke-width="2" stroke-dasharray="5 4"/>
<text x="428" y="80" class="label" style="fill:#c77c00">anchor</text>
<text x="428" y="94" class="sub" style="font-size:10.5px">finds the list</text>
<clipPath id="listclip"><rect x="40" y="104" width="370" height="200"/></clipPath>
<g clip-path="url(#listclip)">
  <rect id="selected" x="44" y="{106}" width="360" height="{RH - 2}" rx="4" fill="#cfe3fb"/>
  <g id="rows-fade"><g id="rows">{row_svg}</g></g>
</g>
<rect x="40" y="104" width="370" height="{RH + 2}" rx="5" fill="none" stroke="#19a974" stroke-width="2" stroke-dasharray="5 4"/>
<text x="428" y="118" class="label" style="fill:#13865c">first row</text>
<text x="428" y="132" class="sub" style="font-size:10.5px">empty = done</text>
<g id="done"><text x="225" y="220" text-anchor="middle" style="font-size:15px;font-weight:700;fill:#13865c">✓ List is empty</text>
  <text x="225" y="242" text-anchor="middle" class="sub">Done. 3 items processed.</text></g>

<g id="dialog">
  <rect x="190" y="180" width="190" height="96" rx="10" fill="#fff" stroke="#c5ccd6"/>
  <text x="206" y="206" style="font-size:12.5px;font-weight:600;fill:#131a29">Approve this request?</text>
  <rect x="262" y="224" width="76" height="28" rx="6" fill="#0a74f0"/>
  <text x="300" y="243" text-anchor="middle" style="font-size:12.5px;font-weight:600;fill:#fff">OK</text>
</g>
<circle id="rip-row" cx="{ROW[0]}" cy="{ROW[1]}" r="14" fill="#0a74f0"/>
<circle id="rip-ok" cx="{OK[0]}" cy="{OK[1]}" r="14" fill="#0a74f0"/>
<path id="cursor" d="M0 0 L0 19 L5 14.5 L8.5 22 L12 20.5 L8.5 13 L14.5 13 Z" fill="#fff" stroke="#131a29" stroke-width="1.6" stroke-linejoin="round"/>

<!-- the loop -->
{stage_svg}
<rect id="hl5" x="500" y="318" width="370" height="40" rx="10" class="hl"/>
<text x="520" y="343" class="st" style="font-size:13.5px">Done when the list is empty.</text>
<g style="font-size:12px;fill:#6c7486">
  <text id="count0" x="868" y="343" text-anchor="end">0 processed</text>
  <text id="count1" x="868" y="343" text-anchor="end">1 processed</text>
  <text id="count2" x="868" y="343" text-anchor="end">2 processed</text>
  <text id="count3" x="868" y="343" text-anchor="end">3 processed</text>
</g>
<path d="M880 295 C 892 260, 892 110, 880 95" fill="none" stroke="#9aa3b2" stroke-width="1.5" marker-end="url(#arr)"/>
<defs><marker id="arr" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
  <path d="M0 0 L10 5 L0 10 z" fill="#9aa3b2"/></marker></defs>
</svg>
'''
open(Path(__file__).resolve().parent.parent / "docs" / "images" / "how-it-works.svg", "w", encoding="utf-8").write(svg)
print(len(svg), "bytes")
