"""Structural balance check for all Kotlin files in the app project.

    python D:/M175Bridge/tools/kotlin_syntax_check.py

Strips strings/comments then verifies braces and parens balance per file.
Catches obvious syntax breakage before Android Studio ever opens.
"""
import glob
import re
import sys

ROOT = "D:/M175-Android-App"
files = glob.glob(ROOT + "/app/src/main/java/**/*.kt", recursive=True)
if not files:
    print("no Kotlin files found!")
    sys.exit(1)

ok = True
for f in files:
    s = open(f, encoding="utf-8").read()
    s2 = re.sub(r'"(?:\\.|[^"\\])*"', '""', s)          # strings
    s2 = re.sub(r"/\*.*?\*/", "", s2, flags=re.S)       # block comments
    s2 = re.sub(r"//[^\n]*", "", s2)                    # line comments
    b = s2.count("{") - s2.count("}")
    p = s2.count("(") - s2.count(")")
    name = f.replace("\\", "/").split("/")[-1]
    if b == 0 and p == 0:
        print("%-30s OK" % name)
    else:
        ok = False
        print("%-30s IMBALANCE braces=%+d parens=%+d" % (name, b, p))

print()
print("ALL KOTLIN FILES STRUCTURALLY BALANCED" if ok else "FIX NEEDED")
sys.exit(0 if ok else 1)
