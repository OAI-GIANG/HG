package org.hg.cim.broker;

import android.os.Process;

/**
 * Binds process identity to the Java Process handle returned by ProcessBuilder.
 * PID equality alone is insufficient because the kernel may reuse a PID after exit.
 */
final class BrokerOllamaProcessLiveness {
    private BrokerOllamaProcessLiveness() {}

    static boolean isSameProcess(java.lang.Process process, int expectedPid, int expectedUid) {
        if (process == null || expectedPid <= 0 || expectedUid < 0) return false;
        try {
            if (!process.isAlive() || process.pid() != expectedPid) return false;
            int observedUid = Process.getUidForPid(expectedPid);
            if (observedUid != expectedUid) return false;
            return process.isAlive() && process.pid() == expectedPid;
        } catch (RuntimeException error) {
            return false;
        }
    }
}
