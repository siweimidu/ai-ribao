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
        const LABEL = { auto: '自动', default: '默认', light: '亮色', dark: '暗色' };
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
     五、右侧目录：滚动高亮
     ----------------------------------------------------------------------------
     这是页面上唯一「活」的东西，也是整页唯一的冒险点。
     用 IntersectionObserver 而不是 scroll 事件：滚动处理函数在长页面上会掉帧，
     而且 60 个条目 + 8 个章节逐帧算位置是浪费。
     ========================================================================= */
  const tocLinks = [...document.querySelectorAll('.toc__nav a')];
  const targets = tocLinks
    .map((a) => ({ a, el: document.getElementById(decodeURIComponent(a.hash.slice(1))) }))
    .filter((x) => x.el);

  if (targets.length && 'IntersectionObserver' in window) {
    // Track which targets are currently inside the reading band, then highlight the
    // topmost one. Taking "the last thing that entered" instead makes the highlight jump
    // around during a fast scroll.
    const visible = new Map();
    const setCurrent = (id) => {
      tocLinks.forEach((a) => {
        if (a.hash.slice(1) === id) a.setAttribute('aria-current', 'true');
        else a.removeAttribute('aria-current');
      });
    };

    const io = new IntersectionObserver((entries) => {
      for (const e of entries) visible.set(e.target.id, e.isIntersecting);
      const firstOn = targets.find((t) => visible.get(t.el.id));
      // At the very top nothing may be inside the band yet, and clearing the highlight
      // leaves the TOC looking broken. Fall back to the first section.
      setCurrent(firstOn ? firstOn.a.hash.slice(1) : targets[0].a.hash.slice(1));
    }, {
      // The band starts below the sticky offset and does not reach the bottom of the
      // viewport, so the highlight tracks what is being *read* rather than what has just
      // scrolled past.
      rootMargin: '-88px 0px -55% 0px',
      threshold: 0,
    });

    targets.forEach((t) => io.observe(t.el));
    setCurrent(targets[0].a.hash.slice(1));

    // Clicking a TOC link: move the highlight immediately, otherwise it lags behind the
    // smooth scroll and briefly marks the wrong section.
    tocLinks.forEach((a) => {
      a.addEventListener('click', () => setCurrent(a.hash.slice(1)));
    });
  }

  /* ============================================================================
     六、唯一的入场：标题 + 统计
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
