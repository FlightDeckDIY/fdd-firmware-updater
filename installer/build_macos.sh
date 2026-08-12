#!/usr/bin/env bash
# Build the FDD Firmware Updater .app for macOS (Apple Silicon).
# Run from the repo root: ./installer/build_macos.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# Resolve the Python 3 interpreter that meets our >=3.11 requirement.
# Prefer an explicit python3.x binary over the bare "python3" symlink so we
# don't accidentally pick up the Xcode/system 3.9 installation.
PYTHON=""
for candidate in python3.14 python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" &>/dev/null; then
        ver=$("$candidate" -c "import sys; print(sys.version_info[:2])")
        major=$("$candidate" -c "import sys; print(sys.version_info.major)")
        minor=$("$candidate" -c "import sys; print(sys.version_info.minor)")
        if [ "$major" -ge 3 ] && [ "$minor" -ge 11 ]; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "ERROR: Python 3.11 or newer is required but was not found on PATH." >&2
    echo "Install with: brew install python@3.13" >&2
    exit 1
fi
echo "==> Using Python: $PYTHON ($($PYTHON --version))"

echo "==> Installing Python dependencies..."
"$PYTHON" -m pip install --upgrade pip pyinstaller
"$PYTHON" -m pip install -e .

echo "==> Copying picotool (macOS arm64) to resources/tools/macos/..."
# Prefer a locally installed picotool via brew; fall back gracefully.
PICOTOOL_BIN="$(which picotool 2>/dev/null || true)"
if [ -n "$PICOTOOL_BIN" ]; then
    cp -f "$PICOTOOL_BIN" resources/tools/macos/picotool
    xattr -c resources/tools/macos/picotool 2>/dev/null || true  # strip Finder/quarantine xattrs
    echo "    Copied $PICOTOOL_BIN"
else
    echo "    WARNING: picotool not found on PATH. Install with: brew install picotool"
    echo "    The app will still work but picotool-based device inspection will be unavailable."
fi

# Build outside the repo. This repo may live under an iCloud-synced folder
# (e.g. ~/Documents), where the file provider stamps com.apple.FinderInfo onto
# the freshly written .app. codesign then rejects the bundle with "resource
# fork, Finder information, or similar detritus not allowed", and stripping the
# xattr doesn't stick because iCloud re-applies it. Building in a plain temp
# directory sidesteps this entirely; only the finished .dmg is copied back.
BUILD_DIR="$(mktemp -d "${TMPDIR:-/tmp}/fdd-updater-build.XXXXXX")"
trap 'rm -rf "$BUILD_DIR"' EXIT
echo "==> Staging build in $BUILD_DIR (outside the repo, so codesign can sign the bundle)"

echo "==> Running PyInstaller..."
"$PYTHON" -m PyInstaller installer/fdd_updater.spec --clean --noconfirm \
    --distpath "$BUILD_DIR/dist" --workpath "$BUILD_DIR/build"

APP="$BUILD_DIR/dist/FDD Firmware Updater.app"

echo "==> Verifying code signature..."
if codesign --verify --deep --strict "$APP"; then
    echo "    Signature OK (ad-hoc)."
else
    echo "    WARNING: signature verification failed — the .app may not launch on other Macs." >&2
fi

echo "==> Build output:"
ls -lh "$BUILD_DIR/dist/"

# Create a versioned .dmg for distribution and copy it back into the repo.
if command -v hdiutil &>/dev/null; then
    VERSION="$("$PYTHON" -c "import re,pathlib; print(re.search(r'^__version__ = \"([^\"]+)\"', pathlib.Path('fdd_updater/__init__.py').read_text(), re.M).group(1))")"
    DMG_NAME="FDD-Firmware-Updater-macOS-v${VERSION}.dmg"
    echo "==> Creating ${DMG_NAME} ..."
    hdiutil create \
        -volname "FDD Firmware Updater" \
        -srcfolder "$APP" \
        -ov -format UDZO \
        "$BUILD_DIR/${DMG_NAME}"

    mkdir -p dist
    cp -f "$BUILD_DIR/${DMG_NAME}" "dist/${DMG_NAME}"
    echo "==> DMG created: dist/${DMG_NAME}"
fi

echo "==> Done."
