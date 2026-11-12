package org.hg.cim.broker;

import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.Set;

/** Pure policy for the Android Binder caller identity tuple. */
public final class CallerTrustEvaluator {
    public static final String ALLOW = "ALLOW";
    public static final String DENY_UID = "DENY_UID";
    public static final String DENY_PACKAGE = "DENY_PACKAGE";
    public static final String DENY_SIGNER = "DENY_SIGNER";
    public static final String DENY_UNPAIRED = "DENY_UNPAIRED";

    private CallerTrustEvaluator() {}

    public static String evaluate(
            int binderCallerUid,
            int installedTermuxUid,
            String[] packagesForUid,
            int pinnedUid,
            Set<String> actualSignerDigests,
            Set<String> pinnedSignerDigests,
            boolean ownerPaired) {

        if (!ownerPaired || pinnedUid < 0 || pinnedSignerDigests == null
                || pinnedSignerDigests.isEmpty()) {
            return DENY_UNPAIRED;
        }
        if (binderCallerUid < 0 || binderCallerUid != installedTermuxUid
                || binderCallerUid != pinnedUid) {
            return DENY_UID;
        }
        if (packagesForUid == null || packagesForUid.length != 1
                || !"com.termux".equals(packagesForUid[0])) {
            return DENY_PACKAGE;
        }
        if (actualSignerDigests == null || actualSignerDigests.isEmpty()
                || !actualSignerDigests.equals(pinnedSignerDigests)) {
            return DENY_SIGNER;
        }
        return ALLOW;
    }

    public static Set<String> immutableSignerSet(String... values) {
        if (values == null || values.length == 0) {
            return Collections.emptySet();
        }
        return Collections.unmodifiableSet(new HashSet<>(Arrays.asList(values)));
    }
}
