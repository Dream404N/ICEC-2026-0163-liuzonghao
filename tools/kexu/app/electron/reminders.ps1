param([ValidateSet('replace','append','status','register')][string]$Action, [string]$DataPath, [string]$AppId)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
if ($Action -eq 'register') {
  $registration = Get-Content -LiteralPath $DataPath -Raw -Encoding UTF8 | ConvertFrom-Json
  $key = 'HKCU:\Software\Classes\AppUserModelId\' + $AppId
  New-Item -Path $key -Force | Out-Null
  New-ItemProperty -Path $key -Name DisplayName -Value ([string]$registration.displayName) -PropertyType String -Force | Out-Null
  New-ItemProperty -Path $key -Name IconUri -Value ([string]$registration.executable) -PropertyType String -Force | Out-Null
  New-ItemProperty -Path $key -Name ShowInSettings -Value 1 -PropertyType DWord -Force | Out-Null
  New-ItemProperty -Path $key -Name CustomActivator -Value ([string]$registration.clsid) -PropertyType String -Force | Out-Null
  New-Item -Path ('HKCU:\Software\Classes\CLSID\' + $registration.clsid) -Force | Out-Null
  @{ registered = $true } | ConvertTo-Json -Compress
  exit 0
}
$null = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
$null = [Windows.UI.Notifications.ToastNotifier, Windows.UI.Notifications, ContentType = WindowsRuntime]
$null = [Windows.UI.Notifications.NotificationSetting, Windows.UI.Notifications, ContentType = WindowsRuntime]
$null = [Windows.UI.Notifications.ScheduledToastNotification, Windows.UI.Notifications, ContentType = WindowsRuntime]
$null = [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]
$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($AppId)
if ($Action -eq 'status') {
  $settingName = 'unknown'
  try { $settingName = $notifier.get_Setting().ToString() } catch {
    if ($_.Exception.ToString() -notmatch '80070490') { throw }
  }
  if ($settingName -ne 'unknown' -and $settingName -ne 'Enabled') { throw ('Notifications: ' + $settingName) }
  $pending = @($notifier.GetScheduledToastNotifications())
  @{ count = $pending.Count; permission = $settingName } | ConvertTo-Json -Compress
  exit 0
}
$data = Get-Content -LiteralPath $DataPath -Raw -Encoding UTF8 | ConvertFrom-Json
$planned = @()
foreach ($reminder in $data.reminders) {
  $time = [DateTimeOffset]::Parse($reminder.at)
  if ($time -le [DateTimeOffset]::Now) { continue }
  $title = [System.Security.SecurityElement]::Escape([string]$reminder.title)
  $body = [System.Security.SecurityElement]::Escape([string]$reminder.body)
  $audio = if ($data.sound) { '<audio src="ms-winsoundevent:Notification.Reminder" />' } else { '<audio silent="true" />' }
  $xmlText = '<toast><visual><binding template="ToastGeneric"><text>' + $title + '</text><text>' + $body + '</text></binding></visual>' + $audio + '<actions><input id="snoozeTime" type="selection" defaultInput="5"><selection id="5" content="5 min" /><selection id="10" content="10 min" /></input><action activationType="system" arguments="snooze" hint-inputId="snoozeTime" content="Snooze" /><action activationType="system" arguments="dismiss" content="Dismiss" /></actions></toast>'
  $xml = [Windows.Data.Xml.Dom.XmlDocument]::new()
  $xml.LoadXml($xmlText)
  $toast = [Windows.UI.Notifications.ScheduledToastNotification]::new($xml, $time)
  $toast.Id = 'k' + [string]$reminder.id
  $planned += $toast
}
if ($Action -eq 'replace') { foreach ($old in $notifier.GetScheduledToastNotifications()) { $notifier.RemoveFromSchedule($old) } }
foreach ($toast in $planned) { $notifier.AddToSchedule($toast) }
$actual = @($notifier.GetScheduledToastNotifications())
@{ count = $actual.Count } | ConvertTo-Json -Compress
