#!/bin/bash
# Build a Linux ARM64 (aarch64) AppImage for PathSafe
#
# For ARM devices: NVIDIA GB10 Blackwell, Raspberry Pi 5, Ampere, etc.
#
# Prerequisites:
#   - PyInstaller executables already built in dist/ (on an ARM64 host)
#   - Running on Linux aarch64
#   - appimagetool available (downloaded automatically if missing)
#
# Usage:
#   chmod +x installer/build_appimage_arm64.sh
#   ./installer/build_appimage_arm64.sh

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
APPIMAGE_NAME="${PATHSAFE_OUTPUT_NAME:-PathSafe-${VERSION}-aarch64.AppImage}"

echo "Building ARM64 AppImage..."
echo "Version: ${VERSION}"
echo "Architecture: aarch64"
echo "Output: dist/${APPIMAGE_NAME}"

# Verify we're on ARM64
MACHINE="$(uname -m)"
if [ "${MACHINE}" != "aarch64" ] && [ "${MACHINE}" != "arm64" ]; then
    echo "WARNING: Running on ${MACHINE}, expected aarch64/arm64."
    echo "The AppImage will match the host architecture, not ARM64."
fi

# Download appimagetool (ARM64 build) if not available
if ! command -v appimagetool &> /dev/null; then
    echo "Downloading appimagetool (aarch64)..."
    curl -Lo /tmp/appimagetool "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-aarch64.AppImage"
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
ARCH=aarch64 "${APPIMAGETOOL}" "${APPDIR}" "dist/${APPIMAGE_NAME}"

# Clean up
rm -rf "${APPDIR}"

echo "Done: dist/${APPIMAGE_NAME}"
