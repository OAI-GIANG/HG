package org.hg.cim.broker;

import android.net.LocalSocket;
import android.net.LocalSocketAddress;
import android.os.Process;
import android.system.Os;
import android.system.OsConstants;
import android.system.StructStat;

import java.io.BufferedInputStream;
import java.io.ByteArrayOutputStream;
import java.io.DataOutputStream;
import java.io.EOFException;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.io.File;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;

/**
 * One-request-per-connection Ollama HTTP transport over a filesystem AF_UNIX socket.
 *
 * It validates the server PID/UID using kernel SO_PEERCRED through LocalSocket.getPeerCredentials(),
 * pins the socket inode across the exchange, and releases no response before nonce/request-digest
 * and post-call checks pass. Streaming is intentionally disabled for protocol version 1.
 */
final class BrokerUnixSocketClient {
    private static final int MAX_HEADER_BYTES = 64 * 1024;
    private static final int MAX_BODY_BYTES = 16 * 1024 * 1024;

    static final class Result {
        final byte[] body;
        final String responseSha256;
        final int peerUid;
        final int peerPid;
        final long socketInode;

        Result(byte[] body, String responseSha256, int peerUid, int peerPid, long socketInode) {
            this.body = body;
            this.responseSha256 = responseSha256;
            this.peerUid = peerUid;
            this.peerPid = peerPid;
            this.socketInode = socketInode;
        }
    }

    Result post(File privateRoot, File socketFile, java.lang.Process backendProcess,
                int expectedUid, int expectedPid, BrokerRequestEnvelope envelope,
                int timeoutMillis) throws Exception {
        SocketIdentity before = inspectSocket(privateRoot, socketFile, expectedUid);
        LocalSocket socket = new LocalSocket(LocalSocket.SOCKET_STREAM);
        try {
            socket.connect(new LocalSocketAddress(socketFile.getAbsolutePath(),
                    LocalSocketAddress.Namespace.FILESYSTEM), timeoutMillis);
            socket.setSoTimeout(timeoutMillis);

            android.net.Credentials prePeer = socket.getPeerCredentials();
            requirePeer(expectedUid, expectedPid, prePeer.getUid(), prePeer.getPid(), prePeer.getGid());

            writeHttpRequest(socket, envelope);
            HttpResponse response = readHttpResponse(socket.getInputStream());

            if (response.status != 200) {
                throw new IOException("backend HTTP status " + response.status);
            }
            requireHeader(response.headers, "x-hg-request-id", envelope.requestId);
            requireHeader(response.headers, "x-hg-request-nonce", envelope.nonce);
            requireHeader(response.headers, "x-hg-request-sha256", envelope.requestSha256);

            android.net.Credentials postPeer = socket.getPeerCredentials();
            requirePeer(expectedUid, expectedPid, postPeer.getUid(), postPeer.getPid(), postPeer.getGid());
            if (!BrokerOllamaProcessLiveness.isSameProcess(backendProcess, expectedPid, expectedUid)) {
                throw new SecurityException("backend process handle, PID or UID changed after response");
            }
            SocketIdentity after = inspectSocket(privateRoot, socketFile, expectedUid);
            if (before.device != after.device || before.inode != after.inode) {
                throw new SecurityException("AF_UNIX socket path was replaced during inference");
            }
            return new Result(response.body, BrokerRequestEnvelope.sha256(response.body),
                    postPeer.getUid(), postPeer.getPid(), after.inode);
        } finally {
            socket.close();
        }
    }

    static void requirePeer(int expectedUid, int expectedPid, int peerUid, int peerPid, int peerGid) {
        if (!BrokerPeerCredentialPolicy.PASS.equals(
                BrokerPeerCredentialPolicy.evaluatePeer(expectedUid, expectedPid, peerUid, peerPid, peerGid))) {
            throw new SecurityException("SO_PEERCRED identity mismatch");
        }
    }

    private static void writeHttpRequest(LocalSocket socket, BrokerRequestEnvelope e) throws IOException {
        DataOutputStream out = new DataOutputStream(socket.getOutputStream());
        String headers = "POST /api/chat HTTP/1.1\r\n"
                + "Host: localhost\r\n"
                + "Connection: close\r\n"
                + "Content-Type: application/json\r\n"
                + "Accept: application/json\r\n"
                + "X-HG-Request-ID: " + e.requestId + "\r\n"
                + "X-HG-Request-Nonce: " + e.nonce + "\r\n"
                + "X-HG-Request-SHA256: " + e.requestSha256 + "\r\n"
                + "Content-Length: " + e.body.length + "\r\n\r\n";
        out.write(headers.getBytes(StandardCharsets.US_ASCII));
        out.write(e.body);
        out.flush();
    }

    private static final class HttpResponse {
        int status;
        Map<String, String> headers = new HashMap<>();
        byte[] body;
    }

    private static HttpResponse readHttpResponse(java.io.InputStream input) throws IOException {
        BufferedInputStream in = new BufferedInputStream(input);
        int budget = MAX_HEADER_BYTES;
        String statusLine = readLine(in, budget);
        budget -= statusLine.length() + 2;
        if (budget < 0 || !statusLine.startsWith("HTTP/1.")) throw new IOException("invalid HTTP status line");
        String[] parts = statusLine.split(" ", 3);
        if (parts.length < 2) throw new IOException("malformed HTTP status line");
        HttpResponse response = new HttpResponse();
        response.status = Integer.parseInt(parts[1]);
        boolean chunked = false;
        long contentLength = -1;
        while (true) {
            String line = readLine(in, budget);
            budget -= line.length() + 2;
            if (budget < 0) throw new IOException("HTTP response headers exceed limit");
            if (line.isEmpty()) break;
            int colon = line.indexOf(':');
            if (colon <= 0) throw new IOException("malformed HTTP header");
            String key = line.substring(0, colon).trim().toLowerCase(Locale.ROOT);
            String value = line.substring(colon + 1).trim();
            if (response.headers.put(key, value) != null) throw new IOException("duplicate HTTP response header");
            if ("transfer-encoding".equals(key) && value.toLowerCase(Locale.ROOT).contains("chunked")) chunked = true;
            if ("content-length".equals(key)) contentLength = Long.parseLong(value);
        }
        if (chunked) response.body = readChunked(in);
        else if (contentLength >= 0) response.body = readExact(in, checkedLength(contentLength));
        else response.body = readUntilEof(in);
        return response;
    }

    private static byte[] readChunked(BufferedInputStream in) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        while (true) {
            String line = readLine(in, 128);
            String sizeToken = line.split(";", 2)[0].trim();
            long length;
            try { length = Long.parseLong(sizeToken, 16); }
            catch (NumberFormatException e) { throw new IOException("invalid HTTP chunk size", e); }
            if (length == 0) {
                while (!readLine(in, MAX_HEADER_BYTES).isEmpty()) { /* consume trailers */ }
                return out.toByteArray();
            }
            if (length > MAX_BODY_BYTES - out.size()) throw new IOException("HTTP body exceeds limit");
            out.write(readExact(in, (int) length));
            expectCrlf(in);
        }
    }

    private static byte[] readUntilEof(BufferedInputStream in) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int count;
        while ((count = in.read(buf)) != -1) {
            if (count > MAX_BODY_BYTES - out.size()) throw new IOException("HTTP body exceeds limit");
            out.write(buf, 0, count);
        }
        return out.toByteArray();
    }

    private static int checkedLength(long length) throws IOException {
        if (length < 0 || length > MAX_BODY_BYTES) throw new IOException("HTTP body exceeds limit");
        return (int) length;
    }

    private static byte[] readExact(BufferedInputStream in, int length) throws IOException {
        byte[] data = new byte[length];
        int offset = 0;
        while (offset < length) {
            int count = in.read(data, offset, length - offset);
            if (count < 0) throw new EOFException("truncated HTTP body");
            offset += count;
        }
        return data;
    }

    private static String readLine(BufferedInputStream in, int maxBytes) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        while (out.size() <= maxBytes) {
            int b = in.read();
            if (b < 0) throw new EOFException("truncated HTTP line");
            if (b == '\r') {
                int lf = in.read();
                if (lf != '\n') throw new IOException("HTTP line is not CRLF terminated");
                return out.toString(StandardCharsets.US_ASCII.name());
            }
            out.write(b);
        }
        throw new IOException("HTTP line exceeds limit");
    }

    private static void expectCrlf(BufferedInputStream in) throws IOException {
        if (in.read() != '\r' || in.read() != '\n') throw new IOException("invalid HTTP chunk terminator");
    }

    private static void requireHeader(Map<String, String> headers, String key, String expected) {
        String actual = headers.get(key);
        if (!expected.equals(actual)) throw new SecurityException("backend response correlation header mismatch");
    }

    private static final class SocketIdentity {
        final long device;
        final long inode;
        SocketIdentity(long device, long inode) { this.device = device; this.inode = inode; }
    }

    private static SocketIdentity inspectSocket(File privateRoot, File socket, int uid) throws Exception {
        File root = privateRoot.getCanonicalFile();
        File target = new File(root, socket.getName());
        if (!target.getParentFile().getCanonicalFile().equals(root)) {
            throw new SecurityException("socket path escapes broker-private root");
        }
        StructStat dir = Os.lstat(root.getAbsolutePath());
        StructStat st = Os.lstat(target.getAbsolutePath());
        if ((dir.st_mode & OsConstants.S_IFMT) != OsConstants.S_IFDIR
                || dir.st_uid != uid || (dir.st_mode & 0077) != 0) {
            throw new SecurityException("private socket directory owner/mode mismatch");
        }
        if ((st.st_mode & OsConstants.S_IFMT) != OsConstants.S_IFSOCK
                || st.st_uid != uid || (st.st_mode & 0077) != 0) {
            throw new SecurityException("socket file owner/type/mode mismatch");
        }
        return new SocketIdentity(st.st_dev, st.st_ino);
    }
}
