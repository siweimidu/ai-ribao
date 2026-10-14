/* ============================================================================
   motion.js — 「Q弹、灵动、跟手」的具体实现
   ----------------------------------------------------------------------------
   全部是原生 rAF，没有引入任何动效库。依据 motion-web 的 handfeel.md：
     诊断表把「四平八稳/太机械」归因于「朝目标做普通 lerp，没有过冲也没有重量」，
     把「自己在动/不跟手」归因于「元素忽略自身速度」。

   所以这里用四件事：
     §1 欠阻尼弹簧      —— 过冲后回稳，读作「有重量地落下」，而不是「滑过去」
     §2 速度耦合        —— 倾斜量随速度变化，停下时自然回正
     §4 次级果冻        —— 环境元素跟着主运动的余速晃动（同一流体内的物体）
     §7.1 1-exp(-k·dt)  —— 帧率无关，30/60/120fps 手感一致

   刻意**没有**做的（都是 slop 闸门明确点名的）：
     × 拖尾圆点光标（B7，2019 年的签名，现在是默认值）
     × 每个卡片都 translateY(-4px) + 阴影（B1，对一切生效等于什么都没说）
     × 全站统一的滚动 fade-up（B2）
   ========================================================================= */

(() => {
  'use strict';

  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const finePointer = window.matchMedia('(hover: hover) and (pointer: fine)').matches;

  /* ------------------------------------------------------------------ 工具 */
  const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);

  /**
   * 帧率无关的指数趋近（handfeel §7.1）。
   *
   * 每帧常数 lerp（`x += d * 0.1`）在不同帧率下是**不同的滤波器**——120Hz 屏幕上
   * 会快一倍。这里用 1-exp(-k·dt)，k 是「每秒的趋近速率」，与帧率无关。
   */
  const approach = (current, target, k, dt) =>
    current + (target - current) * (1 - Math.exp(-k * dt));

  /* ============================================================ §1 欠阻尼弹簧
   * 一个弹簧管一个量，速度存在闭包里（绝不放在会触发重渲染的地方）。
   * damping 0.86 = 顽皮弹跳，0.90 = 果冻，0.93 = 平静。
   */
  class Spring {
    constructor({ stiffness = 80, damping = 0.90 } = {}) {
      this.k = stiffness;
      this.damping = damping;
      this.value = 0;
      this.target = 0;
      this.velocity = 0;
    }
    step(dt) {
      // 积分步长钳制：切标签页回来时 dt 可能是几秒，会让弹簧炸开
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

  /* ==================================================== 光标跟随：主循环
   * 悬停某一行时，行本身轻微让位（位移 + 按速度倾斜），序号做果冻缩放。
   * 不是「整张卡片抬起来」——那是 B1。这里表达的是：这一行正在被读。
   */
  const rows = Array.from(document.querySelectorAll('.row'));

  if (finePointer && !reduced && rows.length) {
    const state = rows.map(() => ({
      tx: new Spring({ stiffness: 90, damping: 0.88 }),
      ty: new Spring({ stiffness: 90, damping: 0.88 }),
      rot: new Spring({ stiffness: 60, damping: 0.93 }),
      jelly: new Spring({ stiffness: 55, damping: 0.90 }),   // §4 次级
      ix: new Spring({ stiffness: 120, damping: 0.86 }),      // 序号 x 缩放
      iy: new Spring({ stiffness: 120, damping: 0.86 }),
    }));

    let hovered = -1;
    let pointerX = 0, pointerY = 0;
    let lastX = 0, lastY = 0;

    const MAX_SHIFT = 5;      // px，位移上限。再大就成了「卡片跳舞」
    const MAX_TILT = 0.55;    // deg，倾角上限
    const LEAD = 0.06;        // 速度耦合增益

    window.addEventListener('pointermove', (e) => {
      pointerX = e.clientX;
      pointerY = e.clientY;
    }, { passive: true });

    rows.forEach((row, i) => {
      row.addEventListener('pointerenter', () => { hovered = i; });
      row.addEventListener('pointerleave', () => { if (hovered === i) hovered = -1; });
    });

    let prev = performance.now();
    let rafId = 0;

    const frame = (now) => {
      const dt = Math.min((now - prev) / 1000, 1 / 30);
      prev = now;

      // 光标速度：位移量除以时间，再用指数趋近抹平抖动
      const dx = (pointerX - lastX) / Math.max(dt, 1 / 240);
      const dy = (pointerY - lastY) / Math.max(dt, 1 / 240);
      lastX = approach(lastX, pointerX, 18, dt);
      lastY = approach(lastY, pointerY, 18, dt);

      let active = 0;

      rows.forEach((row, i) => {
        const s = state[i];
        const isHot = i === hovered;

        if (isHot) {
          // §2 速度耦合：元素对「自己移动得多快」作出反应。
          s.tx.target = clamp(dx * LEAD, -MAX_SHIFT, MAX_SHIFT);
          s.ty.target = clamp(dy * LEAD, -MAX_SHIFT, MAX_SHIFT);
          s.rot.target = clamp(s.tx.value * 0.09, -MAX_TILT, MAX_TILT);
          s.jelly.target = clamp(Math.hypot(dx, dy) / 900, 0, 0.5);
          s.ix.target = 1.14;
          s.iy.target = 0.86;   // 水平拉伸 + 垂直压缩 = 体积守恒的挤压感
        } else {
          s.tx.target = 0; s.ty.target = 0; s.rot.target = 0;
          s.jelly.target = 0; s.ix.target = 1; s.iy.target = 1;
        }

        const tx = s.tx.step(dt);
        const ty = s.ty.step(dt);
        const rot = s.rot.step(dt);
        const jel = s.jelly.step(dt);
        const ix = s.ix.step(dt);
        const iy = s.iy.step(dt);

        row.style.setProperty('--tx', tx.toFixed(2) + 'px');
        row.style.setProperty('--ty', ty.toFixed(2) + 'px');
        row.style.setProperty('--rot', rot.toFixed(3) + 'deg');

        const index = row.querySelector('.row-index');
        if (index) {
          // 果冻叠加在缩放的绝对值上，而不是相乘 —— 否则松手瞬间会「弹回再抖」
          index.style.setProperty('--ix', (ix + jel).toFixed(3));
          index.style.setProperty('--iy', (iy - jel * 0.6).toFixed(3));
          index.style.setProperty('--rot-ix', (rot * -0.4).toFixed(2) + 'deg');
          index.style.transform =
            `scale(var(--ix, 1), var(--iy, 1)) rotate(var(--rot-ix, 0deg))`;
        }

        // 仍在动就继续跑；全静止就停掉 rAF，别空转耗电
        const moving = !s.tx.settled || !s.ty.settled || !s.rot.settled ||
                       !s.jelly.settled || !s.ix.settled || !s.iy.settled;
        if (moving || isHot) active++;
      });

      if (active === 0 && hovered === -1) {
        rafId = window.setTimeout(() => {
          rafId = requestAnimationFrame(frame);
        }, 420);   // 冷下来后降频轮询，不占用每帧预算
        return;
      }
      rafId = requestAnimationFrame(frame);
    };

    // 只在有行进入视口时才启动，且尊重 reduced-motion
    const reduceMQ = window.matchMedia('(prefers-reduced-motion: reduce)');
    const start = () => {
      if (reduceMQ.matches) return;
      prev = performance.now();
      lastX = pointerX; lastY = pointerY;
      rafId = requestAnimationFrame(frame);
    };
    start();
    reduceMQ.addEventListener('change', () => {
      if (reduceMQ.matches) {
        cancelAnimationFrame(rafId);
        rows.forEach((row) => {
          row.style.removeProperty('--tx');
          row.style.removeProperty('--ty');
          row.style.removeProperty('--rot');
        });
      } else {
        start();
      }
    });
  }

  /* ================================================ 入场：只有三处
   * B2：全站统一的 fade-up 会让页面变成一串相同的到达。
   * 这里只给三类元素入场：标题带、前三行事件、指标数字。其余内容本来就在。
   *
   * 关键：**隐藏是 JS 开启的，不是 CSS 默认的**。初版把 `.enter { opacity: 0 }`
   * 写在 CSS 里，一旦观察器没及时触发，前三条事件就是隐形的——截图里整段空白。
   * 内容绝不能依赖动效才能出现（B8）。所以先加类、再观察，且下面有兜底。
   */
  if (!reduced) {
    document.documentElement.classList.add('js-motion');

    const targets = document.querySelectorAll('.enter');

    const reveal = (el) => {
      el.style.setProperty('--enter-delay', (el.dataset.delay || 0) + 'ms');
      el.classList.add('is-in');
    };

    // 先无条件显示首屏内的元素：不把「看得见」这件事交给观察器的时序
    const revealVisible = () => {
      targets.forEach((el) => {
        if (el.classList.contains('is-in')) return;
        if (el.getBoundingClientRect().top < window.innerHeight * 0.95) reveal(el);
      });
    };

    if ('IntersectionObserver' in window) {
      const io = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          reveal(entry.target);
          io.unobserve(entry.target);
        });
      }, { rootMargin: '0px 0px -8% 0px', threshold: 0.05 });
      targets.forEach((el) => io.observe(el));
    }

    revealVisible();
    window.setTimeout(revealVisible, 600);
    window.addEventListener('load', revealVisible, { once: true });
  }

  /* ==================================================== 指标数字：只在指标上
   * 数字滚动是**内容相关**的：它告诉读者「这是刚算出来的」。放在正文上就是装饰。
   */
  if (!reduced) {
    const counters = document.querySelectorAll('.count-up[data-to]');
    const run = (el) => {
      const to = parseFloat(el.dataset.to);
      if (!isFinite(to)) return;
      const dur = 900;
      const t0 = performance.now();
      const tick = (now) => {
        const p = clamp((now - t0) / dur, 0, 1);
        // ease-out-expo：快进慢落，与页面其它入场同一性格
        const eased = p === 1 ? 1 : 1 - Math.pow(2, -10 * p);
        el.textContent = Math.round(to * eased).toLocaleString('en-US');
        if (p < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    };

    if ('IntersectionObserver' in window) {
      const io = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          run(entry.target);
          io.unobserve(entry.target);
        });
      }, { threshold: 0.4 });
      counters.forEach((el) => io.observe(el));
    } else {
      counters.forEach(run);
    }
  } else {
    // 降级：直接把终值写上，不留空
    document.querySelectorAll('.count-up[data-to]').forEach((el) => {
      el.textContent = Math.round(parseFloat(el.dataset.to)).toLocaleString('en-US');
    });
  }

  /* ============================================ 筛选：单源/多源
   * 这是页面上唯一真正的交互控制。用 aria-pressed 表达状态，
   * 保证键盘与读屏可用（components.md 要求交互组件有完整状态矩阵）。
   */
  const filters = document.querySelectorAll('.chip[data-filter]');
  if (filters.length) {
    filters.forEach((btn) => {
      btn.addEventListener('click', () => {
        const on = btn.getAttribute('aria-pressed') === 'true';
        filters.forEach((b) => b.setAttribute('aria-pressed', 'false'));
        btn.setAttribute('aria-pressed', on ? 'false' : 'true');
        const mode = on ? 'all' : btn.dataset.filter;

        document.querySelectorAll('.row').forEach((row) => {
          const multi = row.dataset.level === 'multi_source';
          const show = mode === 'all' || (mode === 'multi' && multi) || (mode === 'single' && !multi);
          row.hidden = !show;
        });

        const shown = document.querySelectorAll('.row:not([hidden])').length;
        const status = document.getElementById('filter-status');
        if (status) {
          status.textContent = mode === 'all'
            ? `显示全部 ${shown} 条`
            : `已筛选：显示 ${shown} 条`;
        }
      });
    });
  }

  /* -------------------------------------------------- 打印前清掉变换 */
  window.addEventListener('beforeprint', () => {
    rows.forEach((row) => {
      row.style.removeProperty('--tx');
      row.style.removeProperty('--ty');
      row.style.removeProperty('--rot');
    });
  });
})();
