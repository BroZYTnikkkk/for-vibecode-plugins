// SPDX-License-Identifier: LGPL-3.0-only
// Sculpt Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
// Speaks Mornye Link, the protocol of Mornye by zarzet (https://github.com/mornyeapp/Mornye), LGPL-3.0-only.
package sculpt;

import android.util.Log;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.security.cert.CertificateException;
import java.security.cert.X509Certificate;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLSocketFactory;
import javax.net.ssl.TrustManager;
import javax.net.ssl.X509TrustManager;

/**
 * Telegram's player cannot trust the computer's self-signed certificate, so it reads a song from this little server
 * on the phone, which checks the certificate's fingerprint and passes the bytes and the seeking ranges through.
 * Static calls only: Python cannot hold objects of this DEX across a reinstall. Other apps can reach 127.0.0.1 too,
 * so every address carries a random token.
 */
public final class LinkProxy {

    private static final String TAG = "SculptLink";
    private static final int BUFFER = 64 * 1024;
    private static Server server;

    private LinkProxy() {
    }

    /** The address songs are read from, ending in "/"; the running server is kept while nothing about it changed. */
    public static synchronized String start(String host, int port, String fingerprint, String query) throws Exception {
        String key = host + ":" + port + "|" + fingerprint + "|";
        if (server != null && server.key.equals(key) && server.alive()) {
            return server.base();
        }
        stop();
        server = new Server(key, "https://" + host + ":" + port + "/rest/stream.view?format=raw&" + query + "&id=", factory(fingerprint));
        return server.base();
    }

    public static synchronized void stop() {
        if (server != null) {
            server.close();
            server = null;
        }
    }

    private static SSLSocketFactory factory(final String fingerprint) throws Exception {
        TrustManager pinned = new X509TrustManager() {
            @Override
            public void checkClientTrusted(X509Certificate[] chain, String type) throws CertificateException {
                throw new CertificateException("not a server");
            }

            @Override
            public void checkServerTrusted(X509Certificate[] chain, String type) throws CertificateException {
                try {
                    byte[] hash = MessageDigest.getInstance("SHA-256").digest(chain[0].getEncoded());
                    if (!hex(hash).equalsIgnoreCase(fingerprint)) {
                        throw new CertificateException("another certificate");
                    }
                } catch (java.security.NoSuchAlgorithmException e) {
                    throw new CertificateException(e);
                }
            }

            @Override
            public X509Certificate[] getAcceptedIssuers() {
                return new X509Certificate[0];
            }
        };
        SSLContext context = SSLContext.getInstance("TLS");
        context.init(null, new TrustManager[]{pinned}, new SecureRandom());
        return context.getSocketFactory();
    }

    private static String hex(byte[] bytes) {
        StringBuilder text = new StringBuilder(bytes.length * 2);
        for (byte b : bytes) {
            text.append(String.format("%02x", b & 255));
        }
        return text.toString();
    }

    private static final class Server implements Runnable {
        final String key;
        private final String upstream;
        private final SSLSocketFactory factory;
        private final ServerSocket socket;
        private final String token;
        private final ExecutorService workers = Executors.newCachedThreadPool(r -> {
            Thread thread = new Thread(r, "sculpt-link-stream");
            thread.setDaemon(true);
            return thread;
        });

        Server(String key, String upstream, SSLSocketFactory factory) throws IOException {
            this.key = key;
            this.upstream = upstream;
            this.factory = factory;
            socket = new ServerSocket(0, 8, InetAddress.getByName("127.0.0.1"));
            byte[] random = new byte[16];
            new SecureRandom().nextBytes(random);
            token = hex(random);
            Thread accepting = new Thread(this, "sculpt-link-proxy");
            accepting.setDaemon(true);
            accepting.start();
        }

        String base() {
            return "http://127.0.0.1:" + socket.getLocalPort() + "/" + token + "/";
        }

        boolean alive() {
            return !socket.isClosed();
        }

        void close() {
            try {
                socket.close();
            } catch (IOException ignored) {
                // closing anyway
            }
            workers.shutdownNow();
        }

        @Override
        public void run() {
            while (!socket.isClosed()) {
                try {
                    final Socket client = socket.accept();
                    workers.execute(() -> serve(client));
                } catch (IOException e) {
                    return;
                }
            }
        }

        private void serve(Socket client) {
            HttpURLConnection connection = null;
            try (Socket open = client) {
                BufferedReader head = new BufferedReader(new InputStreamReader(open.getInputStream(), StandardCharsets.ISO_8859_1));
                String request = head.readLine();
                String range = null;
                for (String line = head.readLine(); line != null && !line.isEmpty(); line = head.readLine()) {
                    if (line.regionMatches(true, 0, "range:", 0, 6)) {
                        range = line.substring(6).trim();
                    }
                }
                OutputStream out = open.getOutputStream();
                String[] parts = request == null ? new String[0] : request.split(" ");
                String prefix = "/" + token + "/";
                if (parts.length < 2 || !"GET".equals(parts[0]) || !parts[1].startsWith(prefix)) {
                    refuse(out, "403 Forbidden");
                    return;
                }
                connection = (HttpURLConnection) new URL(upstream + parts[1].substring(prefix.length())).openConnection();
                ((HttpsURLConnection) connection).setSSLSocketFactory(factory);
                ((HttpsURLConnection) connection).setHostnameVerifier((name, session) -> true);  // the fingerprint is the check
                connection.setConnectTimeout(8000);
                connection.setReadTimeout(30000);
                if (range != null) {
                    connection.setRequestProperty("Range", range);
                }
                int code = connection.getResponseCode();
                StringBuilder answer = new StringBuilder("HTTP/1.1 ").append(code).append(" Media\r\nConnection: close\r\n");
                for (String name : new String[]{"Content-Type", "Content-Length", "Content-Range", "Accept-Ranges"}) {
                    String value = connection.getHeaderField(name);
                    if (value != null) {
                        answer.append(name).append(": ").append(value).append("\r\n");
                    }
                }
                out.write(answer.append("\r\n").toString().getBytes(StandardCharsets.ISO_8859_1));
                InputStream in = code >= 400 ? connection.getErrorStream() : connection.getInputStream();
                if (in != null) {
                    byte[] buffer = new byte[BUFFER];
                    for (int read = in.read(buffer); read >= 0; read = in.read(buffer)) {
                        out.write(buffer, 0, read);
                    }
                }
                out.flush();
            } catch (IOException e) {
                // the usual end of a read: the player seeks by dropping the connection
                Log.d(TAG, e.getClass().getSimpleName());
            } finally {
                if (connection != null) {
                    connection.disconnect();
                }
            }
        }

        private static void refuse(OutputStream out, String status) throws IOException {
            out.write(("HTTP/1.1 " + status + "\r\nContent-Length: 0\r\nConnection: close\r\n\r\n").getBytes(StandardCharsets.ISO_8859_1));
        }
    }
}
