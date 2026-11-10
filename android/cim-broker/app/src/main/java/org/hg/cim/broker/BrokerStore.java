package org.hg.cim.broker;

import android.content.Context;
import android.content.SharedPreferences;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import android.content.pm.SigningInfo;
import android.os.Build;

import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Arrays;
import java.util.Set;
import java.util.TreeSet;

final class BrokerStore {
    static final String TERMUX_PACKAGE = "com.termux";
    // Official F-Droid Termux v0.118.3 signer published by termux/termux-app.
    static final String SUPPORTED_TERMUX_SIGNER_SHA256 =
            "228fb2cfe90831c1499ec3ccaf61e96e8e1ce70766b9474672ce427334d41c42";
    private static final String PREFS = "hg_cim_broker_owner_pairing_v1";
    private static final String KEY_UID = "termux_uid";
    private static final String KEY_SIGNERS = "termux_signers_sha256";
    private static final String KEY_PAIRED = "owner_paired";
    private static final String KEY_INFERENCE_ENABLED = "owner_enabled_inference";

    private BrokerStore() {}

    static final class TermuxIdentity {
        final int uid;
        final String versionName;
        final long versionCode;
        final Set<String> signerDigests;

        TermuxIdentity(int uid, String versionName, long versionCode, Set<String> signerDigests) {
            this.uid = uid;
            this.versionName = versionName;
            this.versionCode = versionCode;
            this.signerDigests = signerDigests;
        }

        String signerDisplay() {
            return String.join(",", signerDigests);
        }
    }

    static TermuxIdentity inspectTermux(Context context) throws PackageManager.NameNotFoundException {
        PackageManager pm = context.getPackageManager();
        PackageInfo info = getPackageInfo(pm);
        ApplicationInfo appInfo = pm.getApplicationInfo(TERMUX_PACKAGE, 0);
        if (info.signingInfo == null) {
            throw new SecurityException("Termux signing information unavailable");
        }

        Signature[] signatures = currentSigners(info.signingInfo);
        if (signatures.length == 0) {
            throw new SecurityException("Termux signer set is empty");
        }

        Set<String> digests = new TreeSet<>();
        for (Signature signature : signatures) {
            digests.add(sha256(signature.toByteArray()));
        }
        if (!digests.equals(java.util.Collections.singleton(SUPPORTED_TERMUX_SIGNER_SHA256))) {
            throw new SecurityException("installed Termux is not signed by the pinned F-Droid certificate");
        }

        long versionCode = Build.VERSION.SDK_INT >= 28
                ? info.getLongVersionCode() : info.versionCode;
        return new TermuxIdentity(
                appInfo.uid,
                info.versionName == null ? "unknown" : info.versionName,
                versionCode,
                digests
        );
    }

    private static PackageInfo getPackageInfo(PackageManager pm)
            throws PackageManager.NameNotFoundException {
        if (Build.VERSION.SDK_INT >= 33) {
            return pm.getPackageInfo(
                    TERMUX_PACKAGE,
                    PackageManager.PackageInfoFlags.of(PackageManager.GET_SIGNING_CERTIFICATES)
            );
        }
        return pm.getPackageInfo(TERMUX_PACKAGE, PackageManager.GET_SIGNING_CERTIFICATES);
    }

    private static Signature[] currentSigners(SigningInfo info) {
        return info.getApkContentsSigners();
    }

    private static String sha256(byte[] input) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(input);
            StringBuilder result = new StringBuilder(digest.length * 2);
            for (byte value : digest) {
                result.append(String.format("%02x", value & 0xff));
            }
            return result.toString();
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException("SHA-256 is unavailable", impossible);
        }
    }

    static boolean ownerPairTermux(Context context, TermuxIdentity identity) {
        if (identity == null || identity.uid < 0
                || !identity.signerDigests.equals(
                        java.util.Collections.singleton(SUPPORTED_TERMUX_SIGNER_SHA256))) {
            return false;
        }
        SharedPreferences prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        return prefs.edit()
                .putInt(KEY_UID, identity.uid)
                .putString(KEY_SIGNERS, String.join(",", identity.signerDigests))
                .putBoolean(KEY_PAIRED, true)
                .commit();
    }

    static void revokePairing(Context context) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().clear().apply();
    }


    static boolean isInferenceEnabled(Context context) {
        SharedPreferences prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        return prefs.getBoolean(KEY_PAIRED, false)
                && prefs.getBoolean(KEY_INFERENCE_ENABLED, false);
    }

    static boolean setInferenceEnabled(Context context, boolean enabled) {
        SharedPreferences prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        if (!prefs.getBoolean(KEY_PAIRED, false)) return false;
        return prefs.edit().putBoolean(KEY_INFERENCE_ENABLED, enabled).commit();
    }

    static boolean isPaired(Context context) {
        SharedPreferences prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        return prefs.getBoolean(KEY_PAIRED, false)
                && prefs.getInt(KEY_UID, -1) >= 0
                && !prefs.getString(KEY_SIGNERS, "").isEmpty();
    }

    static int pinnedUid(Context context) {
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getInt(KEY_UID, -1);
    }

    static String pinnedSignerString(Context context) {
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(KEY_SIGNERS, "");
    }

    static TermuxIdentity authenticateBinderCaller(Context context, int binderCallerUid) {
        try {
            TermuxIdentity identity = inspectTermux(context);
            String[] packages = context.getPackageManager().getPackagesForUid(binderCallerUid);
            SharedPreferences prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
            Set<String> pinned = parseSignerString(prefs.getString(KEY_SIGNERS, ""));
            boolean paired = prefs.getBoolean(KEY_PAIRED, false);

            String decision = CallerTrustEvaluator.evaluate(
                    binderCallerUid,
                    identity.uid,
                    packages,
                    prefs.getInt(KEY_UID, -1),
                    identity.signerDigests,
                    pinned,
                    paired
            );
            if (!CallerTrustEvaluator.ALLOW.equals(decision)) {
                throw new SecurityException("CIM broker caller denied: " + decision);
            }
            return identity;
        } catch (PackageManager.NameNotFoundException error) {
            throw new SecurityException("CIM broker caller denied: TERMUX_PACKAGE_UNAVAILABLE", error);
        } catch (SecurityException error) {
            // Preserve the fail-closed policy reason for machine-verifiable security evidence.
            // Never return caller identity or trust-store contents in this exception.
            throw error;
        }
    }

    private static Set<String> parseSignerString(String value) {
        Set<String> result = new TreeSet<>();
        if (value != null && !value.isEmpty()) {
            result.addAll(Arrays.asList(value.split(",")));
        }
        return result;
    }
}
