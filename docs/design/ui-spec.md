# UI spec

Target look: **light, calm and precise, in the style of macOS System Settings**, with motion that feels native (springs, not fades everywhere). It must look hand-made, not template-made.

The interactive mock-up is in [`ui-reference.html`](ui-reference.html). Open it in a browser and press **Run** and **Record**, flip the switches and hover the recording capsule. When this document and the mock-up disagree, this document wins.

This is a **visual and structural** change only. The engine, vision, recorder, storage, safety stops and F12 behave exactly as they do today.

---

## 1. Structure

Merge `MainWindow` and `FlowEditor` into **one window** with a sidebar:

```
┌──────────────────────────────────────────────────────────────────────┐
│ (native Windows title bar)                                           │
├───────────────┬──────────────────────────────────────────────────────┤
│ Flows     (+) │  Approve requests                Simulate  Run 1  ▶Run│
│ [ Search    ] │  6 steps · up to 100 items per run                    │
│               │                                                      │
│ ▣ Approve req │  Screen                  │ Steps · repeated…  ●Rec  + │
│ ▢ Clear queue │  ┌─────────────────────┐ │ ┌──────────────────────────┐│
│ ▢ Confirm del │  │ [Monitor 1|Monitor 2]│ │ │ 1  ⌖row   First row     ○ ││
│               │  │ Size   2560×1440 125%│ │ │ 2  [Review] Review      ○ ││
│               │  └─────────────────────┘ │ │ …                        ││
│               │  The list                │ └──────────────────────────┘│
│               │  ┌ Anchor   [crop]     ┐ │ Test  Edit      Delete  Save │
│               │  │ First row [crop]    │ │                              │
│               │  │ ● Found, with item  │ │                              │
│               │  │ Mark anchor and…  › │ │                              │
│               │  └─────────────────────┘ │                              │
│               │  Options                 │                              │
│ F12 stops…    │  ┌ Pause if I move  (●)┐ │                              │
└───────────────┴──────────────────────────────────────────────────────┘
```

- **Sidebar** (248 px): the "Flows" title (20 px, bold) with a round **+** button (new flow), a search field that filters the list, the list of flows, and an "F12 stops a run from anywhere" hint pinned to the bottom. Each flow row has a 32 px rounded-square monogram (first letter, colour from a fixed palette by hash), the name (semibold) and a secondary line ("6 steps · today, 09:42" / "not run yet"). Right-click a flow for **Duplicate, Export…, Delete**. **Import…** goes in the + button's menu, next to "New flow".
- **Header** of the editor: flow name as the title (24 px, bold, editable in place on double-click), a secondary line, then on the right **Simulate** (plain pill), **Run 1 item** (tonal pill) and **▶ Run** (filled accent pill).
- **Left column (318 px)**: grouped lists, as in macOS Settings.
  - **Screen**: read-only "Monitor" and "Size" rows ("Monitor 2", "2560 × 1440 · 125 %"). There is no monitor picker: the list is marked on whichever monitor shows it, and the live check and runs find it on any monitor.
  - **The list**: anchor crop, first-row crop, the live status row (dot + "Found, with an item" / "Anchor not found" / "List is empty"), and a "Mark anchor and first row" row in accent text with a chevron.
  - **Options**: switches for "Pause if I move the mouse" and "Maximise the window first", plus the "Max items per run" and "Wait for the list to update" values.
- **Right column**: "Steps · repeated for each item" caption with **Record** and **Add step** pills. The steps are a grouped list: number in a small grey circle, target thumbnail (92×30, 8 px radius), title and secondary line, and a state icon on the right. Under it: Test step, Edit · Delete, Save (tonal).
- **Empty states**: with no flows, the editor area shows a short, centred message and a primary "New flow" button. With no steps, the steps group shows "Record the clicks for one item" with the Record button.
- **Saving**: keep explicit Save, but show unsaved changes as a small dot next to the flow name in the sidebar. Closing with unsaved changes asks as today.

The existing dialogs (StepDialog, RunDialog, MonitorDialog, the tutorial QWizard, message boxes) are restyled with the same tokens. Their behaviour doesn't change. The monitor picker dialog is gone: monitors are detected automatically.

## 2. Tokens

Use the Windows 11 system fonts. Do not bundle web fonts.

| Token | Value |
|---|---|
| Font, text | `Segoe UI Variable Text`, fallback `Segoe UI` |
| Font, titles | `Segoe UI Variable Display`, fallback `Segoe UI` |
| Font, numbers/coords | `Cascadia Mono`, fallback `Consolas` |
| Base size | 13.5 px (10 pt). Title 24 px bold, sidebar title 20 px bold, captions 13 px semibold muted |
| Window background | `#f4f5f8` |
| Sidebar background | `#e9ebef` |
| Text | `#131a29` |
| Secondary text | `#6c7486` |
| Separators | `rgba(19,26,41,.12)`, 1 px, inset 14 px from the left inside groups |
| Group background | `#ffffff`, radius 10 px, hairline border = separator colour |
| Control fill | `rgba(19,26,41,.06)`; hover `rgba(19,26,41,.10)` |
| Accent | `#0a74f0`; hover `#2a88f5`; accent text `#0a63d1`; accent tint `rgba(10,116,240,.10)` |
| Selected flow row | background `#0a74f0`, text white, secondary text white at 78 % |
| Danger (Stop) | `#f0445a` |
| Warning (problem icon) | `#e8960c` on `rgba(232,150,12,.14)` |
| Radii | pills/buttons 7 px · flow rows 8 px · groups 10 px · step thumbnails 8 px · floating cards 18 px · switches and dots fully round |
| Spacing | 8 px grid. Group cell padding 11×14 px. Editor padding 22×26 px. Gap between columns 18 px |

Rules:
- **Accent only for "go" and state**: Run, progress, done checks, the live dot, the selected flow, links like "Mark anchor and first row". Everything else is neutral.
- No uppercase labels, no emoji, no gradients except the monogram squares and the tiny app logo.
- Shadows only on floating things (run panel, problem dialog, capsule, snackbar). Use `QGraphicsDropShadowEffect` sparingly: one per floating window, never per list row.

## 3. Components

| Component | Spec |
|---|---|
| **Pill button** | Text 13 px semibold, 7 px radius, padding 6×13 px (small) / 9×18 px (Run). Variants: plain (control fill), tonal (accent tint + accent text), filled (accent + white text), danger (red + white). |
| **Switch** | 42×25 px track; 21 px white knob with a soft shadow; off = `rgba(19,26,41,.12)`, on = accent. |
| **Live status dot** | 8 px accent dot with a 3 px tint halo that softly expands and fades (2.4 s loop). Grey when not found. |
| **Step state icon** | 22 px. Ready = thin grey ring. Running = accent arc spinning (0.8 s per turn). Done = accent filled circle that pops in, then a white check that draws itself. Problem = amber circle with "!". |
| **Snackbar** | Replaces most "Saved / Finished" message boxes: dark `#131a29` rounded rectangle (12 px), white text, accent check icon, centred at the bottom of the window, rises 24 px with a spring, auto-hides after 2.4 s. Errors still use dialogs. |
| **Recording capsule** | Replaces RecordingBar: a black capsule (height 40, fully rounded) at the **top centre** of a monitor other than the work one if there is one, otherwise of the work monitor. It shows a breathing red dot, "Recording", "**3** steps" (the number pops on each new step), then "Undo" (translucent white pill) and "Finish" (accent pill). Collapsed width ~180 px showing dot, "Recording" and count; it **widens** to reveal Undo/Finish when hovered. Keep warnings as a second line that slides out under the capsule for 5 s. Keep the physical-rect and HWND checks so clicks on it are never recorded. |
| **Run panel** | Floating card (18 px radius, shadow), 360 px wide, at the top centre of another monitor if there is one (like the recording capsule). It opens ready, with Start and Cancel; the run begins on Start. On the left a 64 px **progress ring** (accent on light grey, 6 px stroke, "3/5" in the middle, tabular digits). On the right the flow name (bold) and "Item 4 · **Approve**" (step label in accent). Bottom row: hint "Or push the mouse into a corner" and **Stop · F12** (danger pill). |
| **Problem dialog** | Centred alert card (18 px radius): a 44 px amber circle icon, a bold title ("The list isn't on screen"), one sentence, then "Looking for" / "On screen now" images side by side, then three equal buttons ("Cancel", "Show where", "Try again" as filled accent). Same actions as today per problem kind. |
| **Highlight overlay** (Test step / Simulate) | Accent 3 px rounded rectangle around the target with a soft outer glow, and a small dark label pill above it ("Step 2 · found here"). Fades in, holds, then fades out. |
| **Region picker** | Keep the dimmed frozen screen. The instruction becomes a dark capsule at the top centre (like the recording capsule) with "Step 1 of 2" in muted text. Marked rectangles use a 2 px accent border with 4 px radius and a soft tint. |

## 4. Motion

Implement with `QPropertyAnimation` / `QVariantAnimation` and `QEasingCurve`. All durations are short, nothing blocks input, and every animation is skipped when the user has turned animations off in Windows (`SystemParametersInfo(SPI_GETCLIENTAREAANIMATION)`).

| Where | What | Timing |
|---|---|---|
| Buttons, round +, capsule buttons | Pressed: shrink to 95 %; released: spring back | 80 ms in; 400 ms out, `OutBack` |
| Switch knob | Slides; track colour cross-fades | 400 ms `OutBack` / 200 ms |
| Selecting a flow | Editor content cross-fades (opacity 0.6 → 1) and rises 6 px | 220 ms `OutCubic` |
| Steps list after load/record | Rows fade and rise 8 px, one after another | 500 ms each, 40 ms stagger |
| During a run | Current row: tint background and spinner; finished rows: check pops (scale 0 → 1, 350 ms `OutBack`) and draws (300 ms) | per step |
| Run panel ring | Animates to the new value after each item | 600 ms `OutCubic` |
| Recording capsule | Widens/narrows on hover; the count pops (scale 1.15 and 3 px up, then back) | 600 ms `OutBack` / 400 ms |
| Snackbar | Rises 24 px and fades in, then out | 500 ms `OutBack` / 250 ms |
| Problem dialog | Scales 0.9 → 1 and fades in | 550 ms `OutBack` |
| Live dot | Halo grows and fades | 2.4 s loop |

How to do it in Qt:
- QSS cannot animate or scale. Paint pills, switches, the ring, the step state icon, the live dot and the capsule as small custom `QWidget`s with `paintEvent`, exposing animatable `Property`s. Keep QSS for colours, fonts and the standard widgets (line edits, spin boxes, combo boxes, scroll bars, menus, tooltips).
- For list rows, use a `QListView` + custom `QStyledItemDelegate` (painting the thumbnail, texts and state icon), not one widget per row. Drive row animations from a small `QVariantAnimation` whose value the delegate reads.
- For the cross-fade, use `QGraphicsOpacityEffect` on the editor container and remove it when the animation finishes. Effects left in place make painting slower.
- One shared `ui/theme.py` holds all tokens (colours, radii, fonts, durations) and builds the QSS string. No hard-coded colours anywhere else.

## 5. Must not change

- Engine, vision, recorder logic, storage format, the import/export format, the run controller's safety behaviour (hide windows, F12 global stop, the problem → ask → retry/stop flow, the screen saved on stop).
- The UI stays in English and generic: no names of real apps, companies or people, and no real screenshots.
- `app.setQuitOnLastWindowClosed(False)` and explicit quit from the main window must stay. Our windows are hidden during runs and captures.
- No new runtime dependencies unless essential. Everything here is possible with PySide6-Essentials.

## 6. Done when

- [ ] One main window as in §1; every action that exists today is reachable (new, edit, run, run 1, simulate, test step, add/edit/reorder/delete step, record, mark list, save empty sample, duplicate, import, export, delete, tutorial, open logs, about).
- [ ] Tokens from §2 live in `ui/theme.py` only.
- [ ] The custom widgets from §3 exist and are used: pill, switch, live dot, step state icon, snackbar, recording capsule, run panel with ring, problem dialog, highlight overlay.
- [ ] The motion from §4 is in place and switches off with Windows animations off.
- [ ] Looks right at 100 %, 125 % and 150 % Windows scale (no blurry icons; custom painting uses device-independent pixels).
- [ ] `pytest` is green; the offscreen smoke tests are updated for the new window and cover each new custom widget being created and painted once.
- [ ] Screenshots of the new UI are in `docs/images/` and the README is updated where it describes the windows.
- [ ] `.\build.ps1` still produces the installer.
