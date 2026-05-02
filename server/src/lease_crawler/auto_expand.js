// Auto-expand listing pages: scroll to bottom, click "Load more" / "Show all"
// buttons, repeat until DOM stops growing or we hit the iteration cap. Injected
// by the Obscura crawler via --eval before the HTML dump.
(async () => {
  const MAX_ITERATIONS = 6;
  const SCROLL_PAUSE_MS = 1200;
  const CLICK_PAUSE_MS = 1500;
  const STABLE_PASSES_TO_STOP = 1;
  const PATTERN = /load more|show all|see all|view all|show \d+ more|view all units|see more|more results/i;

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  const isVisible = (el) => {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    const style = window.getComputedStyle(el);
    return style.display !== "none" && style.visibility !== "hidden" && style.opacity !== "0";
  };

  const findExpanders = () => {
    const candidates = Array.from(
      document.querySelectorAll('button, a, [role="button"], [data-testid*="more"], [data-testid*="all"]'),
    );
    return candidates.filter((el) => {
      if (!isVisible(el)) return false;
      const text = (el.innerText || el.textContent || "").trim();
      if (!text || text.length > 80) return false;
      return PATTERN.test(text);
    });
  };

  let lastSize = document.body.innerHTML.length;
  let stablePasses = 0;
  let totalClicks = 0;
  let iterations = 0;

  for (let i = 0; i < MAX_ITERATIONS; i++) {
    iterations = i + 1;

    // Scroll to bottom for infinite-scroll lazy loaders.
    window.scrollTo({ top: document.body.scrollHeight, behavior: "instant" });
    await sleep(SCROLL_PAUSE_MS);

    // Click any visible expander buttons.
    const expanders = findExpanders();
    for (const btn of expanders) {
      try {
        btn.click();
        totalClicks++;
      } catch (_) {
        // ignored — button may detach mid-click
      }
    }
    if (expanders.length > 0) await sleep(CLICK_PAUSE_MS);

    // Stop early if DOM stopped growing AND we found nothing to click.
    const currentSize = document.body.innerHTML.length;
    if (currentSize === lastSize && expanders.length === 0) {
      stablePasses++;
      if (stablePasses >= STABLE_PASSES_TO_STOP) break;
    } else {
      stablePasses = 0;
    }
    lastSize = currentSize;
  }

  // Scroll back to top so the dump captures hero/header content too.
  window.scrollTo({ top: 0, behavior: "instant" });
  await sleep(300);

  // Tag the dom so we can detect that auto_expand ran.
  document.documentElement.setAttribute("data-auto-expanded", "true");
  document.documentElement.setAttribute("data-auto-expand-clicks", String(totalClicks));
  document.documentElement.setAttribute("data-auto-expand-iters", String(iterations));

  return { iterations, totalClicks, finalSize: lastSize };
})();
