package org.hg.cim.broker;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

public final class MainActivity extends Activity {
    private TextView status;
    private BrokerStore.TermuxIdentity identity;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        int pad = (int) (20 * getResources().getDisplayMetrics().density);
        content.setPadding(pad, pad, pad, pad);

        TextView title = new TextView(this);
        title.setText("HG CIM Broker — Owner Pairing");
        title.setTextSize(22);
        content.addView(title, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        status = new TextView(this);
        status.setTextSize(14);
        LinearLayout.LayoutParams statusParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        statusParams.topMargin = pad;
        statusParams.bottomMargin = pad;
        content.addView(status, statusParams);

        Button pair = new Button(this);
        pair.setText("Trust this installed Termux");
        pair.setFilterTouchesWhenObscured(true);
        pair.setOnClickListener(view -> confirmPairing());
        content.addView(pair, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        Button revoke = new Button(this);
        revoke.setText("Revoke Termux pairing");
        revoke.setFilterTouchesWhenObscured(true);
        revoke.setOnClickListener(view -> confirmRevoke());
        content.addView(revoke, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        ScrollView scroll = new ScrollView(this);
        scroll.addView(content);
        setContentView(scroll);
        refresh();
    }

    private void refresh() {
        try {
            identity = BrokerStore.inspectTermux(this);
            String paired = BrokerStore.isPaired(this)
                    ? "PAIRED — Binder calls from this exact UID and pinned signer are eligible."
                    : "NOT PAIRED — all external Binder calls are denied.";
            status.setText(
                    "Package: " + BrokerStore.TERMUX_PACKAGE + "\n"
                    + "Version: " + identity.versionName + " (" + identity.versionCode + ")\n"
                    + "Android UID: " + identity.uid + "\n"
                    + "Current signer SHA-256:\n" + identity.signerDisplay() + "\n"
                    + "Pinned official F-Droid signer:\n"
                    + BrokerStore.SUPPORTED_TERMUX_SIGNER_SHA256 + "\n\n"
                    + "Stored UID: " + BrokerStore.pinnedUid(this) + "\n"
                    + "Stored signer:\n" + BrokerStore.pinnedSignerString(this) + "\n\n"
                    + paired + "\n\n"
                    + "Only official F-Droid Termux v0.118.3 signer identity is accepted by this build. "
                    + "A different release channel or rotated signer is denied."
            );
        } catch (PackageManager.NameNotFoundException | SecurityException error) {
            identity = null;
            status.setText(
                    "Termux package/signing identity could not be inspected or does not match "
                    + "the pinned official F-Droid certificate.\n"
                    + "Pairing and Binder access are disabled.\n"
                    + error.getClass().getSimpleName()
            );
        }
    }

    private void confirmPairing() {
        if (identity == null) {
            refresh();
            return;
        }
        final BrokerStore.TermuxIdentity shownIdentity = identity;
        new AlertDialog.Builder(this)
                .setTitle("Trust official F-Droid Termux?")
                .setMessage(
                        "This pairs the installed Termux Android UID with the official "
                        + "F-Droid signing certificate pinned in this broker build. The broker "
                        + "will reject a different package identity or signer. Only a read-only "
                        + "status call is enabled; no file or command capability exists.\n\n"
                        + "UID: " + shownIdentity.uid + "\n"
                        + "Signer: " + shownIdentity.signerDisplay() + "\n"
                        + "Expected: " + BrokerStore.SUPPORTED_TERMUX_SIGNER_SHA256
                )
                .setNegativeButton("Cancel", null)
                .setPositiveButton("Trust", (dialog, which) -> {
                    try {
                        BrokerStore.TermuxIdentity current = BrokerStore.inspectTermux(this);
                        boolean unchanged = current.uid == shownIdentity.uid
                                && current.signerDigests.equals(shownIdentity.signerDigests);
                        if (!unchanged || !BrokerStore.ownerPairTermux(this, current)) {
                            refresh();
                            status.setText(status.getText()
                                    + "\n\nPairing not saved: identity changed or private storage commit failed.");
                            return;
                        }
                        refresh();
                    } catch (PackageManager.NameNotFoundException | SecurityException error) {
                        refresh();
                    }
                })
                .show();
    }

    private void confirmRevoke() {
        new AlertDialog.Builder(this)
                .setTitle("Revoke Termux pairing?")
                .setMessage("All external Binder status calls will be denied until paired again.")
                .setNegativeButton("Cancel", null)
                .setPositiveButton("Revoke", (dialog, which) -> {
                    BrokerStore.revokePairing(this);
                    refresh();
                })
                .show();
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (status != null) refresh();
    }
}
