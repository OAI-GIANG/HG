package org.hg.cim.broker;

import org.junit.Test;

import java.nio.charset.StandardCharsets;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotEquals;
import static org.junit.Assert.assertTrue;

public final class BrokerRequestEnvelopeTest {
    @Test
    public void createsNonceRequestIdAndDigestBoundToExactBytes() throws Exception {
        byte[] body = "{\"model\":\"unit\",\"stream\":false}".getBytes(StandardCharsets.UTF_8);
        BrokerRequestEnvelope envelope = BrokerRequestEnvelope.create(body);
        assertEquals(64, envelope.nonce.length());
        assertEquals(36, envelope.requestId.length());
        assertEquals(BrokerRequestEnvelope.sha256(body), envelope.requestSha256);
        assertArrayEquals(body, envelope.body);
        body[0] = 'X';
        assertNotEquals(body[0], envelope.body[0]);
        assertEquals(BrokerRequestEnvelope.sha256(envelope.body), envelope.requestSha256);
        assertTrue(BrokerPeerCredentialPolicy.hex64(envelope.requestSha256));
    }

    @Test(expected = SecurityException.class)
    public void rejectsEmptyRequestBody() throws Exception {
        BrokerRequestEnvelope.create(new byte[0]);
    }

    @Test(expected = SecurityException.class)
    public void rejectsOversizedRequestBody() throws Exception {
        BrokerRequestEnvelope.create(new byte[1024 * 1024 + 1]);
    }
}
