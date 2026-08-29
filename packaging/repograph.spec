# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build for the standalone repograph application.

Produces one self-contained executable per platform: repograph.exe on Windows,
repograph elsewhere. No Python installation is required to run it.
"""

import os
import sys

ROOT = os.path.abspath(os.path.join(os.getcwd()))
PACKAGES = os.path.join(ROOT, "packages")

source_paths = [
    os.path.join(PACKAGES, "repograph-core", "src"),
    os.path.join(PACKAGES, "repograph-render", "src"),
    os.path.join(PACKAGES, "repograph-cli", "src"),
    os.path.join(PACKAGES, "repograph-tui", "src"),
    os.path.join(PACKAGES, "repograph-ui", "src"),
]

hidden = [
    "repograph_core", "repograph_render", "repograph_cli", "repograph_tui", "repograph_ui",
    "repograph_core.languages.python_lang", "repograph_core.languages.javascript",
    "repograph_core.languages.others", "repograph_core.manifests.manifest",
    "repograph_core.manifests.lockfiles", "repograph_core.security.secrets",
    "repograph_core.security.patterns", "repograph_core.security.advisories",
    "repograph_core.security.sbom", "repograph_core.security.cvss",
]

analysis = Analysis(
    [os.path.join(ROOT, "packaging", "entry.py")],
    pathex=source_paths,
    binaries=[],
    datas=[],
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    # Nothing here needs a GUI toolkit or a scientific stack; excluding them keeps
    # the binary small and the build reproducible.
    excludes=["tkinter", "test", "unittest", "pydoc_data", "numpy", "PIL", "setuptools",
              "pip", "wheel", "matplotlib", "PyQt5", "PySide6"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="repograph",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
