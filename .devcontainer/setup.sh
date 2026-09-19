#!/usr/bin/env bash
# M175a Studio — Codespace bootstrap.
# 1. Writes local.properties so Gradle/AGP finds the SDK
# 2. Accepts all Android SDK licenses
# 3. Pre-downloads Gradle + dependencies so builds are instant later
set -euo pipefail

SDK="${ANDROID_HOME:-/usr/local/lib/android/sdk}"

# local.properties with the container's SDK path
if [ ! -f local.properties ] || ! grep -q '^sdk.dir=' local.properties; then
  echo "sdk.dir=$SDK" > local.properties
  echo "[setup] wrote local.properties -> $SDK"
fi

# Android SDK: platform 34 + build-tools 34 (AGP 8.5.2 requirements)
yes | "$SDK/cmdline-tools/latest/bin/sdkmanager" --licenses > /dev/null 2>&1 || true
"$SDK/cmdline-tools/latest/bin/sdkmanager" "platforms;android-34" "build-tools;34.0.0" \
  "platform-tools" > /dev/null
echo "[setup] SDK platform 34 + build-tools 34.0.0 ready"

# Warm the Gradle cache (first build is slow otherwise)
./gradlew --version > /dev/null
echo "[setup] gradle wrapper ready"
./gradlew assembleDebug testDebugUnitTest --no-daemon -q \
  && echo "[setup] BUILD OK — codespace is ready" \
  || echo "[setup] WARN: first build had issues — run ./gradlew assembleDebug to see errors"
