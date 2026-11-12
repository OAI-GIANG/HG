package org.hg.cim.broker;

import org.junit.Test;

import static org.junit.Assert.assertEquals;

/** Negative controls for the kernel-authenticated peer and request/response binding policy. */
public final class BrokerPeerCredentialPolicyTest {
    private static final String PASS = BrokerPeerCredentialPolicy.PASS;
    private static final String REFUSED = BrokerPeerCredentialPolicy.REFUSED;

    private static String hex(char c) {
        return new String(new char[64]).replace('\0', c);
    }

    @Test
    public void acceptsExactPeerUidAndPid() {
        assertEquals(PASS, BrokerPeerCredentialPolicy.evaluatePeer(10460, 12001, 10460, 12001, 10460));
    }

    @Test
    public void rejectsDifferentPeerUid() {
        assertEquals(REFUSED, BrokerPeerCredentialPolicy.evaluatePeer(10460, 12001, 10461, 12001, 10460));
    }

    @Test
    public void rejectsDifferentPeerPid() {
        assertEquals(REFUSED, BrokerPeerCredentialPolicy.evaluatePeer(10460, 12001, 10460, 12002, 10460));
    }

    @Test
    public void rejectsInvalidPeerIdentity() {
        assertEquals(REFUSED, BrokerPeerCredentialPolicy.evaluatePeer(10460, 12001, 10460, 0, 10460));
    }

    @Test
    public void acceptsExactRequestResponseCorrelation() {
        assertEquals(PASS, BrokerPeerCredentialPolicy.evaluateEnvelope(
                "request-1", hex('a'), hex('b'),
                "request-1", hex('a'), hex('b'), hex('c')));
    }

    @Test
    public void rejectsChangedRequestId() {
        assertEquals(REFUSED, BrokerPeerCredentialPolicy.evaluateEnvelope(
                "request-1", hex('a'), hex('b'),
                "request-2", hex('a'), hex('b'), hex('c')));
    }

    @Test
    public void rejectsChangedNonce() {
        assertEquals(REFUSED, BrokerPeerCredentialPolicy.evaluateEnvelope(
                "request-1", hex('a'), hex('b'),
                "request-1", hex('d'), hex('b'), hex('c')));
    }

    @Test
    public void rejectsChangedRequestDigest() {
        assertEquals(REFUSED, BrokerPeerCredentialPolicy.evaluateEnvelope(
                "request-1", hex('a'), hex('b'),
                "request-1", hex('a'), hex('e'), hex('c')));
    }

    @Test
    public void rejectsMalformedResponseDigest() {
        assertEquals(REFUSED, BrokerPeerCredentialPolicy.evaluateEnvelope(
                "request-1", hex('a'), hex('b'),
                "request-1", hex('a'), hex('b'), "not-a-digest"));
    }
}
