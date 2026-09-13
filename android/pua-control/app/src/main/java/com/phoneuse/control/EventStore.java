package com.phoneuse.control;

import java.util.ArrayDeque;
import java.util.Deque;

final class EventStore {
    private static final int MAX_EVENTS = 500;
    private static final Deque<String> EVENTS = new ArrayDeque<>();

    private EventStore() {
    }

    static void add(String source, long time, String kind, CharSequence packageName, CharSequence title, CharSequence text) {
        String line = safe(source)
                + '\t' + time
                + '\t' + safe(kind)
                + '\t' + safe(packageName)
                + '\t' + safe(title)
                + '\t' + safe(text);
        synchronized (EVENTS) {
            EVENTS.addLast(line);
            while (EVENTS.size() > MAX_EVENTS) {
                EVENTS.removeFirst();
            }
        }
    }

    static String dump() {
        StringBuilder out = new StringBuilder();
        synchronized (EVENTS) {
            for (String event : EVENTS) {
                out.append(event).append('\n');
            }
        }
        return out.toString();
    }

    static void clear() {
        synchronized (EVENTS) {
            EVENTS.clear();
        }
    }

    static String safe(CharSequence value) {
        if (value == null) return "";
        String text = value.toString().replace('\n', ' ').replace('\r', ' ').replace('\t', ' ');
        return text.length() > 700 ? text.substring(0, 700) : text;
    }
}
