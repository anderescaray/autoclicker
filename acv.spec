# PyInstaller spec: one-folder build (faster start, fewer antivirus false positives than one-file).
# Build with:  python -m PyInstaller acv.spec --noconfirm   (build.ps1 does this for you)

a = Analysis(
    ["src/acv/__main__.py"],
    pathex=["src"],
    datas=[("src/acv/resources", "acv/resources")],
    hiddenimports=["pynput.keyboard._win32", "pynput.mouse._win32"],
    excludes=["tkinter", "unittest", "pydoc", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AutoClickerVisual",
    icon="installer/icon.ico",
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="AutoClickerVisual", upx=False)
