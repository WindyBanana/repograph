"""Turn the built binary into something a desktop can launch.

macOS gets a .app bundle, Linux a .desktop entry, Windows a shortcut script.
Kept in plain Python with no dependencies so the same code runs in CI and on a
laptop.
"""

from __future__ import annotations

import argparse
import os
import plistlib
import shutil
import stat
import sys
from typing import Optional

VERSION = "0.1.0"
BUNDLE_ID = "dev.repograph.app"

# A flat, legible mark: a document with a small dependency graph on it. Drawn as
# SVG so it can be converted per platform without shipping binary assets.
ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <rect width="512" height="512" rx="112" fill="#0f172a"/>
  <circle cx="168" cy="168" r="34" fill="#60a5fa"/>
  <circle cx="344" cy="150" r="26" fill="#f97316"/>
  <circle cx="356" cy="330" r="30" fill="#22d3ee"/>
  <circle cx="168" cy="352" r="26" fill="#a78bfa"/>
  <circle cx="256" cy="256" r="22" fill="#e2e8f0"/>
  <g stroke="#94a3b8" stroke-width="10" stroke-linecap="round" opacity="0.85">
    <line x1="168" y1="168" x2="256" y2="256"/>
    <line x1="344" y1="150" x2="256" y2="256"/>
    <line x1="356" y1="330" x2="256" y2="256"/>
    <line x1="168" y1="352" x2="256" y2="256"/>
  </g>
</svg>
"""

DESKTOP_ENTRY = """[Desktop Entry]
Type=Application
Name=repograph
GenericName=Repository architecture scanner
Comment=Scan a repository and produce architecture diagrams, reports and findings
Exec={exec_path}
Icon={icon}
Terminal=false
Categories=Development;IDE;
Keywords=architecture;diagram;dependencies;security;documentation;
StartupNotify=true
"""


def _chmod_x(path: str) -> None:
    mode = os.stat(path).st_mode
    os.chmod(path, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def macos_app(binary: str, out_dir: str, name: str = "repograph") -> str:
    """A double-clickable .app that opens the UI."""
    app = os.path.join(out_dir, f"{name}.app")
    macos_dir = os.path.join(app, "Contents", "MacOS")
    resources = os.path.join(app, "Contents", "Resources")
    shutil.rmtree(app, ignore_errors=True)
    os.makedirs(macos_dir, exist_ok=True)
    os.makedirs(resources, exist_ok=True)

    target = os.path.join(macos_dir, name)
    shutil.copy2(binary, target)
    _chmod_x(target)

    with open(os.path.join(resources, "icon.svg"), "w", encoding="utf-8") as handle:
        handle.write(ICON_SVG)

    info = {
        "CFBundleName": "repograph",
        "CFBundleDisplayName": "repograph",
        "CFBundleExecutable": name,
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleVersion": VERSION,
        "CFBundleShortVersionString": VERSION,
        "CFBundlePackageType": "APPL",
        "CFBundleInfoDictionaryVersion": "6.0",
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
        # Opening the UI is the point of double-clicking; the same binary is the
        # CLI when it is run from a terminal.
        "LSEnvironment": {"REPOGRAPH_FORCE_UI": "1"},
        "LSApplicationCategoryType": "public.app-category.developer-tools",
        "NSHumanReadableCopyright": "MIT licensed",
    }
    with open(os.path.join(app, "Contents", "Info.plist"), "wb") as handle:
        plistlib.dump(info, handle)
    return app


def linux_desktop_entry(exec_path: str, out_dir: str, icon_path: str = "") -> str:
    os.makedirs(out_dir, exist_ok=True)
    icon = icon_path or os.path.join(out_dir, "repograph.svg")
    if not icon_path:
        with open(icon, "w", encoding="utf-8") as handle:
            handle.write(ICON_SVG)
    path = os.path.join(out_dir, "repograph.desktop")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(DESKTOP_ENTRY.format(exec_path=exec_path, icon=icon))
    _chmod_x(path)
    return path


def windows_shortcut_script(exec_path: str, out_dir: str) -> str:
    """A .vbs that Explorer can run to create the Start Menu shortcut."""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "create-shortcut.vbs")
    script = f'''' Creates a Start Menu shortcut for repograph.
Set shell = CreateObject("WScript.Shell")
startMenu = shell.SpecialFolders("Programs")
Set link = shell.CreateShortcut(startMenu & "\\repograph.lnk")
link.TargetPath = "{exec_path}"
link.Description = "Scan a repository and produce architecture diagrams and reports"
link.WorkingDirectory = shell.SpecialFolders("MyDocuments")
link.Save
'''
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(script)
    return path


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Build desktop wrappers around the binary")
    parser.add_argument("binary", help="path to the built repograph executable")
    parser.add_argument("-o", "--out", default="dist", help="output directory")
    parser.add_argument("--platform", default=sys.platform,
                        help="darwin, linux or win32 (defaults to this machine)")
    args = parser.parse_args(argv)

    binary = os.path.abspath(args.binary)
    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)
    if not os.path.isfile(binary):
        print(f"no such binary: {binary}", file=sys.stderr)
        return 2

    if args.platform.startswith("darwin"):
        print(macos_app(binary, out_dir))
    elif args.platform.startswith("win"):
        print(windows_shortcut_script(binary, out_dir))
    else:
        print(linux_desktop_entry(binary, out_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
