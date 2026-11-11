#!/usr/bin/env python3
"""
Build script for Brain LLM Sync Extension.
Generates:
  1. dist/chrome/   - Pure Chromium Manifest V3 (service_worker)
  2. dist/firefox/  - Pure Firefox Manifest V3 (scripts, gecko settings)
  3. dist/brain-llm-sync-chrome.zip
  4. dist/brain-llm-sync-firefox.xpi
  5. dist/brain-llm-sync-firefox.zip
"""

import os
import json
import shutil
import zipfile

EXT_DIR = os.path.dirname(os.path.abspath(__file__))
# Store listings need a stable name; the version lives in manifest "version" only.
EXT_NAME = "Brain LLM Sync"
DIST_DIR = os.path.join(EXT_DIR, "dist")
CHROME_DIR = os.path.join(DIST_DIR, "chrome")
FIREFOX_DIR = os.path.join(DIST_DIR, "firefox")

def copy_assets(dest_dir):
    os.makedirs(dest_dir, exist_ok=True)
    for item in ["background.js", "popup", "content", "icons"]:
        src_path = os.path.join(EXT_DIR, item)
        dst_path = os.path.join(dest_dir, item)
        if os.path.isdir(src_path):
            if os.path.exists(dst_path):
                shutil.rmtree(dst_path)
            shutil.copytree(src_path, dst_path)
        elif os.path.isfile(src_path):
            shutil.copy2(src_path, dst_path)

def create_zip(source_dir, zip_path):
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(source_dir):
            for file in files:
                abs_path = os.path.join(root, file)
                rel_path = os.path.relpath(abs_path, source_dir)
                zf.write(abs_path, rel_path)
    print(f"  [Package] Created {os.path.basename(zip_path)} ({os.path.getsize(zip_path)} bytes)")

def bump_version(manifest_path, part="patch"):
    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    ver = data.get("version", "1.0.0")
    parts = [int(p) for p in ver.split(".")]
    while len(parts) < 3:
        parts.append(0)
    if part == "major":
        parts[0] += 1
        parts[1] = 0
        parts[2] = 0
    elif part == "minor":
        parts[1] += 1
        parts[2] = 0
    else:
        parts[2] += 1
    new_ver = ".".join(str(p) for p in parts)
    data["version"] = new_ver
    data["name"] = EXT_NAME
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    print(f"  [Version] Bumped {ver} -> {new_ver} (Name: {data['name']})")
    return new_ver

def get_or_create_chrome_key():
    key_path = os.path.join(EXT_DIR, "key.pem")
    try:
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        import base64
        import hashlib

        if not os.path.exists(key_path):
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            pem = key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            )
            with open(key_path, "wb") as f:
                f.write(pem)
        else:
            with open(key_path, "rb") as f:
                key = serialization.load_pem_private_key(f.read(), password=None)

        pub_der = key.public_key().public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        pub_b64 = base64.b64encode(pub_der).decode("ascii")
        h = hashlib.sha256(pub_der).hexdigest()[:32]
        ext_id = "".join(chr(ord("a") + int(c, 16)) for c in h)
        return pub_b64, ext_id
    except Exception as e:
        print(f"  [Warning] Failed to generate/load Chrome key: {e}")
        return None, None

def build(bump_part=None):
    manifest_path = os.path.join(EXT_DIR, "manifest.json")
    if bump_part:
        bump_version(manifest_path, bump_part)

    with open(manifest_path, "r", encoding="utf-8") as f:
        base_manifest = json.load(f)
    version = base_manifest.get("version", "unknown")
    base_manifest["name"] = EXT_NAME

    print(f"=== Building {EXT_NAME} v{version} (Chrome & Firefox) ===")

    # 1. Clean dist
    if os.path.exists(DIST_DIR):
        shutil.rmtree(DIST_DIR)
    os.makedirs(CHROME_DIR, exist_ok=True)
    os.makedirs(FIREFOX_DIR, exist_ok=True)

    # 3. Build Chrome Target
    copy_assets(CHROME_DIR)
    chrome_manifest = dict(base_manifest)
    # Remove gecko settings
    chrome_manifest.pop("browser_specific_settings", None)
    # Pure service_worker
    chrome_manifest["background"] = {
        "service_worker": "background.js"
    }
    pub_b64, chrome_ext_id = get_or_create_chrome_key()
    if pub_b64:
        chrome_manifest["key"] = pub_b64
    with open(os.path.join(CHROME_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(chrome_manifest, f, indent=2)
    print(f"  [Chrome] Manifest V3 generated -> dist/chrome/manifest.json (ID: {chrome_ext_id})")

    # 4. Build Firefox Target
    copy_assets(FIREFOX_DIR)
    firefox_manifest = dict(base_manifest)
    # Pure scripts event page
    firefox_manifest["background"] = {
        "scripts": ["background.js"]
    }
    # Firefox match patterns do not support port numbers or port wildcards
    import re
    cleaned_hosts = []
    for h in base_manifest.get("host_permissions", []):
        ch = re.sub(r":\d+", "", h)
        ch = re.sub(r":\*", "", ch)
        if ch not in cleaned_hosts:
            cleaned_hosts.append(ch)
    firefox_manifest["host_permissions"] = cleaned_hosts
    firefox_manifest["optional_host_permissions"] = base_manifest.get("optional_host_permissions", [])

    # Firefox does not support world: MAIN in content_scripts (uses wrappedJSObject)
    firefox_cs = []
    for cs in base_manifest.get("content_scripts", []):
        if cs.get("world") == "MAIN":
            continue
        firefox_cs.append(cs)
    firefox_manifest["content_scripts"] = firefox_cs
    with open(os.path.join(FIREFOX_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(firefox_manifest, f, indent=2)
    print("  [Firefox] Manifest V3 generated -> dist/firefox/manifest.json")

    # 5. Pack ZIP & XPI
    create_zip(CHROME_DIR, os.path.join(DIST_DIR, "brain-llm-sync-chrome.zip"))

    # 5b. Pack Chrome Web Store release (MUST NOT contain "key" field in manifest)
    chrome_store_dir = os.path.join(DIST_DIR, "chrome-store")
    copy_assets(chrome_store_dir)
    chrome_store_manifest = dict(chrome_manifest)
    chrome_store_manifest.pop("key", None)
    with open(os.path.join(chrome_store_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(chrome_store_manifest, f, indent=2)
    create_zip(chrome_store_dir, os.path.join(DIST_DIR, "brain-llm-sync-chrome-store.zip"))
    shutil.rmtree(chrome_store_dir)

    create_zip(FIREFOX_DIR, os.path.join(DIST_DIR, "brain-llm-sync-firefox.xpi"))
    create_zip(FIREFOX_DIR, os.path.join(DIST_DIR, "brain-llm-sync-firefox.zip"))

    print("\n=== Build Complete ===")
    print(f"  Chrome unpacked:     {CHROME_DIR}")
    print(f"  Firefox unpacked:    {FIREFOX_DIR}")
    print(f"  Chrome dev zip:      {os.path.join(DIST_DIR, 'brain-llm-sync-chrome.zip')}")
    print(f"  Chrome store zip:    {os.path.join(DIST_DIR, 'brain-llm-sync-chrome-store.zip')}")
    print(f"  Firefox XPI:         {os.path.join(DIST_DIR, 'brain-llm-sync-firefox.xpi')}")
    print(f"  Firefox store zip:   {os.path.join(DIST_DIR, 'brain-llm-sync-firefox.zip')}")

if __name__ == "__main__":
    import sys
    bump = None
    if "--bump" in sys.argv:
        idx = sys.argv.index("--bump")
        if idx + 1 < len(sys.argv) and sys.argv[idx + 1] in ("patch", "minor", "major"):
            bump = sys.argv[idx + 1]
        else:
            bump = "patch"
    build(bump_part=bump)
