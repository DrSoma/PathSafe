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

set -e

APP_NAME="PathSafe"
VERSION="1.0.0"
DMG_NAME="PathSafe-${VERSION}.dmg"
APP_BUNDLE="dist/${APP_NAME}.app"

echo "Building ${APP_NAME}.app bundle..."

# Create .app bundle structure
rm -rf "${APP_BUNDLE}"
mkdir -p "${APP_BUNDLE}/Contents/MacOS"
mkdir -p "${APP_BUNDLE}/Contents/Resources"

# Copy executables
cp dist/pathsafe-gui "${APP_BUNDLE}/Contents/MacOS/PathSafe"
cp dist/pathsafe "${APP_BUNDLE}/Contents/MacOS/pathsafe"
chmod +x "${APP_BUNDLE}/Contents/MacOS/PathSafe"
chmod +x "${APP_BUNDLE}/Contents/MacOS/pathsafe"

# Copy icon
cp pathsafe/assets/icon.icns "${APP_BUNDLE}/Contents/Resources/icon.icns"

# Create Info.plist
cat > "${APP_BUNDLE}/Contents/Info.plist" << 'PLIST'
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
    <string>1.0.0</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0.0</string>
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
