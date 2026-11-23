# CLAUDE.md

Guidance for AI coding assistants working in this repository.

## What this is
AutoClicker Visual: a Windows desktop app (Python + PySide6) that repeats a recorded sequence of clicks for every item of a list on screen until the list is empty. It is vision-based: it captures the screen (mss), finds images with OpenCV template matching, and drives the mouse and keyboard (pynput). It is 100 % local, with no network, APIs or cloud.

## Golden rules
- **Fail safe.** When anything is uncertain (missing or ambiguous target, list not updating, user moving the mouse), stop and ask. Never add a code path that clicks "just in case".
- **Generic wording only.** Docs, code, tests, fixtures and commit messages describe the use case as "clicking through a list of pending items in any desktop app". Never name a specific third-party application or organisation.
- **No real screenshots in the repo.** Test fixtures are rendered from `tools/demo_list_app.py` by `tools/make_fixtures.py`.
- `.private/` is git-ignored and holds private notes plus `forbidden_words.txt`. The hooks in `tools/git-hooks` (installed with `.\build.ps1 -InstallHooks`) block commits that contain those words. Never commit anything from `.private/`.

## Layout
- `src/acv/engine.py`: run loop. Pure Python: screen, input and clock are injected, so keep it free of Qt and OS calls.
- `src/acv/vision.py`: matching (`locate` returns found / missing / ambiguous), `crop_unique` and row emptiness.
- `src/acv/desktop.py`: the only place for Windows/OS specifics (DPI awareness, monitors, capture, input).
- `src/acv/recorder.py`: global mouse/keyboard listeners → steps.
- `src/acv/ui/`: windows and dialogs. Long work runs off the GUI thread and talks to it through signals.
- `src/acv/model.py`, `src/acv/storage.py`: dataclasses with versioned JSON, and the per-user data folders.

## Commands
```powershell
.\build.ps1                                   # venv, deps, tests, PyInstaller, Inno Setup installer
$env:QT_QPA_PLATFORM="offscreen"; python -m pytest
$env:PYTHONPATH="src"; python -m acv          # run from source
python tools/demo_list_app.py                 # practice target app
```

## Conventions
- Coordinates passed to the engine and the input controllers are physical pixels relative to the work monitor. The process is per-monitor-v2 DPI aware.
- Bump `SCHEMA_VERSION` in `model.py` only for incompatible changes to `flow.json`. Unknown keys are ignored when loading.
- New logic in `engine.py` or `vision.py` comes with a test in `tests/`.
- UI text is in English.
