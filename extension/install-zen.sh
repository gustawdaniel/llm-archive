#!/usr/bin/env bash
# ==============================================================================
# Brain LLM Sync - Dedykowany instalator na stałe dla Zen Browser
#
# Działanie:
# 1. Buduje najnowszą paczkę .xpi (Firefox / Gecko Manifest V3)
# 2. Instaluje XPI bezpośrednio w profilach Zen Browser (~/.zen/*/extensions/)
# 3. Konfiguruje user.js (wyłączenie wymogu podpisów XPI)
# 4. Konfiguruje Enterprise Policy (/opt/zen-browser-bin/distribution/policies.json)
#    trybem force_installed – gwarantuje, że wtyczka jest zainstalowana NA STAŁE
#    i nie znika po restarcie przeglądarki.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "🦊 Budowanie i instalacja wtyczki na stałe w Zen Browser..."

# 1. Zbuduj paczkę
python3 build.py

# 2. Uruchom dedykowaną instalację
python3 -c '
import os, glob, shutil, json, subprocess

EXT_DIR = os.path.dirname(os.path.abspath("build.py"))
XPI_SRC = os.path.join(EXT_DIR, "dist", "brain-llm-sync-firefox.xpi")
ZEN_DIR = os.path.expanduser("~/.zen")
GECKO_ID = "brain-llm-sync@gustawdaniel.com"

if not os.path.exists(XPI_SRC):
    print("❌ Brak pliku XPI:", XPI_SRC)
    exit(1)

# Znajdź profile Zen
profiles = [p for p in glob.glob(os.path.join(ZEN_DIR, "*")) if os.path.isdir(p) and (p.endswith(".default") or "default" in p.lower() or os.path.exists(os.path.join(p, "prefs.js")))]

print(f"📁 Znaleziono {len(profiles)} profili Zen:")
for prof in profiles:
    prof_name = os.path.basename(prof)
    ext_dir = os.path.join(prof, "extensions")
    os.makedirs(ext_dir, exist_ok=True)
    target_xpi = os.path.join(ext_dir, f"{GECKO_ID}.xpi")
    shutil.copy2(XPI_SRC, target_xpi)
    
    # user.js prefs
    user_js = os.path.join(prof, "user.js")
    lines = []
    if os.path.exists(user_js):
        with open(user_js, "r", encoding="utf-8") as f:
            lines = [l for l in f.readlines() if not ("xpinstall.signatures.required" in l or "extensions.autoDisableScopes" in l)]
    lines.append("user_pref(\"xpinstall.signatures.required\", false);\n")
    lines.append("user_pref(\"extensions.autoDisableScopes\", 0);\n")
    with open(user_js, "w", encoding="utf-8") as f:
        f.writelines(lines)
    print(f"  ✓ Profil {prof_name}: skopiowano XPI i skonfigurowano user.js")

# 3. Enterprise Policy
policy_path = "/opt/zen-browser-bin/distribution/policies.json"
if os.path.exists(os.path.dirname(policy_path)):
    data = {}
    if os.path.exists(policy_path):
        try:
            with open(policy_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    pol = data.setdefault("policies", {})
    ext = pol.setdefault("ExtensionSettings", {})
    ext[GECKO_ID] = {
        "installation_mode": "force_installed",
        "install_url": "file://" + os.path.abspath(XPI_SRC)
    }
    prefs = pol.setdefault("Preferences", {})
    prefs["xpinstall.signatures.required"] = { "Value": False, "Status": "default" }
    prefs["extensions.autoDisableScopes"] = { "Value": 0, "Status": "default" }
    
    temp_policy = "/tmp/zen_policies.json"
    with open(temp_policy, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    
    if os.access(os.path.dirname(policy_path), os.W_OK):
        shutil.copy2(temp_policy, policy_path)
    else:
        subprocess.run(["sudo", "cp", temp_policy, policy_path], check=False)
    print(f"  ✓ Skonfigurowano Enterprise Policy: {policy_path} (force_installed)")

print("\n🎉 Sukces! Wtyczka jest zainstalowana na stałe w Zen Browser.")
'

echo ""
echo "========================================================================"
echo "⚠️  ABY ZEN PRZEŁADOWAŁ WTYCZKĘ DO PAMIĘCI RAM:"
echo "   1. Zrestartuj Zen Browser (Ctrl+Q -> otwórz ponownie)"
echo "      LUB"
echo "   2. W Zen wejdź w: about:addons i upewnij się, że wtyczka jest aktywna"
echo "========================================================================"
