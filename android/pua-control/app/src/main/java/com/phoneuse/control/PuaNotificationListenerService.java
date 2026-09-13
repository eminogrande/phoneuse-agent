package com.phoneuse.control;

import android.app.Notification;
import android.app.PendingIntent;
import android.service.notification.NotificationListenerService;
import android.service.notification.StatusBarNotification;

public class PuaNotificationListenerService extends NotificationListenerService {
    static volatile PuaNotificationListenerService instance;

    @Override
    public void onListenerConnected() {
        instance = this;
    }

    @Override
    public void onListenerDisconnected() {
        instance = null;
    }

    @Override
    public void onNotificationPosted(StatusBarNotification sbn) {
        if (sbn == null) return;
        Notification notification = sbn.getNotification();
        CharSequence title = "";
        CharSequence text = "";
        if (notification != null && notification.extras != null) {
            title = firstNonEmpty(
                    notification.extras.getCharSequence(Notification.EXTRA_TITLE),
                    notification.extras.getCharSequence(Notification.EXTRA_CONVERSATION_TITLE),
                    notification.extras.getCharSequence(Notification.EXTRA_SUB_TEXT)
            );
            text = firstNonEmpty(
                    notification.extras.getCharSequence(Notification.EXTRA_TEXT),
                    notification.extras.getCharSequence(Notification.EXTRA_BIG_TEXT),
                    notification.extras.getCharSequence(Notification.EXTRA_SUMMARY_TEXT)
            );
        }
        EventStore.add("notification", sbn.getPostTime(), "posted", sbn.getPackageName(), title, text);
    }

    @Override
    public void onNotificationRemoved(StatusBarNotification sbn) {
        if (sbn == null) return;
        EventStore.add("notification", System.currentTimeMillis(), "removed", sbn.getPackageName(), "", "");
    }

    String activeNotifications(String packageFilter) {
        StatusBarNotification[] notifications = getActiveNotifications();
        StringBuilder out = new StringBuilder();
        if (notifications == null) return "";
        for (StatusBarNotification sbn : notifications) {
            if (sbn == null || !matchesPackage(sbn, packageFilter)) continue;
            Notification notification = sbn.getNotification();
            CharSequence title = "";
            CharSequence text = "";
            if (notification != null && notification.extras != null) {
                title = firstNonEmpty(
                        notification.extras.getCharSequence(Notification.EXTRA_TITLE),
                        notification.extras.getCharSequence(Notification.EXTRA_CONVERSATION_TITLE),
                        notification.extras.getCharSequence(Notification.EXTRA_SUB_TEXT)
                );
                text = firstNonEmpty(
                        notification.extras.getCharSequence(Notification.EXTRA_TEXT),
                        notification.extras.getCharSequence(Notification.EXTRA_BIG_TEXT),
                        notification.extras.getCharSequence(Notification.EXTRA_SUMMARY_TEXT)
                );
            }
            out.append(sbn.getPostTime())
                    .append('\t')
                    .append(sbn.getPackageName())
                    .append('\t')
                    .append(EventStore.safe(title))
                    .append('\t')
                    .append(EventStore.safe(text))
                    .append('\t')
                    .append(EventStore.safe(sbn.getKey()))
                    .append('\n');
        }
        return out.toString();
    }

    boolean openLatestNotification(String packageFilter) {
        StatusBarNotification[] notifications = getActiveNotifications();
        if (notifications == null) return false;
        StatusBarNotification best = null;
        for (StatusBarNotification sbn : notifications) {
            if (sbn == null || !matchesPackage(sbn, packageFilter)) continue;
            Notification notification = sbn.getNotification();
            if (notification == null || notification.contentIntent == null) continue;
            if (best == null || sbn.getPostTime() > best.getPostTime()) {
                best = sbn;
            }
        }
        if (best == null) return false;
        try {
            best.getNotification().contentIntent.send();
            EventStore.add("notification", System.currentTimeMillis(), "opened", best.getPackageName(), "", "");
            return true;
        } catch (PendingIntent.CanceledException ex) {
            EventStore.add("notification", System.currentTimeMillis(), "open_failed", best.getPackageName(), "", ex.getMessage());
            return false;
        }
    }

    private boolean matchesPackage(StatusBarNotification sbn, String packageFilter) {
        if (packageFilter == null || packageFilter.length() == 0 || "all".equals(packageFilter)) return true;
        return packageFilter.equals(sbn.getPackageName());
    }

    private CharSequence firstNonEmpty(CharSequence... values) {
        for (CharSequence value : values) {
            if (value != null && value.length() > 0) {
                return value;
            }
        }
        return "";
    }
}
