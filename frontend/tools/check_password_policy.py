"""Check public frontend policy data and representative behavior against locked Django; no DB access."""

import gzip
import hashlib
from importlib.metadata import distribution, version
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import unicodedata


ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "frontend/src/auth/password-policy.json"


def public_data():
    import django
    source = Path(django.__file__).parent / "contrib/auth/common-passwords.txt.gz"
    ranges = []
    for point in range(0x110000):
        if chr(point).isdigit():
            if ranges and point == ranges[-1][1] + 1:
                ranges[-1][1] = point
            else:
                ranges.append([point, point])
    return {
        "djangoVersion": version("Django"), "unicodeVersion": unicodedata.unidata_version,
        "sourceSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "commonPasswords": sorted({line.strip() for line in gzip.decompress(source.read_bytes()).decode("utf-8").splitlines()}),
        "digitRanges": ranges,
    }


def main():
    data = public_data()
    if sys.argv[1:] == ["--write"]:
        TARGET.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        package = distribution("Django")
        license_path = next(path for path in package.files if str(path).endswith(".dist-info/licenses/LICENSE"))
        TARGET.with_name("LICENSE-Django.txt").write_bytes(package.locate_file(license_path).read_bytes())
        print("PUBLIC_POLICY_DATA=UPDATED")
        return
    if sys.argv[1:] or json.loads(TARGET.read_text(encoding="utf-8")) != data:
        raise RuntimeError("Public password policy data differs from the locked runtime")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    os.environ.setdefault("DJANGO_SECRET_KEY", secrets.token_urlsafe(48))
    os.environ.setdefault("POSTGRES_PASSWORD", secrets.token_urlsafe(48))
    sys.path.insert(0, str(ROOT / "backend"))
    import django
    django.setup()
    from django.conf import settings
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError
    from django.db import connection
    from apps.accounts.models import User

    expected = ["UserAttributeSimilarityValidator", "MinimumLengthValidator", "CommonPasswordValidator", "NumericPasswordValidator"]
    if settings.AUTH_PASSWORD_VALIDATORS != [{"NAME": "django.contrib.auth.password_validation." + name} for name in expected]:
        raise RuntimeError("Backend policy changed; review frontend validation")
    cases = [{"email": "learner@example.invalid", "password": value} for value in data["commonPasswords"][::97]]
    cases += [{"email": " learner+tag@EXAMPLE.invalid ", "password": value} for value in (
        "learner1", "LEARNER123!", "invalid1", "PASSWORD123 ", "²²²²²²²²", "١٢٣٤٥٦٧٨", "ⅦⅦⅦⅦⅦⅦⅦⅦ",
        "😀😀😀😀", "😀😀😀😀😀😀😀😀", "        ", " unique-phrase-18! ", "\u0085password\u0085",
        "a" * 300, "example.invalid!", "qil-independent-passphrase",
    )]
    wanted = []
    for item in cases:
        try:
            validate_password(item["password"], User(email=User.objects.normalize_email(item["email"])))
            wanted.append([])
        except ValidationError as error:
            wanted.append([entry.code for entry in error.error_list])
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("Project Node.js is unavailable")
    result = subprocess.run([node, str(ROOT / "frontend/tools/policy-probe.mjs")], cwd=ROOT,
        input=json.dumps(cases), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", timeout=30)
    if result.returncode or json.loads(result.stdout) != wanted:
        raise RuntimeError("Frontend policy behavior differs from Django")
    if connection.connection is not None:
        raise RuntimeError("Policy check unexpectedly opened a database")
    print("PASSWORD_POLICY_PARITY=PASS " + str(len(cases)) + " cases; database untouched")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("PASSWORD_POLICY_PARITY=FAIL " + type(error).__name__)
        raise SystemExit(1)
