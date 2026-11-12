package org.hg.cim.broker;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Locale;
import java.util.UUID;

final class BrokerRequestEnvelope {
    final String requestId;
    final String nonce;
    final String requestSha256;
    final byte[] body;

    private BrokerRequestEnvelope(String requestId, String nonce, String requestSha256, byte[] body) {
        this.requestId = requestId;
        this.nonce = nonce;
        this.requestSha256 = requestSha256;
        this.body = body;
    }

    static BrokerRequestEnvelope create(byte[] body) throws Exception {
        if (body == null || body.length == 0 || body.length > 1024 * 1024) {
            throw new SecurityException("inference request size is outside 1..1048576 bytes");
        }
        byte[] random = new byte[32];
        new SecureRandom().nextBytes(random);
        StringBuilder nonce = new StringBuilder(64);
        for (byte b : random) nonce.append(String.format(Locale.ROOT, "%02x", b & 0xff));
        return new BrokerRequestEnvelope(UUID.randomUUID().toString(), nonce.toString(),
                sha256(body), body.clone());
    }

    static String sha256(byte[] value) throws Exception {
        byte[] digest = MessageDigest.getInstance("SHA-256").digest(value);
        StringBuilder result = new StringBuilder(64);
        for (byte b : digest) result.append(String.format(Locale.ROOT, "%02x", b & 0xff));
        return result.toString();
    }
}
