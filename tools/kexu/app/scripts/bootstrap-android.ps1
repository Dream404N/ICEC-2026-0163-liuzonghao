$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$toolsDir = Join-Path $project '.tools'
New-Item -ItemType Directory -Path $toolsDir -Force | Out-Null
$jdkDir = Join-Path $toolsDir 'jdk'
if (!(Test-Path -LiteralPath (Join-Path $jdkDir 'bin\java.exe'))) {
  $jdkZip = Join-Path $toolsDir 'microsoft-jdk.zip'
  & curl.exe -fL --connect-timeout 20 --max-time 600 --retry 2 -o $jdkZip 'https://aka.ms/download-jdk/microsoft-jdk-21.0.8-windows-x64.zip'
  if ($LASTEXITCODE -ne 0) { throw 'JDK download failed' }
  $unpack = Join-Path $toolsDir 'jdk-unpack'
  Expand-Archive -LiteralPath $jdkZip -DestinationPath $unpack -Force
  $source = Get-ChildItem -LiteralPath $unpack -Directory | Select-Object -First 1
  Move-Item -LiteralPath $source.FullName -Destination $jdkDir
}
$sdkDir = Join-Path $toolsDir 'android-sdk'
$manager = Join-Path $sdkDir 'cmdline-tools\latest\bin\sdkmanager.bat'
if (!(Test-Path -LiteralPath $manager)) {
  $sdkZip = Join-Path $toolsDir 'commandlinetools.zip'
  & curl.exe -fL --connect-timeout 20 --max-time 600 --retry 2 -o $sdkZip 'https://dl.google.com/android/repository/commandlinetools-win-13114758_latest.zip'
  if ($LASTEXITCODE -ne 0) { throw 'Android command line tools download failed' }
  $unpack = Join-Path $toolsDir 'sdk-unpack'
  Expand-Archive -LiteralPath $sdkZip -DestinationPath $unpack -Force
  New-Item -ItemType Directory -Path (Join-Path $sdkDir 'cmdline-tools') -Force | Out-Null
  Move-Item -LiteralPath (Join-Path $unpack 'cmdline-tools') -Destination (Join-Path $sdkDir 'cmdline-tools\latest')
}
$env:JAVA_HOME = $jdkDir
$env:ANDROID_HOME = $sdkDir
$env:ANDROID_SDK_ROOT = $sdkDir
1..50 | ForEach-Object { 'y' } | & $manager --sdk_root=$sdkDir --licenses
& $manager 'platform-tools' 'platforms;android-36' 'build-tools;36.0.0'
if ($LASTEXITCODE -ne 0) { throw 'Android SDK installation failed' }
if (!(Test-Path -LiteralPath (Join-Path $sdkDir 'platforms\android-36\android.jar'))) { throw 'Android SDK platform was not installed. Run sdkmanager --licenses and retry.' }
Write-Output 'Project-local JDK 21 and Android SDK 36 are ready. Run npm run android:build.'
