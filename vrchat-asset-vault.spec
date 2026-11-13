# PyInstaller spec for the Windows .exe (double-click, no Python needed).
# Build on Windows with: pip install .[gui] pyinstaller && pyinstaller vrchat-asset-vault.spec
# GitHub Actions (.github/workflows/build-windows.yml) does this on every release tag.
# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ["src/vrchat_asset_vault/__main__.py"],
    pathex=["src"],
    binaries=[],
    datas=[],
    hiddenimports=["vrchat_asset_vault.gui"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
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
    name="VRChat Asset Vault",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
