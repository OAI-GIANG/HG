package org.hg.cim.broker;

import android.content.Context;
import android.os.Bundle;

import org.json.JSONArray;
import org.json.JSONObject;

import java.nio.charset.StandardCharsets;

/**
 * Version-1 non-streaming inference adapter. It has no TCP fallback.
 * It refuses until the APK contains a reproducibly built, signed runtime anchor and an
 * owner-approved private model manifest. If qualified later, request/response bytes are
 * correlated by request ID + nonce + request digest and wrapped in a post-call PID/UID/socket
 * identity check before response content is released to Binder.
 */
final class BrokerInferenceProvider {
    private final Context context;
    private final BrokerOllamaSupervisor supervisor;
    private final BrokerUnixSocketClient unixClient;

    BrokerInferenceProvider(Context context) {
        this.context = context.getApplicationContext();
        this.supervisor = new BrokerOllamaSupervisor(this.context);
        this.unixClient = new BrokerUnixSocketClient();
    }

    Bundle infer(String model, String prompt) throws Exception {
        if (!BrokerStore.isInferenceEnabled(context)) {
            return blocked("OWNER_INFERENCE_NOT_ENABLED");
        }
        if (!BrokerModelAnchor.isApproved(context, model)) {
            return blocked("MODEL_NOT_APPROVED_OR_NOT_PROVISIONED");
        }

        // This deliberately fails until a reproducible Android ELF and provenance record are
        // embedded in the signed APK. Empty anchor => no child process and no listener.
        final int backendPid;
        try {
            backendPid = supervisor.ensureStarted();
        } catch (SecurityException error) {
            return blocked("BACKEND_NOT_TRUSTED");
        }

        java.lang.Process backend = supervisor.process();
        if (backend == null || backendPid <= 0) return blocked("BACKEND_PROCESS_NOT_BOUND");

        JSONObject message = new JSONObject();
        message.put("role", "user");
        message.put("content", prompt);
        JSONArray messages = new JSONArray().put(message);
        JSONObject request = new JSONObject();
        request.put("model", model);
        request.put("messages", messages);
        request.put("stream", false);
        byte[] body = request.toString().getBytes(StandardCharsets.UTF_8);

        BrokerRequestEnvelope envelope = BrokerRequestEnvelope.create(body);
        java.io.File root = supervisor.rootDirectory();
        java.io.File socketFile = supervisor.socketFile();
        BrokerUnixSocketClient.Result result = unixClient.post(
                root, socketFile, backend, android.os.Process.myUid(), backendPid, envelope, 120_000);

        if (!BrokerOllamaProcessLiveness.isSameProcess(
                supervisor.process(), backendPid, android.os.Process.myUid())) {
            throw new SecurityException("BACKEND_POSTCHECK_FAILED");
        }
        JSONObject response = new JSONObject(new String(result.body, StandardCharsets.UTF_8));
        JSONObject responseMessage = response.optJSONObject("message");
        if (responseMessage == null || !"assistant".equals(responseMessage.optString("role"))) {
            throw new SecurityException("MODEL_RESPONSE_SCHEMA_INVALID");
        }
        String text = responseMessage.optString("content", null);
        if (text == null || text.isEmpty() || text.length() > 2_000_000) {
            throw new SecurityException("MODEL_RESPONSE_EMPTY_OR_TOO_LARGE");
        }

        Bundle out = new Bundle();
        out.putString("status", "PASS");
        out.putString("request_id", envelope.requestId);
        out.putString("response", text);
        out.putString("request_sha256", envelope.requestSha256);
        out.putString("response_sha256", result.responseSha256);
        out.putInt("backend_pid", result.peerPid);
        out.putInt("backend_uid", result.peerUid);
        out.putLong("socket_inode", result.socketInode);
        out.putString("transport", "AF_UNIX");
        out.putString("peer_credential", "SO_PEERCRED");
        out.putBoolean("postcheck", true);
        return out;
    }

    private static Bundle blocked(String code) {
        Bundle out = new Bundle();
        out.putString("status", "BLOCKED");
        out.putString("error_code", code);
        return out;
    }
}
