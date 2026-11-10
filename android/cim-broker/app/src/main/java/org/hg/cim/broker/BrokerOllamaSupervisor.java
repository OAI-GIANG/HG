package org.hg.cim.broker;

import android.content.Context;
import android.system.Os;
import android.system.OsConstants;

import java.io.File;
import java.io.IOException;
import java.util.Map;

/**
 * Starts a Broker-UID Ollama binary packaged in this APK's native library directory.
 *
 * The expected executable name is libollama.so only because Android's APK native-library
 * packaging extracts executable ELF files from ABI directories. The file must be a signed
 * APK payload, not a Termux path or a writable caller-supplied path.
 */
final class BrokerOllamaSupervisor {
    private final Context context;
    private java.lang.Process process;
    private int pid = -1;

    BrokerOllamaSupervisor(Context context) {
        this.context = context.getApplicationContext();
    }

    synchronized int ensureStarted() throws Exception {
        if (process != null && process.isAlive()) return pid;
        process = null;
        pid = -1;

        File executable = new File(context.getApplicationInfo().nativeLibraryDir, "libollama.so");
        if (!BrokerRuntimeAnchor.verify(context, executable)) {
            throw new SecurityException("BACKEND_NOT_ANCHORED: signed runtime manifest missing or digest mismatch");
        }
        if (Os.lstat(executable.getAbsolutePath()).st_uid != android.os.Process.myUid()) {
            throw new SecurityException("backend executable owner UID mismatch");
        }

        File root = new File(context.getNoBackupFilesDir(), "hg-model-broker");
        if (!root.exists() && !root.mkdirs()) throw new IOException("cannot create broker-private model directory");
        Os.chmod(root.getAbsolutePath(), 0700);
        if (Os.lstat(root.getAbsolutePath()).st_uid != android.os.Process.myUid()
                || (Os.lstat(root.getAbsolutePath()).st_mode & 0077) != 0) {
            throw new SecurityException("broker-private directory owner/mode mismatch");
        }

        File models = new File(root, "models");
        if (!models.exists() && !models.mkdirs()) throw new IOException("cannot create broker model directory");
        Os.chmod(models.getAbsolutePath(), 0700);

        File socket = new File(root, "ollama.sock");
        if (socket.exists()) {
            android.system.StructStat stale = Os.lstat(socket.getAbsolutePath());
            if ((stale.st_mode & OsConstants.S_IFMT) != OsConstants.S_IFSOCK
                    || stale.st_uid != android.os.Process.myUid()) {
                throw new SecurityException("refusing to remove a non-socket or foreign-owned stale path");
            }
            Os.remove(socket.getAbsolutePath());
        }

        ProcessBuilder builder = new ProcessBuilder(executable.getAbsolutePath(), "serve");
        Map<String, String> env = builder.environment();
        env.put("HOME", root.getAbsolutePath());
        env.put("OLLAMA_MODELS", models.getAbsolutePath());
        env.put("OLLAMA_SOCKET_PATH", socket.getAbsolutePath());
        env.put("OLLAMA_RUNNER_SOCKET_DIR", root.getAbsolutePath());
        env.put("OLLAMA_BROKER_PID", Integer.toString(android.os.Process.myPid()));
        env.put("OLLAMA_NOHISTORY", "true");
        env.remove("OLLAMA_HOST");
        env.remove("LD_PRELOAD");
        File log = new File(root, "ollama.log");
        if (log.exists()) {
            android.system.StructStat logStat = Os.lstat(log.getAbsolutePath());
            if ((logStat.st_mode & OsConstants.S_IFMT) != OsConstants.S_IFREG
                    || logStat.st_uid != android.os.Process.myUid()
                    || (logStat.st_mode & 0077) != 0) {
                throw new SecurityException("refusing an unsafe broker log file");
            }
        } else if (!log.createNewFile()) {
            throw new IOException("cannot create broker log file");
        }
        Os.chmod(log.getAbsolutePath(), 0600);
        builder.redirectErrorStream(true);
        builder.redirectOutput(ProcessBuilder.Redirect.appendTo(log));
        process = builder.start();
        pid = BrokerOllamaProcessLiveness.pidOf(process);
        if (pid <= 0 || !BrokerOllamaProcessLiveness.isSameProcess(
                process, pid, android.os.Process.myUid())) {
            stop();
            throw new SecurityException("backend process UID/PID could not be bound to ProcessBuilder handle");
        }
        return pid;
    }

    synchronized int pid() {
        return BrokerOllamaProcessLiveness.isSameProcess(process, pid, android.os.Process.myUid()) ? pid : -1;
    }

    synchronized java.lang.Process process() {
        return BrokerOllamaProcessLiveness.isSameProcess(process, pid, android.os.Process.myUid()) ? process : null;
    }

    synchronized File rootDirectory() {
        return new File(context.getNoBackupFilesDir(), "hg-model-broker");
    }

    synchronized File socketFile() {
        return new File(rootDirectory(), "ollama.sock");
    }

    synchronized boolean isAlive() {
        return BrokerOllamaProcessLiveness.isSameProcess(process, pid, android.os.Process.myUid());
    }

    synchronized void stop() {
        if (process == null) return;
        process.destroy();
        try {
            if (!process.waitFor(3, java.util.concurrent.TimeUnit.SECONDS)) process.destroyForcibly();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            process.destroyForcibly();
        } finally {
            process = null;
            pid = -1;
        }
    }
}
