# SPDX-License-Identifier: LGPL-3.0-only
# Mornye Player for exteraGram. Copyright 2026 BroNik (@BroZYTnikkkk).
# Based on Mornye by zarzet (https://github.com/mornyeapp/Mornye), LGPL-3.0-only.

"""Android services for the extension host: WebView, javax.crypto, media."""

import os
from android_utils import run_on_ui_thread
from .logs import log
from java import jclass
from org.telegram.messenger import ApplicationLoader
from .common import mutagen


class _Platform:
    """Android services the extension host needs (WebView, javax.crypto, media)."""

    def __init__(self):
        self.webview = None

    # -- the hidden WebView that runs extension workers

    def start_page(self, url):
        def create():
            try:
                WebView = jclass("android.webkit.WebView")
                context = ApplicationLoader.applicationContext
                if self.webview is not None:
                    try:
                        self.webview.destroy()
                    except Exception:
                        pass
                view = WebView(context)
                settings = view.getSettings()
                settings.setJavaScriptEnabled(True)
                settings.setDomStorageEnabled(True)
                settings.setCacheMode(jclass("android.webkit.WebSettings").LOAD_NO_CACHE)
                view.setWebViewClient(jclass("android.webkit.WebViewClient")())
                view.resumeTimers()
                view.onResume()
                view.loadUrl(url)
                self.webview = view
            except Exception as e:
                log("[Mornye] extension WebView: %s" % e)
        run_on_ui_thread(create)

    def stop_page(self):
        view, self.webview = self.webview, None
        if view is not None:
            run_on_ui_thread(lambda: view.destroy())

    # -- crypto

    @staticmethod
    def _bytes(value):
        return bytes(value) if value is not None else b""

    def block_cipher(self, algorithm, mode, key, iv, decrypt):
        Cipher = jclass("javax.crypto.Cipher")
        SecretKeySpec = jclass("javax.crypto.spec.SecretKeySpec")
        IvParameterSpec = jclass("javax.crypto.spec.IvParameterSpec")
        name = "Blowfish" if algorithm == "blowfish" else "AES"
        cipher = Cipher.getInstance("%s/%s/NoPadding" % (name, mode.upper()))
        op = Cipher.DECRYPT_MODE if decrypt else Cipher.ENCRYPT_MODE
        spec = SecretKeySpec(key, name)
        if mode == "ecb":
            cipher.init(op, spec)
        else:
            cipher.init(op, spec, IvParameterSpec(iv))

        def run(chunk):
            # doFinal returns the cipher to its initial IV for the next segment.
            return self._bytes(cipher.doFinal(chunk))
        return run

    def aes_gcm(self, encrypt, key, nonce, data):
        Cipher = jclass("javax.crypto.Cipher")
        cipher = Cipher.getInstance("AES/GCM/NoPadding")
        spec = jclass("javax.crypto.spec.SecretKeySpec")(key, "AES")
        gcm = jclass("javax.crypto.spec.GCMParameterSpec")(128, nonce)
        cipher.init(Cipher.ENCRYPT_MODE if encrypt else Cipher.DECRYPT_MODE, spec, gcm)
        return self._bytes(cipher.doFinal(data))

    # -- media

    def media_quality(self, path):
        info = {"bit_depth": 0, "sample_rate": 0, "duration": 0, "codec": "", "total_samples": 0}
        if mutagen is not None:
            audio = mutagen.File(path)
            if audio is not None and audio.info is not None:
                info["sample_rate"] = int(getattr(audio.info, "sample_rate", 0) or 0)
                info["bit_depth"] = int(getattr(audio.info, "bits_per_sample", 0) or 0)
                info["duration"] = int(getattr(audio.info, "length", 0) or 0)
                info["total_samples"] = int(getattr(audio.info, "total_samples", 0) or 0)
                info["codec"] = type(audio).__name__.lower()
        return info

    def remux(self, source, target, container="m4a"):
        """Codec-copy into MP4 with MediaExtractor/MediaMuxer (no FFmpeg here)."""
        try:
            MediaExtractor = jclass("android.media.MediaExtractor")
            MediaMuxer = jclass("android.media.MediaMuxer")
            MediaCodec = jclass("android.media.MediaCodec")
            ByteBuffer = jclass("java.nio.ByteBuffer")
            extractor = MediaExtractor()
            extractor.setDataSource(source)
            track = -1
            for i in range(extractor.getTrackCount()):
                if str(extractor.getTrackFormat(i).getString("mime") or "").startswith("audio/"):
                    track = i
                    break
            if track < 0:
                extractor.release()
                return False
            extractor.selectTrack(track)
            muxer = MediaMuxer(target, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)
            out = muxer.addTrack(extractor.getTrackFormat(track))
            muxer.start()
            buffer = ByteBuffer.allocate(1 << 20)
            info = MediaCodec.BufferInfo()
            while True:
                size = extractor.readSampleData(buffer, 0)
                if size < 0:
                    break
                info.set(0, size, extractor.getSampleTime(), extractor.getSampleFlags())
                muxer.writeSampleData(out, buffer, info)
                extractor.advance()
            muxer.stop()
            muxer.release()
            extractor.release()
            return os.path.isfile(target) and os.path.getsize(target) > 0
        except Exception as e:
            log("[Mornye] remux: %s" % e)
            try:
                os.remove(target)
            except OSError:
                pass
            return False

    def open_url(self, url):
        def go():
            Intent = jclass("android.content.Intent")
            intent = Intent(Intent.ACTION_VIEW, jclass("android.net.Uri").parse(url))
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            ApplicationLoader.applicationContext.startActivity(intent)
        run_on_ui_thread(go)


PLATFORM = _Platform()
