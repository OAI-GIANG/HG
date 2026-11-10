package org.hg.cim.broker;

import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

public final class BrokerOllamaProcessLivenessTest {
    @Test
    public void nullProcessHasNoPid() {
        assertEquals(-1, BrokerOllamaProcessLiveness.pidOf(null));
    }

    @Test
    public void pidIsReadFromTheProcessHandleNotCallerInput() throws Exception {
        java.lang.Process child = new ProcessBuilder("sh", "-c", "sleep 5").start();
        try {
            int observed = BrokerOllamaProcessLiveness.pidOf(child);
            assertTrue("a live host Process handle must expose its own PID", observed > 0);
        } finally {
            child.destroyForcibly();
            child.waitFor();
        }
    }

    @Test
    public void rejectsMalformedRuntimeDigest() {
        assertTrue(BrokerRuntimeAnchor.hex64("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"));
        assertTrue(!BrokerRuntimeAnchor.hex64("0123456789ABCDEF0123456789abcdef0123456789abcdef0123456789abcdef"));
        assertTrue(!BrokerRuntimeAnchor.hex64("abcd"));
    }
}
