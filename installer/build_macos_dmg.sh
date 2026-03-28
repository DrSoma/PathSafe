#!/bin/bash
# Build a macOS .dmg installer for PathSafe
#
# Prerequisites:
#   - PyInstaller executables already built in dist/
#   - Running on macOS
#
# Usage:
#   chmod +x installer/build_macos_dmg.sh
#   ./installer/build_macos_dmg.sh

set -euo pipefail

APP_NAME="PathSafe"
APP_BUNDLE="dist/${APP_NAME}.app"

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
DMG_NAME="${PATHSAFE_OUTPUT_NAME:-PathSafe-${VERSION}.dmg}"

echo "Building ${APP_NAME}.app bundle..."
echo "Version: ${VERSION}"
echo "Output: dist/${DMG_NAME}"

# Create .app bundle structure
rm -rf "${APP_BUNDLE}"
mkdir -p "${APP_BUNDLE}/Contents/MacOS"
mkdir -p "${APP_BUNDLE}/Contents/Resources"

# Copy executables
cp dist/pathsafe-gui "${APP_BUNDLE}/Contents/MacOS/PathSafe"
chmod +x "${APP_BUNDLE}/Contents/MacOS/PathSafe"

# Keep the CLI helper under a non-colliding name on case-insensitive filesystems.
if [ -f "dist/pathsafe" ]; then
    cp dist/pathsafe "${APP_BUNDLE}/Contents/MacOS/pathsafe-cli"
    chmod +x "${APP_BUNDLE}/Contents/MacOS/pathsafe-cli"
fi

# Copy icon
cp pathsafe/assets/icon.icns "${APP_BUNDLE}/Contents/Resources/icon.icns"

# Create Info.plist
cat > "${APP_BUNDLE}/Contents/Info.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>PathSafe</string>
    <key>CFBundleDisplayName</key>
    <string>PathSafe</string>
    <key>CFBundleIdentifier</key>
    <string>com.pathsafe.app</string>
    <key>CFBundleVersion</key>
    <string>${VERSION}</string>
    <key>CFBundleShortVersionString</key>
    <string>${VERSION}</string>
    <key>CFBundleIconFile</key>
    <string>icon</string>
    <key>CFBundleExecutable</key>
    <string>PathSafe</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>LSMinimumSystemVersion</key>
    <string>10.15</string>
</dict>
</plist>
PLIST

echo "Creating DMG..."

# Create a temporary DMG directory
DMG_DIR="dist/dmg"
rm -rf "${DMG_DIR}"
mkdir -p "${DMG_DIR}"

# Copy app bundle
cp -R "${APP_BUNDLE}" "${DMG_DIR}/"

# Create symlink to Applications
ln -s /Applications "${DMG_DIR}/Applications"

# Create the DMG
rm -f "dist/${DMG_NAME}"
hdiutil create -volname "${APP_NAME}" \
    -srcfolder "${DMG_DIR}" \
    -ov -format UDZO \
    "dist/${DMG_NAME}"

# Clean up
rm -rf "${DMG_DIR}"

echo "Done: dist/${DMG_NAME}"
