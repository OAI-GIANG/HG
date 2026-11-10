package org.hg.cim.broker;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.net.Uri;
import android.os.Binder;
import android.os.Bundle;
import android.os.ParcelFileDescriptor;

public final class CimBrokerProvider extends ContentProvider {
    private static final String METHOD_STATUS = "status";
    private static final String PROTOCOL_VERSION = "1.0.0";

    @Override
    public boolean onCreate() {
        return true;
    }

    @Override
    public Bundle call(String method, String arg, Bundle extras) {
        if (!METHOD_STATUS.equals(method) && !"infer".equals(method)) {
            throw new SecurityException("unsupported broker method");
        }

        Context context = getContext();
        if (context == null) {
            throw new IllegalStateException("broker context unavailable");
        }

        // Read the kernel-provided Binder identity before caller data or identity clearing.
        int callerUid = Binder.getCallingUidOrThrow();
        BrokerStore.TermuxIdentity identity =
                BrokerStore.authenticateBinderCaller(context, callerUid);

        if ("infer".equals(method)) {
            // Request schema is deliberately minimal. No caller-supplied UID, PID, nonce,
            // path, executable or authority is accepted.
            if (extras == null) throw new SecurityException("inference request missing");
            String model = extras.getString("model", "");
            String prompt = extras.getString("prompt", "");
            if (model.isEmpty() || prompt.isEmpty() || prompt.length() > 64 * 1024
                    || extras.getBoolean("stream", false)) {
                throw new SecurityException("invalid inference request schema");
            }
            try {
                return new BrokerInferenceProvider(context).infer(model, prompt);
            } catch (SecurityException error) {
                throw error;
            } catch (Exception error) {
                Bundle blocked = new Bundle();
                blocked.putString("status", "BLOCKED");
                blocked.putString("error_code", "INFERENCE_TRANSPORT_OR_POSTCHECK_FAILED");
                return blocked;
            }
        }

        Bundle response = new Bundle();
        response.putString("protocol_version", PROTOCOL_VERSION);
        response.putBoolean("authenticated", true);
        response.putInt("broker_uid", android.os.Process.myUid());
        response.putInt("caller_uid", callerUid);
        response.putString("caller_package", BrokerStore.TERMUX_PACKAGE);
        response.putString("caller_signer_sha256", identity.signerDisplay());
        response.putString("broker", "HG-CIM-ANDROID-BROKER");
        response.putString("security_boundary", "ANDROID_APP_UID_PLUS_BINDER_CALLER_CHECK");
        response.putBoolean("mutating_capabilities_enabled", false);
        response.putBoolean("inference_enabled", BrokerStore.isInferenceEnabled(context));
        response.putBoolean("runtime_anchor_qualified", false);
        response.putBoolean("model_anchor_qualified", false);
        return response;
    }

    @Override public Cursor query(Uri uri, String[] projection, String selection,
                                  String[] selectionArgs, String sortOrder) {
        throw new SecurityException("query API is disabled");
    }

    @Override public String getType(Uri uri) {
        throw new SecurityException("MIME lookup API is disabled");
    }

    @Override public Uri insert(Uri uri, ContentValues values) {
        throw new SecurityException("insert API is disabled");
    }

    @Override public int delete(Uri uri, String selection, String[] selectionArgs) {
        throw new SecurityException("delete API is disabled");
    }

    @Override public int update(Uri uri, ContentValues values, String selection,
                                String[] selectionArgs) {
        throw new SecurityException("update API is disabled");
    }

    @Override
    public ParcelFileDescriptor openFile(Uri uri, String mode) {
        throw new SecurityException("file API is disabled");
    }
}
