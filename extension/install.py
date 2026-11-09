#!/usr/bin/env python3
"""
Automated Browser Extension Installer for Brain LLM Sync.
Installs and registers the extension across all installed web browsers:
  - Mozilla Zen Browser (Gecko)
  - Mozilla Firefox (Gecko)
  - Google Chrome (Chromium)
  - Chromium (Chromium)
  - Microsoft Edge (Chromium, if profile exists)
  - Google Chrome for Testing (if profile exists)

Also verifies and starts the background logger systemd user service.
"""

import os
import sys
import glob
import json
import shutil
import subprocess

EXT_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(EXT_DIR, "dist")
CHROME_DIST = os.path.join(DIST_DIR, "chrome")
FIREFOX_XPI = os.path.join(DIST_DIR, "brain-llm-sync-firefox.xpi")
HOME = os.path.expanduser("~")

GECKO_ID = "brain-llm-sync@gustawdaniel.com"

def run_cmd(cmd, check=False, sudo=False):
    if sudo and os.geteuid() != 0:
        cmd = ["sudo"] + cmd
    res = subprocess.run(cmd, capture_output=True, text=True)
    if check and res.returncode != 0:
        raise RuntimeError(f"Command failed ({res.returncode}): {' '.join(cmd)}\n{res.stderr}")
    return res

def can_sudo():
    res = subprocess.run(["sudo", "-n", "true"], capture_output=True)
    return res.returncode == 0

def build_extension(bump_part="patch"):
    print(f"📦 [1/5] Building & bumping Extension ({bump_part}) for Chromium & Firefox...")
    import build
    if bump_part:
        build.build(bump_part=bump_part)
    else:
        build.build()
    pub_b64, chrome_id = build.get_or_create_chrome_key()
    print(f"  ✓ Build complete. Chrome Extension ID: {chrome_id}")
    return chrome_id

def ensure_user_pref(user_js_path, key, value_repr):
    lines = []
    if os.path.exists(user_js_path):
        with open(user_js_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    pref_str = f'user_pref("{key}", {value_repr});\n'
    updated = False
    new_lines = []
    for line in lines:
        if line.strip().startswith(f'user_pref("{key}"'):
            new_lines.append(pref_str)
            updated = True
        else:
            new_lines.append(line)
    if not updated:
        new_lines.append(pref_str)
    with open(user_js_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

def update_firefox_policy(policy_path, xpi_path, use_sudo=False):
    if not os.path.exists(os.path.dirname(policy_path)):
        return False
    try:
        py_code = f"""
import json, os
path = {repr(policy_path)}
os.makedirs(os.path.dirname(path), exist_ok=True)
data = {{}}
if os.path.exists(path):
    with open(path, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
        except Exception:
            data = {{}}
pol = data.setdefault('policies', {{}})
ext = pol.setdefault('ExtensionSettings', {{}})
ext[{repr(GECKO_ID)}] = {{
    'installation_mode': 'force_installed',
    'install_url': 'file://' + os.path.abspath({repr(xpi_path)})
}}
prefs = pol.setdefault('Preferences', {{}})
prefs['xpinstall.signatures.required'] = {{ 'Value': False, 'Status': 'default' }}
prefs['extensions.autoDisableScopes'] = {{ 'Value': 0, 'Status': 'default' }}
with open(path, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2)
    f.write('\\n')
"""
        cmd = [sys.executable, "-c", py_code]
        run_cmd(cmd, check=True, sudo=use_sudo)
        return True
    except Exception as e:
        print(f"    [Warning] Could not update policy {policy_path}: {e}")
        return False

def configure_gecko_browser(name, root_dir, enterprise_policy=None):
    if not os.path.isdir(root_dir):
        return False

    print(f"🦊 [Gecko] Configuring {name} ({root_dir})...")
    profiles = []
    for item in os.listdir(root_dir):
        p = os.path.join(root_dir, item)
        if os.path.isdir(p) and (item.endswith(".default") or "default" in item.lower() or os.path.exists(os.path.join(p, "prefs.js"))):
            profiles.append(p)

    for prof in profiles:
        ext_dir = os.path.join(prof, "extensions")
        os.makedirs(ext_dir, exist_ok=True)
        dest_xpi = os.path.join(ext_dir, f"{GECKO_ID}.xpi")
        shutil.copy2(FIREFOX_XPI, dest_xpi)
        
        user_js = os.path.join(prof, "user.js")
        ensure_user_pref(user_js, "xpinstall.signatures.required", "false")
        ensure_user_pref(user_js, "extensions.autoDisableScopes", "0")
        print(f"  ✓ Installed XPI & user.js in profile: {os.path.basename(prof)}")

    if enterprise_policy:
        sudo_needed = not os.access(os.path.dirname(enterprise_policy), os.W_OK)
        if update_firefox_policy(enterprise_policy, FIREFOX_XPI, use_sudo=sudo_needed):
            print(f"  ✓ Configured enterprise policy: {enterprise_policy}")

    return True

def configure_chromium_browser(name, user_config_dir, chrome_id, sys_ext_dir=None, policy_dir=None):
    if not os.path.isdir(user_config_dir):
        return False

    print(f"🌐 [Chromium] Configuring {name} ({user_config_dir})...")
    ext_dir = os.path.join(user_config_dir, "External Extensions")
    os.makedirs(ext_dir, exist_ok=True)

    json_file = os.path.join(ext_dir, f"{chrome_id}.json")
    content = {
        "external_path": CHROME_DIST
    }
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(content, f, indent=2)
        f.write("\n")
    print(f"  ✓ Created user external extension: {json_file}")

    sudo_ok = can_sudo()
    if sys_ext_dir and sudo_ok:
        try:
            run_cmd(["mkdir", "-p", sys_ext_dir], check=True, sudo=True)
            sys_file = os.path.join(sys_ext_dir, f"{chrome_id}.json")
            tmp_file = f"/tmp/{chrome_id}.json"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(content, f, indent=2)
            run_cmd(["cp", tmp_file, sys_file], check=True, sudo=True)
            print(f"  ✓ Created system external extension: {sys_file}")
        except Exception as e:
            print(f"    [Notice] System external extension skipped: {e}")

    if policy_dir and sudo_ok:
        try:
            run_cmd(["mkdir", "-p", policy_dir], check=True, sudo=True)
            pol_file = os.path.join(policy_dir, "brain_extension.json")
            policy_data = {
                "ExtensionInstallAllowlist": [chrome_id]
            }
            tmp_pol = "/tmp/brain_extension.json"
            with open(tmp_pol, "w", encoding="utf-8") as f:
                json.dump(policy_data, f, indent=2)
            run_cmd(["cp", tmp_pol, pol_file], check=True, sudo=True)
            print(f"  ✓ Created managed policy: {pol_file}")
        except Exception as e:
            print(f"    [Notice] Managed policy skipped: {e}")

    return True

def ensure_logger_service():
    print("🔌 [4/5] Checking Background Logger Service (port 3040)...")
    if sys.platform != "darwin":
        service_name = "brain-extension-logger.service"
        # Ensure systemd user service is running
        res = subprocess.run(["systemctl", "--user", "is-active", service_name], capture_output=True, text=True)
        if res.stdout.strip() != "active":
            print(f"  Starting and enabling {service_name}...")
            subprocess.run(["systemctl", "--user", "enable", "--now", service_name], check=False)
    else:
        plist_path = os.path.expanduser("~/Library/LaunchAgents/com.brain.llm-extension-logger.plist")
        if os.path.exists(plist_path):
            subprocess.run(["launchctl", "load", "-w", plist_path], capture_output=True)

    # Check health
    import urllib.request
    try:
        req = urllib.request.urlopen("http://127.0.0.1:3040/health", timeout=3)
        status = json.loads(req.read().decode("utf-8"))
        print(f"  ✓ Logger server healthy on port 3040 (Database: {status.get('db_connected', 'unknown')})")
    except Exception as e:
        print(f"  ⚠ Logger service warning: {e}")

def print_summary(chrome_id):
    print("\n" + "="*70)
    print("🎉 BRAIN LLM SYNC EXTENSION INSTALLED SUCCESSFULLY!")
    print("="*70)
    print("\n🔗 SZYBKIE LINKI DIAGNOSTYCZNE I ZARZĄDZANIE (wklej w pasek przeglądarki):")
    print("  • Firefox & Zen Browser:")
    print("    - about:debugging#/runtime/this-firefox  (Wczytaj/odśwież dodatek tymczasowy)")
    print("    - about:addons                          (Zarządzanie dodatkami i uprawnieniami)")
    print("    - Ścieżka XPI: apps/llm-archive/extension/dist/brain-llm-sync-firefox.xpi")
    print("\n  • Chrome / Chromium / Brave / Edge:")
    print("    - chrome://extensions                   (Menedżer rozszerzeń)")
    print("    - ID Rozszerzenia:                      " + chrome_id)
    print("    - Włącz 'Tryb programisty' (Developer mode) w prawym górnym rogu.")
    print("    - Załaduj rozpakowane z: apps/llm-archive/extension/dist/chrome")
    print("\n🖥️ DIAGNOSTYKA I LOGI W TERMINALU:")
    print("  • Podgląd logów na żywo: brain ext logs")
    print("  • Status usługi i sync:   brain ext status")
    print("  • Test endpointu:         curl http://127.0.0.1:3040/health")
    print("="*70 + "\n")

def main():
    bump = "patch"
    if "--no-bump" in sys.argv:
        bump = None
    elif "--bump" in sys.argv:
        idx = sys.argv.index("--bump")
        if idx + 1 < len(sys.argv) and sys.argv[idx + 1] in ("patch", "minor", "major"):
            bump = sys.argv[idx + 1]

    chrome_id = build_extension(bump_part=bump)

    is_mac = sys.platform == "darwin"

    print("\n🌐 [2/5] Configuring Gecko Browsers (Zen & Firefox)...")
    # 1. Zen Browser
    zen_root = os.path.join(HOME, "Library", "Application Support", "zen", "Profiles") if is_mac else os.path.join(HOME, ".zen")
    configure_gecko_browser(
        name="Zen Browser",
        root_dir=zen_root,
        enterprise_policy="/opt/zen-browser-bin/distribution/policies.json" if os.path.exists("/opt/zen-browser-bin/distribution") else None
    )

    # 2. Mozilla Firefox
    firefox_root = os.path.join(HOME, "Library", "Application Support", "Firefox", "Profiles") if is_mac else os.path.join(HOME, ".mozilla", "firefox")
    configure_gecko_browser(
        name="Mozilla Firefox",
        root_dir=firefox_root,
        enterprise_policy="/etc/firefox/policies/policies.json" if not is_mac else None
    )

    print("\n🌐 [3/5] Configuring Chromium Browsers (Chrome, Chromium, Edge)...")
    # 3. Google Chrome
    chrome_root = os.path.join(HOME, "Library", "Application Support", "Google", "Chrome") if is_mac else os.path.join(HOME, ".config", "google-chrome")
    configure_chromium_browser(
        name="Google Chrome",
        user_config_dir=chrome_root,
        chrome_id=chrome_id,
        sys_ext_dir=None if is_mac else "/usr/share/google-chrome/extensions",
        policy_dir=None if is_mac else "/etc/opt/chrome/policies/managed"
    )

    # 4. Chromium
    chromium_root = os.path.join(HOME, "Library", "Application Support", "Chromium") if is_mac else os.path.join(HOME, ".config", "chromium")
    configure_chromium_browser(
        name="Chromium",
        user_config_dir=chromium_root,
        chrome_id=chrome_id,
        sys_ext_dir=None if is_mac else "/usr/share/chromium/extensions",
        policy_dir=None if is_mac else "/etc/chromium/policies/managed"
    )

    # 5. Microsoft Edge
    edge_root = os.path.join(HOME, "Library", "Application Support", "Microsoft Edge") if is_mac else os.path.join(HOME, ".config", "microsoft-edge")
    configure_chromium_browser(
        name="Microsoft Edge",
        user_config_dir=edge_root,
        chrome_id=chrome_id
    )

    # 6. Google Chrome for Testing
    cft_root = os.path.join(HOME, "Library", "Application Support", "Google Chrome for Testing") if is_mac else os.path.join(HOME, ".config", "google-chrome-for-testing")
    configure_chromium_browser(
        name="Google Chrome for Testing",
        user_config_dir=cft_root,
        chrome_id=chrome_id
    )

    ensure_logger_service()
    print_summary(chrome_id)

if __name__ == "__main__":
    main()
