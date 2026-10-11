#!/usr/bin/env bash
# Build the APK on this PC and publish it to the rolling "latest" release —
# the same steps as .github/workflows/android.yml, without spending any
# GitHub Actions minutes (the account's allowance ran out 2026-09-08).
#
#   bash tools/build_apk_local.sh            build + publish
#   bash tools/build_apk_local.sh --no-publish
#
# Needs: JDK 17, Android SDK with platforms;android-35 (C:\Users\arnod\AndroidSdk),
# Gradle 8.11.1. versionCode must beat every earlier build or the phone keeps
# the old one, so it is one above the highest used by CI or a previous local build.
set -euo pipefail
cd "$(dirname "$0")/.."

export ANDROID_HOME="${ANDROID_HOME:-C:/Users/arnod/AndroidSdk}"
GRADLE="${GRADLE:-$(ls -d "$HOME"/.gradle/wrapper/dists/gradle-8.11.1-bin/*/gradle-8.11.1/bin/gradle | head -1)}"
BT="$ANDROID_HOME/build-tools/36.1.0"

last_ci=$(gh run list -R Apn0/Box-Inventory-Storage -w "Build APK" -L 1 --json number --jq ".[0].number" 2>/dev/null || echo 0)
last_local=$(cat android/.last_version_code 2>/dev/null || echo 0)
code=$(( (last_ci > last_local ? last_ci : last_local) + 1 ))

python build.py >/dev/null
# The page is ES modules, which a browser refuses to load over file:// — and the
# APK opens it from file:///android_asset/. So the phone gets the inlined build.
python tools/bundle_single_file.py >/dev/null
mkdir -p android/app/src/main/assets
cp dist/index.html android/app/src/main/assets/index.html
trap 'rm -f android/app/src/main/assets/index.html' EXIT

(cd android && "$GRADLE" assembleDebug --no-daemon -q -PappVersionCode="$code")
apk=android/app/build/outputs/apk/debug/app-debug.apk
"$BT/aapt2.exe" dump badging "$apk" | head -1
echo "$code" > android/.last_version_code

# build.py stamps today's date into these; do not leave that as a stray diff
git checkout -- data/inventory.json data/snapshot.js 2>/dev/null || true

if [[ "${1:-}" != "--no-publish" ]]; then
  out="$(mktemp -d)/box-inventory.apk"
  cp "$apk" "$out"
  gh release upload latest "$out" --clobber -R Apn0/Box-Inventory-Storage
  gh release edit latest -R Apn0/Box-Inventory-Storage --notes \
    "Debug build of commit $(git rev-parse --short HEAD) (versionCode $code), built locally $(date +%F)."
  echo "published versionCode $code"
fi
