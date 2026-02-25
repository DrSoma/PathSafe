#!/bin/bash
# Build a Linux AppImage for PathSafe
#
# Prerequisites:
#   - PyInstaller executables already built in dist/
#   - Running on Linux
#   - appimagetool available (downloaded automatically if missing)
#
# Usage:
#   chmod +x installer/build_appimage.sh
#   ./installer/build_appimage.sh

set -euo pipefail

APP_NAME="PathSafe"
APPDIR="dist/PathSafe.AppDir"

resolve_version() {
    local parsed_version
    parsed_version="$(sed -nE 's/^version = "([^"]+)"/\1/p' pyproject.toml | head -n 1)"
    if [ -z "${parsed_version}" ]; then
        echo "Could not parse version from pyproject.toml" >&2
        exit 1
    fi
    echo "${parsed_version}"
}

VERSION="${PATHSAFE_VERSION:-$(resolve_version)}"
APPIMAGE_NAME="${PATHSAFE_OUTPUT_NAME:-PathSafe-${VERSION}-x86_64.AppImage}"

echo "Building AppImage..."
echo "Version: ${VERSION}"
echo "Output: dist/${APPIMAGE_NAME}"

# Download appimagetool if not available
if ! command -v appimagetool &> /dev/null; then
    echo "Downloading appimagetool..."
    curl -Lo /tmp/appimagetool "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
    chmod +x /tmp/appimagetool
    APPIMAGETOOL=/tmp/appimagetool
else
    APPIMAGETOOL=appimagetool
fi

# Create AppDir structure
rm -rf "${APPDIR}"
mkdir -p "${APPDIR}/usr/bin"
mkdir -p "${APPDIR}/usr/share/applications"

# Copy executables
cp dist/pathsafe-gui "${APPDIR}/usr/bin/PathSafe"
cp dist/pathsafe "${APPDIR}/usr/bin/pathsafe"
chmod +x "${APPDIR}/usr/bin/PathSafe"
chmod +x "${APPDIR}/usr/bin/pathsafe"

# Copy desktop file
cp installer/pathsafe.desktop "${APPDIR}/pathsafe.desktop"
cp installer/pathsafe.desktop "${APPDIR}/usr/share/applications/pathsafe.desktop"

# Create AppRun
cat > "${APPDIR}/AppRun" << 'APPRUN'
#!/bin/bash
SELF=$(readlink -f "$0")
HERE=${SELF%/*}
exec "${HERE}/usr/bin/PathSafe" "$@"
APPRUN
chmod +x "${APPDIR}/AppRun"

# Copy application icon
cp pathsafe/assets/icon.png "${APPDIR}/pathsafe.png"
mkdir -p "${APPDIR}/usr/share/icons/hicolor/256x256/apps"
cp pathsafe/assets/icon.png "${APPDIR}/usr/share/icons/hicolor/256x256/apps/pathsafe.png"

# Build the AppImage
ARCH=x86_64 "${APPIMAGETOOL}" "${APPDIR}" "dist/${APPIMAGE_NAME}"

# Clean up
rm -rf "${APPDIR}"

echo "Done: dist/${APPIMAGE_NAME}"
