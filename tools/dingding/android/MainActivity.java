package com.icec.dingding;

import android.Manifest;
import android.app.Activity;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.provider.CalendarContract;
import android.provider.MediaStore;
import android.text.TextUtils;
import android.webkit.JavascriptInterface;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStream;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.TimeZone;

/**
 * 叮叮课表 · 安卓版。
 *
 * 刻意不做的事：不申请 INTERNET（课表全在本机）、不常驻服务、不开机自启、
 * 不建 AlarmManager 定时任务。提醒交给手机自带日历 —— 写入日历时每节课
 * 附一条「提前 20 分钟」的系统提醒，由系统负责弹出，清后台也不会漏。
 *
 * 界面就是 assets/index.html（与 Windows 版同一个文件），这里只提供三个
 * 本机能力：写日历、发通知、导出 ics。
 */
public class MainActivity extends Activity {

    private static final String CHANNEL = "dingding_class";
    private static final int REQ_CALENDAR = 1;
    private WebView web;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        ensureChannel();
        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setAllowFileAccess(true);
        web.addJavascriptInterface(new Bridge(), "DingDing");
        web.loadUrl("file:///android_asset/index.html");
        setContentView(web);
    }

    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) {
            web.goBack();
        } else {
            super.onBackPressed();
        }
    }

    private void ensureChannel() {
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationManager nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
            NotificationChannel ch = new NotificationChannel(
                    CHANNEL, "上课提醒", NotificationManager.IMPORTANCE_HIGH);
            ch.setDescription("课前 20 分钟的提醒");
            nm.createNotificationChannel(ch);
        }
    }

    private void toast(final String msg) {
        runOnUiThread(new Runnable() {
            @Override public void run() {
                Toast.makeText(MainActivity.this, msg, Toast.LENGTH_LONG).show();
            }
        });
    }

    private class Bridge {

        /** 把精简课表一次性写入系统日历，每节附提前 20 分钟提醒；重复点不会产生重复项。 */
        @JavascriptInterface
        public String writeCalendar(String json) {
            if (checkSelfPermission(Manifest.permission.WRITE_CALENDAR) != PackageManager.PERMISSION_GRANTED
                    || checkSelfPermission(Manifest.permission.READ_CALENDAR) != PackageManager.PERMISSION_GRANTED) {
                runOnUiThread(new Runnable() {
                    @Override public void run() {
                        requestPermissions(new String[]{
                                Manifest.permission.READ_CALENDAR,
                                Manifest.permission.WRITE_CALENDAR}, REQ_CALENDAR);
                    }
                });
                return "先允许「日历」权限，然后点一次「写入手机日历」就好。";
            }
            try {
                JSONArray arr = new JSONArray(json);
                long calId = pickCalendar();
                if (calId < 0) {
                    return "没找到可写的日历。可以先点「保存课表 .ics」，再用日历 App 导入。";
                }
                SimpleDateFormat fmt = new SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.CHINA);
                fmt.setTimeZone(TimeZone.getDefault());
                List<long[]> spans = new ArrayList<long[]>();
                List<String[]> texts = new ArrayList<String[]>();
                long min = Long.MAX_VALUE, max = 0;
                for (int i = 0; i < arr.length(); i++) {
                    JSONObject e = arr.getJSONObject(i);
                    long st = fmt.parse(e.getString("d") + " " + e.getString("s")).getTime();
                    long en = fmt.parse(e.getString("d") + " " + e.getString("e")).getTime();
                    JSONArray ns = e.getJSONArray("n"), ms = e.getJSONArray("m");
                    String names = join(ns, " / "), rooms = join(ms, " / ");
                    spans.add(new long[]{st, en});
                    texts.add(new String[]{names, rooms,
                            "第" + e.getInt("w") + "周 · " + e.getString("pl") + " · 叮叮课表"});
                    if (st < min) min = st;
                    if (en > max) max = en;
                }
                Set<String> existing = existingKeys(min, max);
                int added = 0, skipped = 0;
                for (int i = 0; i < spans.size(); i++) {
                    long st = spans.get(i)[0], en = spans.get(i)[1];
                    String[] t = texts.get(i);
                    String key = st + "|" + t[0];
                    if (existing.contains(key)) { skipped++; continue; }
                    ContentValues v = new ContentValues();
                    v.put(CalendarContract.Events.CALENDAR_ID, calId);
                    v.put(CalendarContract.Events.TITLE, t[0]);
                    v.put(CalendarContract.Events.EVENT_LOCATION, t[1]);
                    v.put(CalendarContract.Events.DESCRIPTION, t[2]);
                    v.put(CalendarContract.Events.DTSTART, st);
                    v.put(CalendarContract.Events.DTEND, en);
                    v.put(CalendarContract.Events.EVENT_TIMEZONE, TimeZone.getDefault().getID());
                    v.put(CalendarContract.Events.HAS_ALARM, 1);
                    Uri uri = getContentResolver().insert(CalendarContract.Events.CONTENT_URI, v);
                    if (uri == null) continue;
                    long eventId = Long.parseLong(uri.getLastPathSegment());
                    ContentValues r = new ContentValues();
                    r.put(CalendarContract.Reminders.EVENT_ID, eventId);
                    r.put(CalendarContract.Reminders.MINUTES, 20);
                    r.put(CalendarContract.Reminders.METHOD, CalendarContract.Reminders.METHOD_ALERT);
                    getContentResolver().insert(CalendarContract.Reminders.CONTENT_URI, r);
                    added++;
                }
                String out = "写入完成：新增 " + added + " 节，已存在跳过 " + skipped
                        + " 节。每节都带提前 20 分钟提醒，之后交给手机日历，不用开着这个 App。";
                toast(out);
                return out;
            } catch (Exception e) {
                return "写入失败：" + e.getClass().getSimpleName() + " " + e.getMessage();
            }
        }

        /** 页面开着且到点时弹一条即时通知；真正的兜底是日历提醒。 */
        @JavascriptInterface
        public void notify(String title, String text) {
            try {
                PendingIntent pi = PendingIntent.getActivity(MainActivity.this, 0,
                        new Intent(MainActivity.this, MainActivity.class),
                        PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
                Notification.Builder b = (Build.VERSION.SDK_INT >= 26)
                        ? new Notification.Builder(MainActivity.this, CHANNEL)
                        : new Notification.Builder(MainActivity.this);
                Notification n = b.setSmallIcon(android.R.drawable.ic_dialog_info)
                        .setContentTitle(title)
                        .setContentText(text)
                        .setStyle(new Notification.BigTextStyle().bigText(text))
                        .setAutoCancel(true)
                        .setContentIntent(pi)
                        .build();
                NotificationManager nm =
                        (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
                nm.notify((int) (System.currentTimeMillis() % 100000), n);
            } catch (Exception e) {
                toast("通知没发出来：" + e.getClass().getSimpleName());
            }
        }

        /** 导出同一份 ics，方便给 Windows / 另一台手机用。 */
        @JavascriptInterface
        public void saveIcs(String text) {
            try {
                String where;
                if (Build.VERSION.SDK_INT >= 29) {
                    ContentValues v = new ContentValues();
                    v.put(MediaStore.Downloads.DISPLAY_NAME, "叮叮课表.ics");
                    v.put(MediaStore.Downloads.MIME_TYPE, "text/calendar");
                    v.put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS);
                    Uri u = getContentResolver().insert(
                            MediaStore.Downloads.EXTERNAL_CONTENT_URI, v);
                    OutputStream os = getContentResolver().openOutputStream(u);
                    os.write(text.getBytes("UTF-8"));
                    os.close();
                    where = "Download/叮叮课表.ics";
                } else {
                    File dir = getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS);
                    File f = new File(dir, "叮叮课表.ics");
                    FileOutputStream os = new FileOutputStream(f);
                    os.write(text.getBytes("UTF-8"));
                    os.close();
                    where = f.getAbsolutePath();
                }
                toast("已保存：" + where);
            } catch (Exception e) {
                toast("保存失败：" + e.getClass().getSimpleName());
            }
        }

        private String join(JSONArray a, String sep) throws Exception {
            List<String> out = new ArrayList<String>();
            for (int i = 0; i < a.length(); i++) {
                String s = a.getString(i);
                if (s != null && s.length() > 0) out.add(s);
            }
            return TextUtils.join(sep, out);
        }

        /** 取第一个可见日历。不查 access_level：该列的部分常量在旧 SDK 里是隐藏 API。 */
        private long pickCalendar() {
            Cursor c = getContentResolver().query(
                    CalendarContract.Calendars.CONTENT_URI,
                    new String[]{CalendarContract.Calendars._ID},
                    CalendarContract.Calendars.VISIBLE + "=1", null, null);
            long id = -1;
            if (c != null) {
                if (c.moveToFirst()) id = c.getLong(0);
                c.close();
            }
            return id;
        }

        private Set<String> existingKeys(long min, long max) {
            Set<String> out = new HashSet<String>();
            Cursor c = getContentResolver().query(
                    CalendarContract.Events.CONTENT_URI,
                    new String[]{CalendarContract.Events.DTSTART,
                            CalendarContract.Events.TITLE},
                    CalendarContract.Events.DTSTART + ">=? AND "
                            + CalendarContract.Events.DTSTART + "<=?",
                    new String[]{String.valueOf(min), String.valueOf(max)}, null);
            if (c != null) {
                while (c.moveToNext()) {
                    out.add(c.getLong(0) + "|" + c.getString(1));
                }
                c.close();
            }
            return out;
        }
    }
}
