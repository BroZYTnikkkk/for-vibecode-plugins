"""Compiles java/src into assets/sculpt.dex.

java/stubs stand in for exteraGram's own classes at compile time only: they are left out of the DEX,
so on the phone the code links against the app's real MessageObject and TLRPC.
"""
import glob
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
JDK = os.environ.get("SCULPT_JDK", r"C:\apktools\jdk21-extract\jdk-21.0.13+9")
SDK = os.environ.get("SCULPT_ANDROID_SDK", r"C:\apktools\android-sdk")
ANDROID_JAR = os.path.join(SDK, "platforms", "android-35", "android.jar")
D8_JAR = os.path.join(SDK, "build-tools", "35.0.0", "lib", "d8.jar")
MIN_API = "26"


def run(command):
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        sys.exit("%s\n%s%s" % (" ".join(command[:3]), result.stdout, result.stderr))


def main():
    work = tempfile.mkdtemp(prefix="sculpt_dex_")
    try:
        stubs = os.path.join(work, "stubs")
        classes = os.path.join(work, "classes")
        out = os.path.join(work, "out")
        for folder in (stubs, classes, out):
            os.makedirs(folder)
        javac = os.path.join(JDK, "bin", "javac")
        java = os.path.join(JDK, "bin", "java")
        run([javac, "--release", "11", "-nowarn", "-cp", ANDROID_JAR, "-d", stubs]
            + glob.glob(os.path.join(HERE, "java", "stubs", "**", "*.java"), recursive=True))
        run([javac, "--release", "11", "-Xlint:-options", "-cp", os.pathsep.join([ANDROID_JAR, stubs]), "-d", classes]
            + glob.glob(os.path.join(HERE, "java", "src", "**", "*.java"), recursive=True))
        compiled = glob.glob(os.path.join(classes, "**", "*.class"), recursive=True)
        run([java, "-cp", D8_JAR, "com.android.tools.r8.D8", "--release", "--min-api", MIN_API,
             "--lib", ANDROID_JAR, "--classpath", stubs, "--output", out] + compiled)
        target = os.path.join(HERE, "assets", "sculpt.dex")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(os.path.join(out, "classes.dex"), target)
        print("built assets/sculpt.dex, %d bytes, %d classes" % (os.path.getsize(target), len(compiled)))
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
