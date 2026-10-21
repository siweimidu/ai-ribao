

def s03_gradient() -> str:
    """Soft gradient hero with the stats floating in glass tiles."""
    css = """
    body{background:linear-gradient(135deg,#4f46e5 0%,#7c3aed 45%,#db2777 100%);color:#fff;padding:60px 64px;position:relative;overflow:hidden}
    body::after{content:"";position:absolute;width:760px;height:760px;border-radius:50%;background:radial-gradient(circle,rgba(255,255,255,.22),transparent 62%);right:-240px;top:-300px}
    .nm{font:700 54px/1.1 -apple-system,"PingFang SC",sans-serif;letter-spacing:-1.4px;text-shadow:0 2px 20px rgba(0,0,0,.16)}
    .desc{font:400 19px/1.6 -apple-system,sans-serif;opacity:.9;margin:20px 0 0;max-width:760px}
    .tiles{display:flex;gap:16px;margin-top:44px;position:relative;z-index:2}
    .tile{background:rgba(255,255,255,.16);border:1px solid rgba(255,255,255,.28);border-radius:14px;padding:16px 26px;backdrop-filter:blur(8px)}
    .tile b{display:block;font:700 30px/1 sans-serif;letter-spacing:-.8px}
    .tile i{display:block;font:400 12px/1 sans-serif;opacity:.78;font-style:normal;margin-top:7px;letter-spacing:.08em}
    """
    body = f"""
    <div class="nm">{H.escape(REPO["full_name"])}</div>
    <p class="desc">{H.escape(REPO["description"])}</p>
    <div class="tiles">
      <div class="tile"><b>{k(REPO["stars"])}</b><i>STARS</i></div>
      <div class="tile"><b>{k(REPO["forks"])}</b><i>FORKS</i></div>
      <div class="tile"><b>{REPO["language"]}</b><i>LANGUAGE</i></div>
      <div class="tile"><b>{REPO["license"]}</b><i>LICENSE</i></div>
    </div>
    """
    return page(css, body)


def s04_blueprint() -> str:
    """Technical drawing: hairline grid, labels with leader rules."""
    css = """
    body{background:#0a2a43;color:#cfe8f7;padding:52px 60px;
         background-image:linear-gradient(rgba(120,190,230,.10) 1px,transparent 1px),linear-gradient(90deg,rgba(120,190,230,.10) 1px,transparent 1px);
         background-size:40px 40px}
    .tag{display:inline-block;font:600 11px/1 monospace;letter-spacing:.2em;border:1px solid #4a90c2;color:#89c4e8;padding:5px 10px;margin-bottom:18px}
    h1{font:600 44px/1.1 ui-monospace,Consolas,monospace;letter-spacing:-.6px;color:#fff}
    .desc{font:400 17px/1.6 ui-monospace,monospace;color:#9dc4dd;margin-top:14px;max-width:840px}
    .grid2{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:#2c5c80;margin-top:40px;border:1px solid #2c5c80}
    .cell{background:#0a2a43;padding:16px 18px}
    .cell b{display:block;font:600 26px/1 ui-monospace,monospace;color:#fff}
    .cell i{display:block;font:400 11px/1 ui-monospace,monospace;color:#6ea8cc;font-style:normal;margin-top:8px;letter-spacing:.12em}
    """
    body = f"""
    <div class="tag">REPOSITORY / {H.escape(REPO["language"]).upper()}</div>
    <h1>{H.escape(REPO["full_name"])}</h1>
    <p class="desc">{H.escape(REPO["description"])}</p>
    <div class="grid2">
      <div class="cell"><b>{k(REPO["stars"])}</b><i>STARS</i></div>
      <div class="cell"><b>{k(REPO["forks"])}</b><i>FORKS</i></div>
      <div class="cell"><b>{k(REPO["issues"])}</b><i>ISSUES</i></div>
      <div class="cell"><b>{REPO["pushed"][5:]}</b><i>LAST PUSH</i></div>
    </div>
    """
    return page(css, body)