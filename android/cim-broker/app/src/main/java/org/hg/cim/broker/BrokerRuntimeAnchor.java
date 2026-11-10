package org.hg.cim.broker;

import android.content.Context;
import android.os.Build;
import android.system.Os;
import android.system.OsConstants;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.InputStream;
import java.security.MessageDigest;

/**
 * Runtime trust anchor is embedded in the signed Broker APK. Empty is valid and means
 * fail-closed / no approved runtime. A backend can run only when exactly one provenance-
 * complete entry matches the installed signed payload byte-for-byte.
 */
final class BrokerRuntimeAnchor {
    private BrokerRuntimeAnchor() {}

    static boolean verify(Context context, File executable) {
        try {
            if (executable == null || !executable.isFile() || !executable.canExecute()) return false;
            android.system.StructStat stat = Os.lstat(executable.getAbsolutePath());
            if ((stat.st_mode & OsConstants.S_IFMT) != OsConstants.S_IFREG
                    || stat.st_uid != android.os.Process.myUid()
                    || (stat.st_mode & 0022) != 0) return false;

            JSONObject root;
            try (InputStream in = context.getAssets().open("trusted-runtimes.json")) {
                ByteArrayOutputStream buffer = new ByteArrayOutputStream();
                byte[] chunk = new byte[8192];
                int count;
                while ((count = in.read(chunk)) != -1) {
                    if (buffer.size() + count > 64 * 1024) return false;
                    buffer.write(chunk, 0, count);
                }
                root = new JSONObject(buffer.toString("UTF-8"));
            }
            if (!"hg-android-broker-runtime-anchor-v1".equals(root.optString("schema"))) return false;
            JSONArray entries = root.optJSONArray("runtimes");
            if (entries == null || entries.length() != 1) return false;

            JSONObject item = entries.getJSONObject(0);
            JSONObject provenance = item.optJSONObject("provenance");
            if (provenance == null) return false;
            if (!"ollama".equals(item.optString("name"))) return false;
            if (!Build.SUPPORTED_ABIS[0].equals(item.optString("abi"))) return false;
            if (!hex64(item.optString("sha256"))) return false;
            if (!hex64(provenance.optString("source_commit_sha256"))
                    || !hex40(provenance.optString("source_commit"))
                    || !hex40(provenance.optString("recipe_commit"))) return false;
            if (!"VERIFIED".equals(provenance.optString("provenance_status"))) return false;
            if (!provenance.optBoolean("reproducible_build", false)
                    || !provenance.optBoolean("signed_distribution_verified", false)) return false;

            return constantTimeEquals(item.getString("sha256"), sha256(executable));
        } catch (Exception error) {
            return false;
        }
    }

    private static String sha256(File file) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream in = new java.io.FileInputStream(file)) {
            byte[] buf = new byte[64 * 1024];
            int n;
            while ((n = in.read(buf)) != -1) digest.update(buf, 0, n);
        }
        StringBuilder out = new StringBuilder();
        for (byte b : digest.digest()) out.append(String.format("%02x", b & 0xff));
        return out.toString();
    }

    static boolean hex64(String s) {
        if (s == null || s.length() != 64) return false;
        for (int i=0;i<s.length();i++) if (!((s.charAt(i)>='0'&&s.charAt(i)<='9')||(s.charAt(i)>='a'&&s.charAt(i)<='f'))) return false;
        return true;
    }
    private static boolean hex40(String s) {
        if (s == null || s.length() != 40) return false;
        for (int i=0;i<s.length();i++) if (!((s.charAt(i)>='0'&&s.charAt(i)<='9')||(s.charAt(i)>='a'&&s.charAt(i)<='f'))) return false;
        return true;
    }
    private static boolean constantTimeEquals(String a,String b) {
        if(a==null||b==null)return false;
        int diff=a.length()^b.length(), n=Math.max(a.length(),b.length());
        for(int i=0;i<n;i++)diff|=(i<a.length()?a.charAt(i):0)^(i<b.length()?b.charAt(i):0);
        return diff==0;
    }
}
