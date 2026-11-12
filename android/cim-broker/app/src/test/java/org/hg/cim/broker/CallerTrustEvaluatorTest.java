package org.hg.cim.broker;

import org.junit.Test;

import java.util.Set;

import static org.junit.Assert.assertEquals;

public final class CallerTrustEvaluatorTest {
    private static final Set<String> SIGNER = CallerTrustEvaluator.immutableSignerSet("aa11");
    private static final String[] TERMUX_PACKAGE = {"com.termux"};

    @Test
    public void acceptsExactUidPackageAndPinnedSigner() {
        assertEquals(CallerTrustEvaluator.ALLOW,
                CallerTrustEvaluator.evaluate(10460, 10460, TERMUX_PACKAGE, 10460, SIGNER, SIGNER, true));
    }

    @Test
    public void rejectsDifferentUid() {
        assertEquals(CallerTrustEvaluator.DENY_UID,
                CallerTrustEvaluator.evaluate(2000, 10460, TERMUX_PACKAGE, 10460, SIGNER, SIGNER, true));
    }

    @Test
    public void rejectsCallerUidDifferentFromInstalledTermuxUid() {
        assertEquals(CallerTrustEvaluator.DENY_UID,
                CallerTrustEvaluator.evaluate(10461, 10460, TERMUX_PACKAGE, 10460, SIGNER, SIGNER, true));
    }

    @Test
    public void rejectsUnexpectedPackageForUid() {
        assertEquals(CallerTrustEvaluator.DENY_PACKAGE,
                CallerTrustEvaluator.evaluate(10460, 10460, new String[]{"evil.package"}, 10460, SIGNER, SIGNER, true));
    }

    @Test
    public void rejectsSharedUidWithAdditionalPackage() {
        assertEquals(CallerTrustEvaluator.DENY_PACKAGE,
                CallerTrustEvaluator.evaluate(10460, 10460, new String[]{"com.termux", "other.package"}, 10460, SIGNER, SIGNER, true));
    }

    @Test
    public void rejectsSignerRotation() {
        assertEquals(CallerTrustEvaluator.DENY_SIGNER,
                CallerTrustEvaluator.evaluate(10460, 10460, TERMUX_PACKAGE, 10460,
                        CallerTrustEvaluator.immutableSignerSet("bb22"), SIGNER, true));
    }

    @Test
    public void rejectsUnpairedBroker() {
        assertEquals(CallerTrustEvaluator.DENY_UNPAIRED,
                CallerTrustEvaluator.evaluate(10460, 10460, TERMUX_PACKAGE, -1, SIGNER,
                        java.util.Collections.emptySet(), false));
    }
}
