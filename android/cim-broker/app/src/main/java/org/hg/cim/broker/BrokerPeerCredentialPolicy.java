package org.hg.cim.broker;

/**
 * Fail-closed policy for the kernel-authenticated AF_UNIX peer and the request/response envelope.
 * Caller-supplied PID/UID fields are never accepted as identity evidence.
 */
public final class BrokerPeerCredentialPolicy {
    public static final String PASS = "PASS";
    public static final String REFUSED = "REFUSED";

    private BrokerPeerCredentialPolicy() {}

    public static String evaluatePeer(
            int expectedUid, int expectedPid, int peerUid, int peerPid, int peerGid) {
        if (expectedUid < 0 || expectedPid <= 0 || peerUid < 0 || peerPid <= 0 || peerGid < 0) {
            return REFUSED;
        }
        return expectedUid == peerUid && expectedPid == peerPid ? PASS : REFUSED;
    }

    public static String evaluateEnvelope(
            String expectedRequestId,
            String expectedNonce,
            String expectedRequestSha256,
            String responseRequestId,
            String responseNonce,
            String responseRequestSha256,
            String responseSha256) {
        if (!hex64(expectedRequestSha256) || !hex64(responseRequestSha256)
                || !hex64(expectedNonce) || responseNonce == null || responseNonce.isEmpty()
                || expectedRequestId == null || expectedRequestId.isEmpty()
                || responseRequestId == null || responseRequestId.isEmpty()
                || !hex64(responseSha256)) {
            return REFUSED;
        }
        return expectedRequestId.equals(responseRequestId)
                && constantTimeEquals(expectedNonce, responseNonce)
                && constantTimeEquals(expectedRequestSha256, responseRequestSha256)
                ? PASS : REFUSED;
    }

    public static boolean hex64(String value) {
        if (value == null || value.length() != 64) return false;
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return false;
        }
        return true;
    }

    private static boolean constantTimeEquals(String left, String right) {
        if (left == null || right == null) return false;
        int diff = left.length() ^ right.length();
        int n = Math.max(left.length(), right.length());
        for (int i = 0; i < n; i++) {
            char a = i < left.length() ? left.charAt(i) : 0;
            char b = i < right.length() ? right.charAt(i) : 0;
            diff |= a ^ b;
        }
        return diff == 0;
    }
}
