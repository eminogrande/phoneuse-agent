package com.phoneuse.control;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.util.Log;

import java.util.List;

public class CommandReceiver extends BroadcastReceiver {
    private static final String TAG = "PuaControl";

    @Override
    public void onReceive(Context context, Intent intent) {
        String action = intent.getAction();
        if ("com.phoneuse.control.EVENTS".equals(action)) {
            String events = EventStore.dump();
            Log.i(TAG, events);
            setResultData(events);
            return;
        } else if ("com.phoneuse.control.CLEAR_EVENTS".equals(action)) {
            EventStore.clear();
            setResultData("clearEvents=true");
            return;
        } else if ("com.phoneuse.control.NOTIFICATIONS".equals(action)) {
            PuaNotificationListenerService listener = PuaNotificationListenerService.instance;
            if (listener == null) {
                setResultData("notification listener not connected");
                return;
            }
            setResultData(listener.activeNotifications(intent.getStringExtra("package")));
            return;
        } else if ("com.phoneuse.control.OPEN_NOTIFICATION".equals(action)) {
            PuaNotificationListenerService listener = PuaNotificationListenerService.instance;
            if (listener == null) {
                setResultData("notification listener not connected");
                return;
            }
            boolean ok = listener.openLatestNotification(intent.getStringExtra("package"));
            setResultData("openNotification=" + ok);
            return;
        } else if ("com.phoneuse.control.LAUNCH".equals(action)) {
            PuaAccessibilityService service = PuaAccessibilityService.instance;
            if (service != null && service.launchPackage(intent.getStringExtra("package"))) {
                setResultData("launch=true via=accessibility");
                return;
            }
            boolean ok = launchPackage(context, intent.getStringExtra("package"));
            setResultData("launch=" + ok + " via=receiver");
            return;
        }

        PuaAccessibilityService service = PuaAccessibilityService.instance;
        if (service == null) {
            Log.e(TAG, "service not connected");
            setResultData("service not connected");
            return;
        }

        if ("com.phoneuse.control.CLICK".equals(action)) {
            boolean ok = service.click(intent.getIntExtra("x", 0), intent.getIntExtra("y", 0));
            setResultData("click=" + ok);
        } else if ("com.phoneuse.control.CLICK_ID".equals(action)) {
            String viewId = intent.getStringExtra("viewId");
            boolean ok = service.clickByViewId(viewId);
            setResultData("clickId=" + ok);
        } else if ("com.phoneuse.control.SET_TEXT".equals(action)) {
            String viewId = intent.getStringExtra("viewId");
            String text = intent.getStringExtra("text");
            boolean ok = service.setTextByViewId(viewId, text == null ? "" : text);
            setResultData("setText=" + ok);
        } else if ("com.phoneuse.control.SET_FOCUSED_TEXT".equals(action)) {
            String text = intent.getStringExtra("text");
            boolean ok = service.setFocusedText(text == null ? "" : text);
            setResultData("setFocusedText=" + ok);
        } else if ("com.phoneuse.control.OPEN_URL".equals(action)) {
            String url = intent.getStringExtra("url");
            boolean ok = service.openUrl(url);
            setResultData("openUrl=" + ok);
        } else if ("com.phoneuse.control.GLOBAL_ACTION".equals(action)) {
            String name = intent.getStringExtra("name");
            boolean ok = service.globalAction(name);
            setResultData("globalAction=" + ok);
        } else if ("com.phoneuse.control.DUMP".equals(action)) {
            String dump = service.dump();
            Log.i(TAG, dump);
            setResultData(dump);
        }
    }

    private boolean launchPackage(Context context, String packageName) {
        if (packageName == null || packageName.length() == 0) return false;
        PackageManager packageManager = context.getPackageManager();
        Intent launchIntent = packageManager.getLaunchIntentForPackage(packageName);
        if (launchIntent == null) {
            Intent queryIntent = new Intent(Intent.ACTION_MAIN);
            queryIntent.addCategory(Intent.CATEGORY_LAUNCHER);
            queryIntent.setPackage(packageName);
            List<ResolveInfo> activities = packageManager.queryIntentActivities(queryIntent, 0);
            if (activities != null && !activities.isEmpty()) {
                ResolveInfo activity = activities.get(0);
                launchIntent = new Intent(Intent.ACTION_MAIN);
                launchIntent.addCategory(Intent.CATEGORY_LAUNCHER);
                launchIntent.setClassName(activity.activityInfo.packageName, activity.activityInfo.name);
            }
        }
        if (launchIntent == null) return false;
        launchIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        context.startActivity(launchIntent);
        return true;
    }
}
