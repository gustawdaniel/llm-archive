import os
import json
from pathlib import Path

def test_web_app_structure():
    base_dir = Path(__file__).parent.parent / "web"
    assert base_dir.exists()
    
    pkg_json_path = base_dir / "package.json"
    assert pkg_json_path.exists()
    
    with open(pkg_json_path) as f:
        pkg = json.load(f)
    assert pkg["name"] == "brain-llm-web"
    assert "devDependencies" in pkg
    assert "svelte" in pkg["devDependencies"]
    assert "@sveltejs/kit" in pkg["devDependencies"]
    
    # Check routes
    routes_dir = base_dir / "src" / "routes"
    assert (routes_dir / "+page.svelte").exists()
    assert (routes_dir / "conversations" / "+page.svelte").exists()
    assert (routes_dir / "conversations" / "[id]" / "+page.svelte").exists()
    assert (routes_dir / "stats" / "+page.svelte").exists()
    
    # Check components
    comp_dir = base_dir / "src" / "lib" / "components"
    assert (comp_dir / "Navbar.svelte").exists()
    assert (comp_dir / "MarkdownViewer.svelte").exists()
    assert (comp_dir / "PlatformBadge.svelte").exists()
    
    # Check build output
    build_dir = base_dir / "build"
    assert build_dir.exists(), "Web app must be built with pnpm run build"
    assert (build_dir / "index.js").exists()
