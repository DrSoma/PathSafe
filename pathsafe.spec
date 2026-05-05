# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for PathSafe: builds standalone executables.

Build with:
    pip install pyinstaller
    pyinstaller pathsafe.spec

Output: dist/pathsafe (Linux/Mac) or dist/pathsafe.exe (Windows)
        dist/pathsafe-gui (Linux/Mac) or dist/pathsafe-gui.exe (Windows)
"""

block_cipher = None

import sys

_datas = [
    ('pathsafe/assets/icon.png', 'pathsafe/assets'),
]

# Platform-specific icon for the executable
if sys.platform == 'win32':
    _icon = 'pathsafe/assets/icon.ico'
elif sys.platform == 'darwin':
    _icon = 'pathsafe/assets/icon.icns'
else:
    _icon = None

_hidden = [
    'pathsafe',
    'pathsafe.models',
    'pathsafe.tiff',
    'pathsafe.scanner',
    'pathsafe.deidentifier',
    'pathsafe.verify',
    'pathsafe.report',
    'pathsafe.openslide_utils',
    'pathsafe.formats',
    'pathsafe.formats.base',
    'pathsafe.formats.ndpi',
    'pathsafe.formats.svs',
    'pathsafe.formats.mrxs',
    'pathsafe.formats.dicom',
    'pathsafe.formats.bif',
    'pathsafe.formats.scn',
    'pathsafe.formats.generic_tiff',
    'pathsafe.log',
    'pathsafe.converter',
    'pathsafe.cli',
    'pathsafe.cli._common',
    'pathsafe.cli._gui_cmd',
    'pathsafe.cli.scan',
    'pathsafe.cli.deidentify',
    'pathsafe.cli.verify',
    'pathsafe.cli.info',
    'pathsafe.cli.convert',
    'pathsafe.cli.pipeline',
    'tifffile',
    'numpy',
    'fpdf2',
    'openslide',
    'imagecodecs',
]

# --- CLI executable ---
a = Analysis(
    ['pathsafe/cli/__main__.py'],
    pathex=['.'],
    binaries=[],
    datas=_datas,
    hiddenimports=_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='pathsafe',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    icon=_icon,
)

# --- GUI executable ---
a_gui = Analysis(
    ['pathsafe/gui_qt.py'],
    pathex=['.'],
    binaries=[],
    datas=_datas,
    hiddenimports=_hidden + [
        'pathsafe.gui_qt',
        'pathsafe.gui',
        'pathsafe.gui.window',
        'pathsafe.gui.menus',
        'pathsafe.gui.dialogs',
        'pathsafe.gui.panels',
        'pathsafe.gui.panels.deidentify_panel',
        'pathsafe.gui.panels.convert_panel',
        'pathsafe.gui.themes',
        'pathsafe.gui.widgets',
        'pathsafe.gui.workers',
        'pathsafe.gui.toast',
        'pathsafe.gui.pipeline_tab',
        'PySide6',
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)

pyz_gui = PYZ(a_gui.pure, a_gui.zipped_data, cipher=block_cipher)

exe_gui = EXE(
    pyz_gui,
    a_gui.scripts,
    a_gui.binaries,
    a_gui.zipfiles,
    a_gui.datas,
    [],
    name='pathsafe-gui',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # No console window for GUI
    icon=_icon,
)
