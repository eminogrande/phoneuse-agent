package com.phoneuse.control;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.graphics.Path;
import android.graphics.Rect;
import android.net.Uri;
import android.os.Bundle;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;

import java.util.List;

public class PuaAccessibilityService extends AccessibilityService {
    static volatile PuaAccessibilityService instance;

    @Override
    protected void onServiceConnected() {
        instance = this;
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        recordEvent(event);
    }

    @Override
    public void onInterrupt() {
    }

    @Override
    public boolean onUnbind(android.content.Intent intent) {
        instance = null;
        return super.onUnbind(intent);
    }

    boolean click(int x, int y) {
        Path path = new Path();
        path.moveTo(x, y);
        GestureDescription gesture = new GestureDescription.Builder()
                .addStroke(new GestureDescription.StrokeDescription(path, 0, 100))
                .build();
        return dispatchGesture(gesture, null, null);
    }

    boolean swipe(int x1, int y1, int x2, int y2, int durationMs) {
        Path path = new Path();
        path.moveTo(x1, y1);
        path.lineTo(x2, y2);
        GestureDescription gesture = new GestureDescription.Builder()
                .addStroke(new GestureDescription.StrokeDescription(path, 0, Math.max(50, durationMs)))
                .build();
        return dispatchGesture(gesture, null, null);
    }

    boolean longPress(int x, int y, int durationMs) {
        Path path = new Path();
        path.moveTo(x, y);
        GestureDescription gesture = new GestureDescription.Builder()
                .addStroke(new GestureDescription.StrokeDescription(path, 0, Math.max(600, durationMs)))
                .build();
        return dispatchGesture(gesture, null, null);
    }

    boolean globalAction(String name) {
        if (name == null) return false;
        if ("home".equals(name)) {
            return performGlobalAction(GLOBAL_ACTION_HOME);
        }
        if ("back".equals(name)) {
            return performGlobalAction(GLOBAL_ACTION_BACK);
        }
        if ("recents".equals(name)) {
            return performGlobalAction(GLOBAL_ACTION_RECENTS);
        }
        if ("notifications".equals(name)) {
            return performGlobalAction(GLOBAL_ACTION_NOTIFICATIONS);
        }
        if ("quick-settings".equals(name)) {
            return performGlobalAction(GLOBAL_ACTION_QUICK_SETTINGS);
        }
        return false;
    }

    boolean openUrl(String url) {
        if (url == null || url.length() == 0) return false;
        Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        intent.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP);
        try {
            startActivity(intent);
            return true;
        } catch (RuntimeException ex) {
            return false;
        }
    }

    boolean launchPackage(String packageName) {
        if (packageName == null || packageName.length() == 0) return false;
        PackageManager packageManager = getPackageManager();
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
        launchIntent.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP);
        launchIntent.addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP);
        try {
            startActivity(launchIntent);
            return true;
        } catch (RuntimeException ex) {
            // Background Activity Launch blocked (e.g. right after boot):
            // fall back to the human path — go home and tap the app icon.
            return launchViaLauncher(packageManager, packageName);
        }
    }

    private boolean launchViaLauncher(PackageManager pm, String packageName) {
        try {
            String label = String.valueOf(pm.getApplicationLabel(pm.getApplicationInfo(packageName, 0)));
            performGlobalAction(GLOBAL_ACTION_HOME);
            for (int attempt = 0; attempt < 8; attempt++) {
                Thread.sleep(600);
                AccessibilityNodeInfo root = getRootInActiveWindow();
                if (root == null) continue;
                List<AccessibilityNodeInfo> byText = root.findAccessibilityNodeInfosByText(label);
                if (byText != null) {
                    for (AccessibilityNodeInfo node : byText) {
                        AccessibilityNodeInfo n = node;
                        while (n != null) {
                            if (n.isClickable() && n.isEnabled()) {
                                return n.performAction(AccessibilityNodeInfo.ACTION_CLICK);
                            }
                            n = n.getParent();
                        }
                    }
                }
            }
        } catch (Exception ignored) {
        }
        return false;
    }

    boolean clickByViewId(String viewId) {
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) return false;
        List<AccessibilityNodeInfo> nodes = root.findAccessibilityNodeInfosByViewId(viewId);
        if (nodes == null || nodes.isEmpty()) return false;
        AccessibilityNodeInfo node = nodes.get(0);
        while (node != null) {
            if (node.isClickable() && node.isEnabled()) {
                return node.performAction(AccessibilityNodeInfo.ACTION_CLICK);
            }
            node = node.getParent();
        }
        return false;
    }

    boolean setTextByViewId(String viewId, String text) {
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) return false;
        List<AccessibilityNodeInfo> nodes = root.findAccessibilityNodeInfosByViewId(viewId);
        if (nodes == null || nodes.isEmpty()) return false;
        AccessibilityNodeInfo node = nodes.get(0);
        node.performAction(AccessibilityNodeInfo.ACTION_FOCUS);
        Bundle args = new Bundle();
        args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text);
        return node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args);
    }

    boolean setFocusedText(String text) {
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) return false;
        AccessibilityNodeInfo focused = root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT);
        if (focused == null) return false;
        Bundle args = new Bundle();
        args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text);
        return focused.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args);
    }

    String dump() {
        AccessibilityNodeInfo root = getRootInActiveWindow();
        StringBuilder out = new StringBuilder();
        append(root, out, 0);
        return out.toString();
    }

    String events() {
        return EventStore.dump();
    }

    void clearEvents() {
        EventStore.clear();
    }

    private void recordEvent(AccessibilityEvent event) {
        if (event == null) return;
        CharSequence packageName = event.getPackageName();
        CharSequence className = event.getClassName();
        EventStore.add("accessibility", event.getEventTime(), eventTypeName(event.getEventType()),
                packageName, className, safeText(event.getText()) + " " + safeText(event.getContentDescription()));
    }

    private String eventTypeName(int type) {
        try {
            return AccessibilityEvent.eventTypeToString(type);
        } catch (RuntimeException ex) {
            return String.valueOf(type);
        }
    }

    private String safeText(List<CharSequence> values) {
        if (values == null || values.isEmpty()) return "";
        StringBuilder out = new StringBuilder();
        for (CharSequence value : values) {
            if (value == null) continue;
            if (out.length() > 0) out.append(" | ");
            out.append(value);
        }
        return safeText(out);
    }

    private String safeText(CharSequence value) {
        return EventStore.safe(value);
    }

    private void append(AccessibilityNodeInfo node, StringBuilder out, int depth) {
        if (node == null || depth > 8) return;
        Rect bounds = new Rect();
        node.getBoundsInScreen(bounds);
        for (int i = 0; i < depth; i++) out.append("  ");
        out.append(node.getClassName())
                .append(" id=").append(node.getViewIdResourceName())
                .append(" text=").append(node.getText())
                .append(" desc=").append(node.getContentDescription())
                .append(" bounds=").append(bounds.toShortString())
                .append(" focusable=").append(node.isFocusable())
                .append(" focused=").append(node.isFocused())
                .append('\n');
        for (int i = 0; i < node.getChildCount(); i++) {
            append(node.getChild(i), out, depth + 1);
        }
    }
}
