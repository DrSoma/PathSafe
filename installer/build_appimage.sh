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

set -e

APP_NAME="PathSafe"
VERSION="1.0.0"
APPIMAGE_NAME="PathSafe-${VERSION}-x86_64.AppImage"
APPDIR="dist/PathSafe.AppDir"

echo "Building AppImage..."

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

# Create a simple SVG icon (placeholder)
cat > "${APPDIR}/pathsafe.svg" << 'SVG'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="12" fill="#1e1e2e"/>
  <text x="32" y="42" font-family="Arial" font-size="28" font-weight="bold" fill="#89b4fa" text-anchor="middle">PS</text>
</svg>
SVG

# Build the AppImage
ARCH=x86_64 "${APPIMAGETOOL}" "${APPDIR}" "dist/${APPIMAGE_NAME}"

# Clean up
rm -rf "${APPDIR}"

echo "Done: dist/${APPIMAGE_NAME}"
