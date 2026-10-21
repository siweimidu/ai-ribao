

def s01_terminal() -> str:
    """Terminal card: monospace, dark, looks like a session tailing a build."""
    css = """
    body{background:#0b0f14;color:#c9d1d9;font-family:"JetBrains Mono",Consolas,monospace;padding:54px 64px}
    .hd{color:#58a6ff;font-size:22px;letter-spacing:-.2px}
    .hd::before{content:"$ ";color:#3fb950}
    .desc{color:#8b949e;font-size:19px;line-height:1.65;margin:20px 0 34px;max-width:900px}
    .row{display:flex;gap:38px;font-size:17px;color:#8b949e}
    .row b{color:#e6edf3;font-weight:600}
    .cursor{display:inline-block;width:11px;height:22px;background:#3fb950;vertical-align:-3px;margin-left:4px;animation:none}
    .lic{position:absolute;right:64px;top:54px;color:#3fb950;font-size:15px;border:1px solid #238636;border-radius:5px;padding:5px 12px}
    """
    body = f"""
    <div class="lic">{H.escape(REPO["license"])}</div>
    <div class="hd">{H.escape(REPO["full_name"])}</div>
    <p class="desc">{H.escape(REPO["description"])}</p>
    <div class="row">
      <span><b>{k(REPO["stars"])}</b> stars</span>
      <span><b>{k(REPO["forks"])}</b> forks</span>
      <span><b>{REPO["language"]}</b></span>
      <span>updated {REPO["pushed"]}</span>
    </div>
    <div class="row" style="margin-top:18px"><span><b>+</b> {H.escape(", ".join(REPO["topics"]))}<span class="cursor"></span></span></div>
    """
    return page(css, body)


def s02_magazine() -> str:
    """Editorial: a serif headline, the numbers as a ruled table."""
    css = """
    body{background:#faf8f5;color:#1a1a1a;padding:58px 68px;position:relative}
    .kicker{font:600 12px/1 sans-serif;letter-spacing:.22em;text-transform:uppercase;color:#b5532f;margin-bottom:22px}
    h1{font:700 62px/1.06 Georgia,"Songti SC",serif;letter-spacing:-1.6px}
    h1 span{color:#8a8a8a;font-weight:400}
    .desc{font:400 20px/1.6 Georgia,serif;color:#3d3d3d;margin:24px 0 0;max-width:820px}
    .rule{height:1px;background:#1a1a1a;margin:34px 0 0;opacity:.18}
    .stats{display:flex;margin-top:22px;font-family:Georgia,serif}
    .stats div{padding-right:44px;margin-right:44px;border-right:1px solid #d8d2c8}
    .stats div:last-child{border:0}
    .stats b{display:block;font-size:34px;letter-spacing:-1px}
    .stats i{display:block;font:400 13px/1 sans-serif;color:#8a8a8a;font-style:normal;margin-top:6px;letter-spacing:.06em}
    """
    body = f"""
    <div class="kicker">Open source · {H.escape(REPO["language"])}</div>
    <h1>{H.escape(REPO["name"])}<span> / {H.escape(REPO["owner"])}</span></h1>
    <p class="desc">{H.escape(REPO["description"])}</p>
    <div class="rule"></div>
    <div class="stats">
      <div><b>{k(REPO["stars"])}</b><i>STARS</i></div>
      <div><b>{k(REPO["forks"])}</b><i>FORKS</i></div>
      <div><b>{k(REPO["issues"])}</b><i>ISSUES</i></div>
      <div><b>{REPO["created"][:4]}</b><i>SINCE</i></div>
    </div>
    """
    return page(css, body)