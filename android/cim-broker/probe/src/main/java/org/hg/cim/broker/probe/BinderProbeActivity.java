package org.hg.cim.broker.probe;

import android.app.Activity;
import android.net.Uri;
import android.os.Bundle;
import android.os.Process;
import android.util.Log;
import android.widget.TextView;

/**
 * Runs from a separately installed package/UID and attempts an exported Binder call.
 * Qualification requires an installed Termux identity paired in the Broker UI first,
 * then this different caller must be rejected specifically as DENY_UID.
 */
public final class BinderProbeActivity extends Activity {
    private static final String TAG = "HGBinderProbe";
    private static final Uri BROKER_URI = Uri.parse("content://org.hg.cim.broker.ipc");

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        TextView view = new TextView(this);
        view.setTextSize(18);
        view.setPadding(32, 32, 32, 32);
        setContentView(view);

        int callerUid = Process.myUid();
        try {
            Bundle response = getContentResolver().call(BROKER_URI, "status", null, null);
            String detail = response == null ? "null" : response.getString("broker", "unknown");
            view.setText("NEGATIVE_BINDER_FAIL: call unexpectedly returned " + detail);
            Log.e(TAG, "NEGATIVE_BINDER_FAIL caller_uid=" + callerUid + " response=" + detail);
        } catch (SecurityException denied) {
            String reason = denied.getMessage();
            if (reason != null && reason.contains("DENY_UID")) {
                view.setText("NEGATIVE_BINDER_PASS: DENY_UID");
                Log.i(TAG, "NEGATIVE_BINDER_PASS_DENY_UID caller_uid=" + callerUid);
            } else {
                view.setText("NEGATIVE_BINDER_INCONCLUSIVE: " + denied.getClass().getSimpleName());
                Log.e(TAG, "NEGATIVE_BINDER_INCONCLUSIVE caller_uid=" + callerUid
                        + " exception=" + denied.getClass().getSimpleName()
                        + " reason=" + (reason == null ? "none" : reason));
            }
        } catch (RuntimeException failure) {
            view.setText("NEGATIVE_BINDER_FAIL: unexpected runtime error");
            Log.e(TAG, "NEGATIVE_BINDER_FAIL caller_uid=" + callerUid
                    + " exception=" + failure.getClass().getSimpleName(), failure);
        }
    }
}
