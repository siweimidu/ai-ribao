/* ============================================================================
   motion.js — 侧栏交互、日历、搜索、目录高亮
   ----------------------------------------------------------------------------
   原则（frontend-design）：「单次编排的一个瞬间胜过零散效果」。
   所以这里没有滚动淡入、没有卡片 hover 抬升、没有拖尾光标。
   留下的动效都**回应人的动作**：点击、展开、切换、阅读位置变化。

   弹簧与帧率无关的趋近仍沿用 motion-web 的手感规范：
   欠阻尼弹簧负责「Q 弹」，1-exp(-k·dt) 保证 30/60/120fps 手感一致。
   ========================================================================= */

(() => {
  'use strict';

  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);
  const approach = (cur, target, k, dt) => cur + (target - cur) * (1 - Math.exp(-k * dt));

  /* ============================================================ 弹簧 */
  class Spring {
    constructor({ stiffness = 90, damping = 0.88 } = {}) {
      this.k = stiffness; this.damping = damping;
      this.value = 0; this.target = 0; this.velocity = 0;
    }
    step(dt) {
      // 切标签页回来时 dt 可能是几秒，不钳制会让弹簧炸开
      const h = Math.min(dt, 1 / 30);
      this.velocity += (this.target - this.value) * this.k * h;
      this.velocity *= this.damping;
      this.value += this.velocity * h;
      return this.value;
    }
    get settled() {
      return Math.abs(this.velocity) < 0.001 && Math.abs(this.target - this.value) < 0.001;
    }
  }

  /* ============================================================================
     一、左侧栏：移动端抽屉
     ========================================================================= */
  const rail = document.querySelector('.rail');
  const railToggle = document.querySelector('.rail__toggle');
  if (rail && railToggle) {
    rail.dataset.open = 'false';
    railToggle.setAttribute('aria-expanded', 'false');
    railToggle.addEventListener('click', () => {
      const open = rail.dataset.open === 'true';
      rail.dataset.open = open ? 'false' : 'true';
      railToggle.setAttribute('aria-expanded', open ? 'false' : 'true');
    });
  }

  /* ============================================================================
     二、日历
     ----------------------------------------------------------------------------
     数据来自内联 JSON（生成期写入）：哪些日期有归档、当前期是哪天、今天哪天。
     只渲染当前显示的月份，左右箭头切月。
     ========================================================================= */
  const cal = document.querySelector('.cal');
  if (cal) {
    const raw = document.getElementById('calendar-data');
    let data = { dates: [], current: null, today: null };
    try {
      data = JSON.parse(raw?.textContent || '{}');
    } catch { /* 数据坏了就退化成空日历，不要整页报错 */ }

    const have = new Set(data.dates || []);
    const today = data.today;
    const current = data.current;
    const grid = cal.querySelector('.cal__grid');
    const label = cal.querySelector('.cal__month');
    const prev = cal.querySelector('[data-nav="prev"]');
    const next = cal.querySelector('[data-nav="next"]');

    // 从当前期所在月份开始，没有当前期就退到有归档的最近一个月
    const anchor = (current || data.dates?.[data.dates.length - 1] || today || '');
    let [yy, mm] = (anchor.split('-').map(Number) || []);
    if (!yy || !mm) { const d = new Date(); yy = d.getFullYear(); mm = d.getMonth() + 1; }
    yy = Number(yy); mm = Number(mm);

    const pad = (n) => String(n).padStart(2, '0');
    const iso = (y, m, d) => `${y}-${pad(m)}-${pad(d)}`;
    const DOW = ['日', '一', '二', '三', '四', '五', '六'];

    const render = () => {
      label.textContent = `${yy} 年 ${mm} 月`;
      // 清掉日期格但保留星期表头
      grid.querySelectorAll('.cal__day').forEach((el) => el.remove());

      const first = new Date(yy, mm - 1, 1);
      const days = new Date(yy, mm, 0).getDate();
      const lead = first.getDay();      // 周日 = 0
      for (let i = 0; i < lead; i++) {
        const pad_ = document.createElement('span');
        pad_.className = 'cal__day';
        pad_.setAttribute('aria-hidden', 'true');
        grid.appendChild(pad_);
      }
      for (let d = 1; d <= days; d++) {
        const key = iso(yy, mm, d);
        const has = have.has(key);
        const el = document.createElement(has ? 'a' : 'span');
        el.className = 'cal__day';
        el.textContent = String(d);
        if (has) {
          el.href = `${key}.html`;
          el.dataset.has = 'true';
          el.title = `${key} 的日报`;
          if (key === current) el.setAttribute('aria-current', 'page');
        } else {
          el.setAttribute('aria-disabled', 'true');
        }
        if (key === current) el.dataset.current = 'true';
        if (key === today) {
          el.dataset.today = 'true';
          el.title = has ? `${key}（今天）` : `${key}（今天，尚无日报）`;
          if (!has) el.dataset.has = 'false';
        }
        grid.appendChild(el);
      }

      // 上下界：没有更早/更晚的归档就禁用箭头，而不是让人无限翻空月份
      const sorted = [...have].sort();
      const earliest = sorted[0] || '';
      const latest = sorted[sorted.length - 1] || '';
      const thisMonth = `${yy}-${pad(mm)}`;
      prev.disabled = !earliest || thisMonth <= earliest.slice(0, 7);
      next.disabled = !latest || thisMonth >= latest.slice(0, 7);
    };

    const shift = (delta) => {
      mm += delta;
      if (mm < 1) { mm = 12; yy -= 1; }
      if (mm > 12) { mm = 1; yy += 1; }
      render();
    };

    prev?.addEventListener('click', () => shift(-1));
    next?.addEventListener('click', () => shift(1));
    render();
  }

  /* ============================================================================
     三、搜索往期
     ----------------------------------------------------------------------------
     索引是生成期写入的 JSON（每期的事件标题 + 源名），不请求后端。
     匹配用简单的分词子串，中文按**字**切，因为中文没有空格可切。
     ========================================================================= */
  const dialog = document.getElementById('search-dialog');
  const openers = document.querySelectorAll('[data-open-search]');
  if (dialog && openers.length) {
    const input = dialog.querySelector('input[type="search"]');
    const list = dialog.querySelector('.search__results');
    let index = [];
    try {
      index = JSON.parse(document.getElementById('search-index')?.textContent || '[]');
    } catch { index = []; }

    const flatten = () => index.flatMap((issue) =>
      (issue.items || []).map((it) => ({ date: issue.date, title: it.t, source: it.s || '' }))
    );
    let rows = [];

    const renderResults = (query) => {
      const q = query.trim().toLowerCase();
      list.innerHTML = '';
      if (!q) {
        const hint = document.createElement('li');
        hint.className = 'search__empty';
        hint.textContent = index.length
          ? `共 ${index.length} 期，输入关键词开始搜索`
          : '还没有可搜索的往期内容';
        list.appendChild(hint);
        return;
      }
      // 中文按字切、拉丁按词切：`gemini 4` 要能命中 `Gemini 4 Argon`
      const tokens = q.match(/[a-z0-9]+|[\u4e00-\u9fff]/g) || [q];
      const hits = rows
        .map((r) => {
          const hay = (r.title + ' ' + r.source).toLowerCase();
          const score = tokens.reduce((n, t) => n + (hay.includes(t) ? 1 : 0), 0);
          return { r, score };
        })
        .filter((x) => x.score === tokens.length)
        .slice(0, 60);

      if (!hits.length) {
        const none = document.createElement('li');
        none.className = 'search__empty';
        none.textContent = `没有匹配「${query}」的内容`;
        list.appendChild(none);
        return;
      }
      for (const { r } of hits) {
        const li = document.createElement('li');
        const a = document.createElement('a');
        a.href = `${r.date}.html`;
        const b = document.createElement('b');
        b.textContent = r.title;
        const small = document.createElement('small');
        small.textContent = `${r.date}${r.source ? '　' + r.source : ''}`;
        a.append(b, small);
        li.appendChild(a);
        list.appendChild(li);
      }
    };

    const open = () => {
      if (!rows.length) rows = flatten();
      if (typeof dialog.showModal === 'function') dialog.showModal();
      else dialog.setAttribute('open', '');
      input.value = '';
      renderResults('');
      window.setTimeout(() => input.focus(), 20);
    };

    const close = () => {
      if (typeof dialog.close === 'function') dialog.close();
      else dialog.removeAttribute('open');
    };

    openers.forEach((btn) => btn.addEventListener('click', open));
    dialog.addEventListener('click', (e) => { if (e.target === dialog) close(); });
    dialog.addEventListener('close', () => {
      const opener = document.querySelector('[data-open-search]');
      if (opener && document.activeElement === document.body) opener.focus();
    });

    // Esc must close even while the input has focus. `<dialog>` closes itself on Esc only
    // when the event is not consumed by a focused control, and a search field focuses
    // itself on open -- so in practice Esc did nothing and the modal blocked the page.
    // This shipped and the interaction test caught it.
    dialog.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        close();
      }
    });

    let debounce = 0;
    input.addEventListener('input', () => {
      window.clearTimeout(debounce);
      debounce = window.setTimeout(() => renderResults(input.value), 90);
    });

    // Ctrl/⌘+K 打开；Esc 由 <dialog> 原生处理
    window.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        open();
      }
    });
  }

  /* ============================================================================
     四、主题
     ----------------------------------------------------------------------------
     四档（自动 / 默认 / 亮色 / 暗色），与 juya 一致。
     存 localStorage —— 这是读者本机的偏好，不是内容。
     ========================================================================= */
  const themeRoot = document.documentElement;
  const THEME_KEY = 'aidaily-theme';
  const themeButtons = document.querySelectorAll('[data-theme-choice]');
  if (themeButtons.length) {
    const apply = (choice) => {
      if (choice === 'auto') themeRoot.removeAttribute('data-theme');
      else themeRoot.setAttribute('data-theme', choice);
      themeButtons.forEach((b) => {
        b.setAttribute('aria-checked', b.dataset.themeChoice === choice ? 'true' : 'false');
      });
      const summary = document.querySelector('[data-theme-summary]');
      if (summary) {
        const LABEL = {
          auto: '自动', default: '默认', light: '亮色', dark: '暗色',
          'claude-light': 'Claude 亮色', 'claude-dark': 'Claude 暗色',
        };
        summary.textContent = LABEL[choice] || '自动';
      }
    };

    let saved = 'auto';
    try { saved = window.localStorage.getItem(THEME_KEY) || 'auto'; } catch { /* 隐私模式 */ }
    apply(saved);

    themeButtons.forEach((btn) => {
      btn.addEventListener('click', () => {
        const choice = btn.dataset.themeChoice;
        apply(choice);
        try { window.localStorage.setItem(THEME_KEY, choice); } catch { /* 忽略 */ }
      });
    });
  }

  /* ============================================================================
     五、右侧目录：点击跳转 + 滚动高亮

     两个行为，之前都坏着：

     **点击不跳转**：目录项是锚点 `<a href="#...">`，但 `scroll-behavior: smooth`
     只对用户手势生效于部分浏览器，而页面用 `preventDefault` 之外的方式介入时会失效。
     现在显式处理：写入历史、滚动到目标、并把高亮立刻移过去。

     **高亮不动**：目录里既有章节也有条目，而章节**包含**自己的条目。
     按文档顺序取"第一个可见的"，章节永远先命中，条目一次都轮不到 ——
     点击跳到某一条，高亮却停在章节上。
     改成取**离视口顶部最近**的那个，两者公平竞争。

     用 rAF 节流的 scroll 处理而不是 IntersectionObserver：观察器只报告"是否相交"，
     而这里需要的正是"哪个最近"，那是个几何问题，观察器算不了。
     ========================================================================= */
  const tocLinks = [...document.querySelectorAll('.toc__nav a')];
  const tocTargets = tocLinks
    .map((a) => ({ a, el: document.getElementById(decodeURIComponent(a.hash.slice(1))) }))
    .filter((x) => x.el);

  if (tocTargets.length) {
    const setCurrent = (id) => {
      tocLinks.forEach((a) => {
        if (a.hash.slice(1) === id) a.setAttribute('aria-current', 'true');
        else a.removeAttribute('aria-current');
      });
    };

    // The reading line: a target is "current" when its top has passed this offset but the
    // next target has not. 88px clears the sticky rail's height.
    const READING_LINE = 88;
    let ticking = false;

    const pick = () => {
      ticking = false;
      const line = READING_LINE;
      let best = tocTargets[0];
      let bestTop = -Infinity;
      for (const t of tocTargets) {
        const top = t.el.getBoundingClientRect().top;
        // The last target whose top is above the reading line is the one being read.
        if (top <= line && top > bestTop) {
          bestTop = top;
          best = t;
        }
      }
      // Above the first target nothing qualifies, and an empty highlight reads as broken.
      if (bestTop === -Infinity) best = tocTargets[0];
      setCurrent(best.a.hash.slice(1));
    };

    const onScroll = () => {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(pick);
    };

    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll, { passive: true });

    // A click must move the highlight immediately. Waiting for the scroll event means the
    // wrong entry stays lit for the whole smooth-scroll, which looks like the click failed.
    tocLinks.forEach((a) => {
      a.addEventListener('click', (event) => {
        const id = a.hash.slice(1);
        const target = document.getElementById(decodeURIComponent(id));
        if (!target) return;
        event.preventDefault();
        // Smooth scrolling is a nicety; `prefers-reduced-motion` turns it off and the
        // jump is instant, which is the documented behaviour for that setting.
        const behaviour = window.matchMedia('(prefers-reduced-motion: reduce)').matches
          ? 'auto' : 'smooth';
        target.scrollIntoView({ behavior: behaviour, block: 'start' });
        setCurrent(id);
        if (history.replaceState) history.replaceState(null, '', `#${id}`);
      });
    });

    pick();
  }

  /* ============================================================================
     六、事件日历（Tibo 重置监控）
     ----------------------------------------------------------------------------
     与左侧导航日历同一套语言，但职责不同：那个回答"我要读哪一天"，
     这个回答"那天发生了什么"。所以格子更大、带事件标记、旁边有详情面板。

     日期与事件是服务端数据，**当前显示的月份是浏览状态**，所以网格在客户端渲染：
     为一页只显示一个月的界面渲染十二个月的标记是浪费。
     ========================================================================= */
  const ecal = document.getElementById('event-calendar');
  const ecalData = document.getElementById('tibo-events');
  if (ecal && ecalData) {
    let events = [];
    try {
      events = JSON.parse(ecalData.textContent || '[]');
    } catch { events = []; }

    const byDay = new Map();
    for (const e of events) {
      if (!e.d) continue;
      if (!byDay.has(e.d)) byDay.set(e.d, []);
      byDay.get(e.d).push(e);
    }

    const grid = ecal.querySelector('[data-ecal-grid]');
    const label = ecal.querySelector('[data-ecal-month]');
    const panel = ecal.querySelector('[data-ecal-panel]');
    const prev = ecal.querySelector('[data-ecal-nav="prev"]');
    const next = ecal.querySelector('[data-ecal-nav="next"]');

    const pad = (n) => String(n).padStart(2, '0');
    const iso = (y, m, d) => `${y}-${pad(m)}-${pad(d)}`;
    const today = new Date();
    const todayIso = iso(today.getFullYear(), today.getMonth() + 1, today.getDate());

    // Open on the newest month that actually has events, not on the current month: a page
    // that opens empty looks broken even when the data is fine.
    const newest = [...byDay.keys()].sort().pop() || todayIso;
    let [yy, mm] = newest.split('-').map(Number);
    let selected = newest;

    const esc = (s) => String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');

    const showPanel = (day) => {
      const rows = byDay.get(day) || [];
      if (!rows.length) {
        panel.innerHTML = `<div class="ecal__empty">${esc(day)} 没有记录。</div>`;
        return;
      }
      const entries = rows.map((e) => {
        const posts = (e.posts || []).map((p) => `
          <div class="ecal__quote">
            ${p.stage ? `<em>${esc(p.stage)}</em>` : ''}
            <div>${esc(p.text)}</div>
            ${p.orig ? `<div style="color:var(--muted-fg)">${esc(p.orig)}</div>` : ''}
            ${p.url ? `<a href="${esc(p.url)}" rel="noopener noreferrer" style="font-size:var(--fs-micro);color:var(--muted-fg)">在原站查看 ↗</a>` : ''}
          </div>`).join('');
        return `<li class="ecal__entry" data-kind="${esc(e.k)}">
          <div class="ecal__entry-title">${esc(e.t)}</div>
          <div class="ecal__entry-meta">
            <span>${esc(e.at)}</span>
            <span>${esc(e.l)}</span>
            ${e.s ? `<span>${esc(e.s)}</span>` : ''}
          </div>
          ${e.sch ? `<div class="ecal__entry-meta"><span>${esc(e.sch)}</span></div>` : ''}
          ${posts}
        </li>`;
      }).join('');
      panel.innerHTML = `
        <div class="ecal__panel-head">
          <span class="ecal__panel-date">${esc(day)}</span>
          <span class="ecal__panel-sub">${rows.length} 条记录${day === todayIso ? ' · 今天' : ''}</span>
        </div>
        <ul class="ecal__entries">${entries}</ul>`;
    };

    const render = () => {
      label.textContent = `${yy} 年 ${mm} 月`;
      grid.querySelectorAll('.ecal__day').forEach((el) => el.remove());

      const first = new Date(yy, mm - 1, 1);
      const days = new Date(yy, mm, 0).getDate();
      for (let i = 0; i < first.getDay(); i++) {
        const padCell = document.createElement('span');
        padCell.className = 'ecal__day ecal__day--pad';
        padCell.setAttribute('aria-hidden', 'true');
        grid.appendChild(padCell);
      }
      for (let d = 1; d <= days; d++) {
        const key = iso(yy, mm, d);
        const rows = byDay.get(key);
        const cell = document.createElement(rows ? 'button' : 'span');
        cell.className = 'ecal__day';
        cell.dataset.day = key;
        if (rows) {
          cell.type = 'button';
          cell.dataset.count = String(rows.length);
          cell.setAttribute('aria-label', `${key}，${rows.length} 条记录`);
          cell.innerHTML = `<span class="ecal__num">${d}</span>
            <span class="ecal__marks">${rows.map((e) => `<i data-kind="${esc(e.k)}"></i>`).join('')}</span>`;
          cell.addEventListener('click', () => select(key));
        } else {
          cell.setAttribute('aria-disabled', 'true');
          cell.innerHTML = `<span class="ecal__num">${d}</span>`;
        }
        if (key === todayIso) cell.dataset.today = 'true';
        if (key === selected) cell.setAttribute('aria-selected', 'true');
        grid.appendChild(cell);
      }

      const months = [...new Set([...byDay.keys()].map((k) => k.slice(0, 7)))].sort();
      const here = `${yy}-${pad(mm)}`;
      prev.disabled = !months.length || here <= months[0];
      next.disabled = !months.length || here >= months[months.length - 1];
    };

    const select = (day) => {
      selected = day;
      grid.querySelectorAll('.ecal__day[aria-selected]').forEach((el) => el.removeAttribute('aria-selected'));
      const cell = grid.querySelector(`.ecal__day[data-day="${day}"]`);
      if (cell) cell.setAttribute('aria-selected', 'true');
      showPanel(day);
    };

    const shift = (delta) => {
      mm += delta;
      if (mm < 1) { mm = 12; yy -= 1; }
      if (mm > 12) { mm = 1; yy += 1; }
      render();
    };

    prev.addEventListener('click', () => shift(-1));
    next.addEventListener('click', () => shift(1));
    render();
    showPanel(selected);
  }

  /* ============================================================================
     七、拖拽调整左右两栏宽度
     ----------------------------------------------------------------------------
     宽度是读者的排版偏好，与主题同类：存在 localStorage，不进内容。

     实现要点：

     · **指针事件而不是鼠标事件** —— 触屏与手写笔同样可用，
       而且 `setPointerCapture` 让指针移出手柄甚至移出窗口时仍然收得到事件，
       这正是一次拖拽的常见轨迹（拖到一半松手、或拖出边缘）。

     · **拖拽期间写 CSS 变量**，不直接改元素的 style。轨道宽度由
       `--rail-w` / `--toc-w` 两个变量驱动，网格列跟着变，不用重排两处。

     · **上下限随视口计算** —— 固定像素上下限在小屏上会让内容列被压成一条线。
       上限取"视口宽度减去内容列的最小可读宽度"，下限保证导航项不换行。

     · **双击复位**，因为拖到一个刚好不合适的位置时，读者需要一个确定的退路。
     ========================================================================= */
  const RAIL_KEY = 'aidaily-rail-w';
  const TOC_KEY = 'aidaily-toc-w';

  // Minimum content-column width. The rails may not squeeze the reading column below this:
  // a layout where the navigation is comfortable and the article is a 120px ribbon is worse
  // than one where the navigation is cramped. Matches `--fs-body`'s measure assumptions.
  const MIN_CONTENT = 420;

  /** The widest a rail may get, given the other rail's current width. */
  const maxRailWidth = (spec, otherVar) => {
    const other = parseFloat(
      getComputedStyle(document.documentElement).getPropertyValue(otherVar)
    ) || 0;
    // Viewport minus the other rail, minus the gutter between tracks, minus the content
    // floor, minus the shell's own horizontal padding.
    const gutters = 96;
    const padding = 64;
    return Math.max(
      spec.min,
      window.innerWidth - other - gutters - padding - MIN_CONTENT
    );
  };

  const resizeSpecs = [
    {
      el: document.querySelector('.rail'),
      key: RAIL_KEY,
      cssVar: '--rail-w',
      // The rail sits on the left, so dragging right makes it wider.
      direction: 1,
      min: 190,
      // The TOC is the constraint on the rail, and vice versa.
      otherVar: '--toc-w',
      fallback: 240,
    },
    {
      el: document.querySelector('.toc'),
      key: TOC_KEY,
      cssVar: '--toc-w',
      // The TOC sits on the right, so dragging left makes it wider.
      direction: -1,
      min: 180,
      otherVar: '--rail-w',
      fallback: 240,
    },
  ].map((spec) => ({ ...spec, max: () => maxRailWidth(spec, spec.otherVar) }));

  const store = {
    get(key) {
      try {
        const raw = window.localStorage.getItem(key);
        const value = raw === null ? NaN : Number(raw);
        return Number.isFinite(value) ? value : null;
      } catch { return null; }
    },
    set(key, value) {
      try { window.localStorage.setItem(key, String(Math.round(value))); } catch { /* 隐私模式 */ }
    },
  };

  const clampWidth = (spec, value) =>
    Math.max(spec.min, Math.min(value, spec.max()));

  const applyWidth = (spec, value) => {
    document.documentElement.style.setProperty(spec.cssVar, `${Math.round(value)}px`);
  };

  // Restore saved widths before measuring anything, so the first paint is already right
  // and the layout does not visibly reflow once the reader's preference is applied.
  for (const spec of resizeSpecs) {
    if (!spec.el) continue;
    const saved = store.get(spec.key);
    if (saved !== null) applyWidth(spec, clampWidth(spec, saved));
  }

  for (const spec of resizeSpecs) {
    if (!spec.el) continue;
    const grip = spec.el.querySelector('[data-resize]');
    if (!grip) continue;

    let startX = 0;
    let startWidth = 0;
    let active = false;

    const width = () => spec.el.getBoundingClientRect().width;

    grip.addEventListener('pointerdown', (event) => {
      active = true;
      startX = event.clientX;
      startWidth = width();
      grip.dataset.active = 'true';
      document.body.dataset.resizing = 'true';
      // Capture so the drag keeps tracking outside the grip and outside the window.
      grip.setPointerCapture(event.pointerId);
      event.preventDefault();
    });

    grip.addEventListener('pointermove', (event) => {
      if (!active) return;
      const delta = (event.clientX - startX) * spec.direction;
      applyWidth(spec, clampWidth(spec, startWidth + delta));
    });

    const finish = (event) => {
      if (!active) return;
      active = false;
      grip.dataset.active = 'false';
      delete document.body.dataset.resizing;
      if (grip.hasPointerCapture?.(event.pointerId)) {
        grip.releasePointerCapture(event.pointerId);
      }
      store.set(spec.key, width());
    };

    grip.addEventListener('pointerup', finish);
    grip.addEventListener('pointercancel', finish);

    // Double-click resets. Dragging to a position that turns out to be wrong needs a
    // defined way back; "drag it approximately back" is not one.
    grip.addEventListener('dblclick', () => {
      applyWidth(spec, spec.fallback);
      store.set(spec.key, spec.fallback);
    });

    // Keyboard: the grip is a real button, so it must be operable without a pointer.
    grip.addEventListener('keydown', (event) => {
      const step = event.shiftKey ? 40 : 10;
      let next = null;
      if (event.key === 'ArrowLeft') next = width() - step * spec.direction;
      else if (event.key === 'ArrowRight') next = width() + step * spec.direction;
      else if (event.key === 'Home') next = spec.fallback;
      if (next === null) return;
      event.preventDefault();
      applyWidth(spec, clampWidth(spec, next));
      store.set(spec.key, width());
    });

    // A saved width can exceed the limit after the window shrinks; re-clamp on resize so
    // the content column never collapses to nothing.
    window.addEventListener('resize', () => {
      const current = width();
      const clamped = clampWidth(spec, current);
      if (Math.abs(clamped - current) > 1) applyWidth(spec, clamped);
    }, { passive: true });
  }

  /* ============================================================================
     八、复制订阅地址
     ----------------------------------------------------------------------------
     点订阅按钮的意图是"把地址给我"，不是"打开一屏 XML"。所以复制到剪贴板，
     并给一个明确的成功反馈 —— 没有反馈的复制按钮和坏掉的按钮无法区分。

     `navigator.clipboard` 需要安全上下文（https 或 localhost）。本站是 https，
     但用 file:// 打开的本地副本会走到回退分支，所以回退用
     `select()` + `execCommand`，而不是静默失败。
     ========================================================================= */
  const copyButtons = document.querySelectorAll('[data-copy]');
  if (copyButtons.length) {
    const flash = (button, ok) => {
      if (!button.dataset.label) button.dataset.label = button.textContent.trim();
      button.textContent = ok ? '已复制' : '复制失败，请手动选择';
      button.dataset.copied = ok ? 'true' : 'false';
      window.setTimeout(() => {
        button.textContent = button.dataset.label;
        delete button.dataset.copied;
      }, 1600);
    };

    const legacyCopy = (text) => {
      // Fallback for a non-secure context: a hidden textarea plus the deprecated command is
      // the only option there, and still better than telling the reader to select the text
      // themselves when the modern API is simply unavailable.
      const area = document.createElement('textarea');
      area.value = text;
      area.setAttribute('readonly', '');
      area.style.position = 'fixed';
      area.style.top = '-1000px';
      document.body.appendChild(area);
      area.select();
      let ok = false;
      try { ok = document.execCommand('copy'); } catch { ok = false; }
      document.body.removeChild(area);
      return ok;
    };

    copyButtons.forEach((button) => {
      button.addEventListener('click', async () => {
        const text = button.dataset.copy || '';
        if (!text) return;
        let ok = false;
        try {
          if (navigator.clipboard && window.isSecureContext) {
            await navigator.clipboard.writeText(text);
            ok = true;
          } else {
            ok = legacyCopy(text);
          }
        } catch {
          ok = legacyCopy(text);
        }
        flash(button, ok);
      });
    });
  }

  /* ============================================================================
     九、唯一的入场：标题 + 统计
     ========================================================================= */
  if (!reduced.matches) {
    document.documentElement.classList.add('js-motion');
    const targets2 = document.querySelectorAll('.enter');
    const reveal = (el) => el.classList.add('is-in');
    // 首屏内的无条件显示：不把「看得见」交给观察器的时序
    const showVisible = () => {
      targets2.forEach((el) => {
        if (!el.classList.contains('is-in') && el.getBoundingClientRect().top < window.innerHeight * 0.95) {
          reveal(el);
        }
      });
    };
    if ('IntersectionObserver' in window) {
      const io = new IntersectionObserver((entries) => {
        entries.forEach((e) => { if (e.isIntersecting) { reveal(e.target); io.unobserve(e.target); } });
      }, { threshold: 0.05 });
      targets2.forEach((el) => io.observe(el));
    }
    showVisible();
    window.setTimeout(showVisible, 600);
  }

  /* ============================================================================
     七、目录只在正文滚动时消耗注意力，打印前清掉状态
     ========================================================================= */
  window.addEventListener('beforeprint', () => {
    document.querySelectorAll('[aria-current]').forEach((el) => {
      if (el.closest('.toc')) el.removeAttribute('aria-current');
    });
  });

  // reduced-motion 中途被打开：停掉弹簧（本页没有常驻 rAF，这里只需清状态）
  reduced.addEventListener?.('change', () => {
    if (reduced.matches) document.querySelectorAll('.enter').forEach((el) => el.classList.add('is-in'));
  });
})();
