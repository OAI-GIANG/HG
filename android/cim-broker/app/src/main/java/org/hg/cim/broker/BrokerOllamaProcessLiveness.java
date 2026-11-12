package org.hg.cim.broker;

import android.system.Os;

import java.lang.reflect.Method;

/**
 * Binds a ProcessBuilder process handle to a kernel procfs PID/UID observation.
 *
 * Android's hidden Process.getUidForPid() is deliberately not called. The public
 * java.lang.Process.pid() method is obtained reflectively so older Android releases
 * fail closed when that API is absent. PID and UID are sampled while the same
 * Process handle is alive before and after the procfs observation.
 */
final class BrokerOllamaProcessLiveness {
    private BrokerOllamaProcessLiveness() {}

    static int pidOf(java.lang.Process process) {
        if (process == null) return -1;
        try {
            Method pidMethod = java.lang.Process.class.getMethod("pid");
            Object value = pidMethod.invoke(process);
            if (!(value instanceof Long)) return -1;
            long pid = (Long) value;
            return pid > 0 && pid <= Integer.MAX_VALUE ? (int) pid : -1;
        } catch (ReflectiveOperationException | RuntimeException error) {
            return -1;
        }
    }

    static boolean isSameProcess(java.lang.Process process, int expectedPid, int expectedUid) {
        if (process == null || expectedPid <= 0 || expectedUid < 0) return false;
        try {
            if (!process.isAlive() || pidOf(process) != expectedPid) return false;

            // procfs directory ownership reflects the effective UID of this process.
            // Access denial or an unavailable proc entry is an explicit refusal.
            int observedUid = Os.stat("/proc/" + expectedPid).st_uid;
            if (observedUid != expectedUid) return false;

            // Recheck the same ProcessBuilder handle after the kernel observation.
            return process.isAlive()
                    && pidOf(process) == expectedPid
                    && Os.stat("/proc/" + expectedPid).st_uid == expectedUid;
        } catch (Exception error) {
            return false;
        }
    }
}
