import os
import json
import zipfile
import subprocess
import pytest

EXTENSION_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "extension")

def test_extension_build_and_manifests():
    build_script = os.path.join(EXTENSION_DIR, "build.py")
    res = subprocess.run(["python3", build_script], capture_output=True, text=True)
    assert res.returncode == 0, f"Build failed: {res.stderr}"

    # Verify Chrome output
    chrome_manifest_path = os.path.join(EXTENSION_DIR, "dist", "chrome", "manifest.json")
    assert os.path.exists(chrome_manifest_path)
    with open(chrome_manifest_path, "r", encoding="utf-8") as f:
        chrome_manifest = json.load(f)
    assert chrome_manifest["manifest_version"] == 3
    assert "service_worker" in chrome_manifest["background"]
    assert "scripts" not in chrome_manifest["background"]
    assert "browser_specific_settings" not in chrome_manifest

    # Verify Firefox output
    firefox_manifest_path = os.path.join(EXTENSION_DIR, "dist", "firefox", "manifest.json")
    assert os.path.exists(firefox_manifest_path)
    with open(firefox_manifest_path, "r", encoding="utf-8") as f:
        firefox_manifest = json.load(f)
    assert firefox_manifest["manifest_version"] == 3
    assert "scripts" in firefox_manifest["background"]
    assert "service_worker" not in firefox_manifest["background"]
    assert "browser_specific_settings" in firefox_manifest
    assert firefox_manifest["browser_specific_settings"]["gecko"]["id"] == "brain-llm-sync@brain-os.local"

    # Verify packages
    chrome_zip = os.path.join(EXTENSION_DIR, "dist", "brain-llm-sync-chrome.zip")
    firefox_xpi = os.path.join(EXTENSION_DIR, "dist", "brain-llm-sync-firefox.xpi")
    assert os.path.exists(chrome_zip)
    assert os.path.exists(firefox_xpi)

    with zipfile.ZipFile(chrome_zip, "r") as zf:
        namelist = zf.namelist()
        assert "manifest.json" in namelist
        assert "background.js" in namelist
        assert "content/chatgpt.js" in namelist
        assert "content/claude.js" in namelist
        assert "content/gemini.js" in namelist
        assert "icons/icon-128.png" in namelist

    with zipfile.ZipFile(firefox_xpi, "r") as zf:
        namelist = zf.namelist()
        assert "manifest.json" in namelist
        assert "background.js" in namelist
        assert "content/chatgpt.js" in namelist
        assert "content/gemini.js" in namelist
        assert "icons/icon-128.png" in namelist


def test_deepseek_exporter_build():
    deepseek_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "deepseek-exporter")
    build_script = os.path.join(deepseek_dir, "build.py")
    res = subprocess.run(["python3", build_script], capture_output=True, text=True)
    assert res.returncode == 0, f"DeepSeek build failed: {res.stderr}"

    # Verify Chrome manifest
    chrome_manifest_path = os.path.join(deepseek_dir, "dist", "chrome", "manifest.json")
    assert os.path.exists(chrome_manifest_path)
    with open(chrome_manifest_path, "r", encoding="utf-8") as f:
        chrome_manifest = json.load(f)
    assert "service_worker" in chrome_manifest["background"]
    assert "browser_specific_settings" not in chrome_manifest

    # Verify Firefox manifest & packages
    firefox_manifest_path = os.path.join(deepseek_dir, "dist", "firefox", "manifest.json")
    assert os.path.exists(firefox_manifest_path)
    with open(firefox_manifest_path, "r", encoding="utf-8") as f:
        firefox_manifest = json.load(f)
    assert "scripts" in firefox_manifest["background"]
    assert "browser_specific_settings" in firefox_manifest

    assert os.path.exists(os.path.join(deepseek_dir, "dist", "deepseek-exporter-chrome.zip"))
    assert os.path.exists(os.path.join(deepseek_dir, "dist", "deepseek-exporter-firefox.xpi"))


def test_gemini_chat_exporter_build():
    gemini_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "gemini-chat-exporter")
    build_script = os.path.join(gemini_dir, "build.py")
    res = subprocess.run(["python3", build_script], capture_output=True, text=True)
    assert res.returncode == 0, f"Gemini build failed: {res.stderr}"

    chrome_manifest_path = os.path.join(gemini_dir, "dist", "chrome", "manifest.json")
    assert os.path.exists(chrome_manifest_path)
    with open(chrome_manifest_path, "r", encoding="utf-8") as f:
        chrome_manifest = json.load(f)
    assert "browser_specific_settings" not in chrome_manifest

    firefox_manifest_path = os.path.join(gemini_dir, "dist", "firefox", "manifest.json")
    assert os.path.exists(firefox_manifest_path)
    with open(firefox_manifest_path, "r", encoding="utf-8") as f:
        firefox_manifest = json.load(f)
    assert "browser_specific_settings" in firefox_manifest

    assert os.path.exists(os.path.join(gemini_dir, "dist", "gemini-chat-exporter-chrome.zip"))
    assert os.path.exists(os.path.join(gemini_dir, "dist", "gemini-chat-exporter-firefox.xpi"))
