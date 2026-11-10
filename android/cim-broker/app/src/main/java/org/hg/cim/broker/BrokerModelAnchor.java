package org.hg.cim.broker;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;

/**
 * An empty model list is a valid fail-closed state. Model names supplied by callers are
 * accepted only when an APK-signed manifest entry pins the exact private blob digest.
 */
final class BrokerModelAnchor {
    private BrokerModelAnchor() {}

    static boolean isApproved(Context context, String requestedModel) {
        if (requestedModel == null || requestedModel.isEmpty() || requestedModel.length() > 128) return false;
        try (InputStream in = context.getAssets().open("trusted-models.json")) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] bytes = new byte[4096];
            int n;
            while ((n = in.read(bytes)) != -1) {
                if (out.size() + n > 64 * 1024) return false;
                out.write(bytes, 0, n);
            }
            JSONObject root = new JSONObject(out.toString("UTF-8"));
            if (!"hg-android-broker-model-anchor-v1".equals(root.optString("schema"))) return false;
            JSONArray entries = root.optJSONArray("models");
            if (entries == null) return false;
            // Broker model import is not qualified yet; no caller can add entries.
            for (int i = 0; i < entries.length(); i++) {
                JSONObject entry = entries.getJSONObject(i);
                if (requestedModel.equals(entry.optString("name"))
                        && BrokerRuntimeAnchor.hex64(entry.optString("manifest_sha256"))
                        && BrokerRuntimeAnchor.hex64(entry.optString("model_blob_sha256"))
                        && "VERIFIED".equals(entry.optString("provenance_status"))) {
                    return false; // Requires verified local blob import + manifest digest implementation.
                }
            }
        } catch (Exception ignored) {
            return false;
        }
        return false;
    }
}
