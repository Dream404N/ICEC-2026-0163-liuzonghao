package com.icec.dingding;

import android.app.AlarmManager;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Build;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.text.SimpleDateFormat;
import java.util.Locale;
import java.util.TimeZone;

/**
 * 叮叮课表 · 系统闹钟提醒。
 *
 * 这里没有 Service、没有前台进程、没有轮询：把未来 7 天的上课提醒点一次性交给
 * Android 系统的 AlarmManager 持有。到点由系统拉起本 BroadcastReceiver 发通知，
 * 所以 App 被划掉、长期不开、甚至重启后（BOOT_COMPLETED 重排）都能响。
 *
 * 可靠性边界（不吹）：Android 12+ 用户可在设置里关掉「精确闹钟」；
 * Android 13+ 需要通知权限；部分国产 ROM 会冻结开机广播或强停后不再唤醒。
 * 真正最稳的一层仍是 writeCalendar() 写进系统日历的提前 20 分钟提醒。
 */
public class RemindReceiver extends BroadcastReceiver {

    public static final String ACTION_FIRE = "com.icec.dingding.FIRE";
    public static final String ACTION_RESCHEDULE = "com.icec.dingding.RESCHEDULE";
    private static final String CHANNEL = "dingding_class";
    private static final long WINDOW_MS = 7L * 24 * 60 * 60 * 1000;

    @Override
    public void onReceive(Context ctx, Intent intent) {
        String action = intent.getAction();
        if (ACTION_FIRE.equals(action)) {
            show(ctx,
                    intent.getStringExtra("title"),
                    intent.getStringExtra("text"),
                    intent.getIntExtra("id", 1));
            // 滚动补排：每响一次就把未来 7 天的窗口重新铺一遍，不会越用越少。
            scheduleAll(ctx);
        } else if (Intent.ACTION_BOOT_COMPLETED.equals(action)
                || Intent.ACTION_MY_PACKAGE_REPLACED.equals(action)
                || ACTION_RESCHEDULE.equals(action)) {
            scheduleAll(ctx);
        }
    }

    static void ensureChannel(Context ctx) {
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationManager nm =
                    (NotificationManager) ctx.getSystemService(Context.NOTIFICATION_SERVICE);
            NotificationChannel ch = new NotificationChannel(
                    CHANNEL, "上课提醒", NotificationManager.IMPORTANCE_HIGH);
            ch.setDescription("课前 20 分钟 · 叮叮课表系统闹钟");
            nm.createNotificationChannel(ch);
        }
    }

    static void show(Context ctx, String title, String text, int id) {
        try {
            ensureChannel(ctx);
            PendingIntent pi = PendingIntent.getActivity(ctx, 0,
                    new Intent(ctx, MainActivity.class),
                    PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
            Notification.Builder b = (Build.VERSION.SDK_INT >= 26)
                    ? new Notification.Builder(ctx, CHANNEL)
                    : new Notification.Builder(ctx);
            Notification n = b.setSmallIcon(android.R.drawable.ic_dialog_info)
                    .setContentTitle(title == null ? "叮叮课表" : title)
                    .setContentText(text == null ? "" : text)
                    .setStyle(new Notification.BigTextStyle().bigText(text))
                    .setAutoCancel(true)
                    .setContentIntent(pi)
                    .build();
            NotificationManager nm =
                    (NotificationManager) ctx.getSystemService(Context.NOTIFICATION_SERVICE);
            nm.notify(id, n);
        } catch (Exception ignored) {
            // 通知权限被关时系统直接拒发；不假装成功，也不写假日志。
        }
    }

    /** 把未来 7 天的提醒点注册进系统闹钟，返回成功注册条数。 */
    static int scheduleAll(Context ctx) {
        AlarmManager am = (AlarmManager) ctx.getSystemService(Context.ALARM_SERVICE);
        if (am == null) return 0;
        try {
            JSONArray arr = readCourses(ctx);
            SimpleDateFormat fmt = new SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.CHINA);
            fmt.setTimeZone(TimeZone.getDefault());
            long now = System.currentTimeMillis();
            long end = now + WINDOW_MS;
            int count = 0;
            for (int i = 0; i < arr.length(); i++) {
                JSONObject e = arr.getJSONObject(i);
                long fire = fmt.parse(e.getString("d") + " " + e.getString("r")).getTime();
                if (fire <= now || fire > end) continue;
                String names = join(e.getJSONArray("n"), " / ");
                String rooms = join(e.getJSONArray("m"), " / ");
                String key = e.getString("d") + "-" + e.getString("p");
                Intent in = new Intent(ctx, RemindReceiver.class).setAction(ACTION_FIRE);
                in.putExtra("title", "叮叮课表 · 该去上课了");
                in.putExtra("text", e.getString("s") + " " + names
                        + (rooms.length() > 0 ? " · " + rooms : ""));
                in.putExtra("id", key.hashCode() & 0x7fffffff);
                PendingIntent pi = PendingIntent.getBroadcast(ctx,
                        key.hashCode() & 0x7fffffff, in,
                        PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
                setAlarm(am, fire, pi);
                count++;
            }
            return count;
        } catch (Exception e) {
            return 0;
        }
    }

    /** 10 秒后由系统闹钟发一条测试通知：退出 App 后也能验证「无后台进程」这条链路。 */
    static void scheduleTest(Context ctx, int seconds) {
        AlarmManager am = (AlarmManager) ctx.getSystemService(Context.ALARM_SERVICE);
        if (am == null) return;
        Intent in = new Intent(ctx, RemindReceiver.class).setAction(ACTION_FIRE);
        in.putExtra("title", "叮叮课表 · 后台闹钟测试");
        in.putExtra("text", "这条由系统闹钟发出。如果你已经退出 App 还看到它，说明后台提醒是通的。");
        in.putExtra("id", 900001);
        PendingIntent pi = PendingIntent.getBroadcast(ctx, 900001, in,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        setAlarm(am, System.currentTimeMillis() + seconds * 1000L, pi);
    }

    private static void setAlarm(AlarmManager am, long at, PendingIntent pi) {
        try {
            if (Build.VERSION.SDK_INT >= 23) {
                am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pi);
            } else {
                am.setExact(AlarmManager.RTC_WAKEUP, at, pi);
            }
        } catch (SecurityException denied) {
            // 用户关掉了「精确闹钟」权限：退化成普通闹钟，可能晚几分钟，但不静默失败。
            am.set(AlarmManager.RTC_WAKEUP, at, pi);
        }
    }

    private static JSONArray readCourses(Context ctx) throws Exception {
        InputStream is = ctx.getAssets().open("courses.json");
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        byte[] buf = new byte[4096];
        int n;
        while ((n = is.read(buf)) > 0) bos.write(buf, 0, n);
        is.close();
        return new JSONObject(new String(bos.toByteArray(), "UTF-8"))
                .getJSONArray("entries");
    }

    private static String join(JSONArray a, String sep) throws Exception {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < a.length(); i++) {
            String s = a.getString(i);
            if (s == null || s.length() == 0) continue;
            if (sb.length() > 0) sb.append(sep);
            sb.append(s);
        }
        return sb.toString();
    }
}
