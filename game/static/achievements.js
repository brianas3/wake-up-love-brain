"use strict";

(() => {
  const content = $("achievements-content");
  let filter = "all", generation = 0;
  const FILTERS = [["all", "全部"], ["情境測驗", "小測驗"], ["互動練習", "聊天闖關"],
    ["unlocked", "已解鎖"], ["locked", "待解鎖"]];

  function progressBar(value, total, label) {
    const p = el("progress", "achievement-progress");
    p.max = total; p.value = value;
    p.setAttribute("aria-label", label || `已完成 ${value} / ${total}`);
    return p;
  }
  function card(badge) {
    const card = el("article", "achievement-card" + (badge.unlocked ? " is-unlocked" : " is-locked"));
    card.dataset.rarity = badge.rarity || "一般";
    const row = el("div", "achievement-card-top"), icon = el("div", "achievement-icon");
    icon.append(ico(badge.icon));
    row.append(icon, el("span", "achievement-rarity", badge.rarity || "一般"));
    const label = el("span", "achievement-status", badge.unlocked ? "✓ 已解鎖" : "尚未解鎖");
    card.append(row, label, el("h4", "", badge.title), el("p", "achievement-description", badge.description));
    if (badge.unlocked) {
      const date = badge.unlocked_at ? new Date(badge.unlocked_at * 1000).toLocaleDateString("zh-TW") : "已完成";
      card.append(el("p", "achievement-unlocked-date", `解鎖日期 · ${date}`));
    } else {
      const current = Math.min(badge.progress, badge.target), total = badge.target;
      const labelRow = el("div", "achievement-progress-label");
      labelRow.append(el("span", "", "目前進度"), el("strong", "", `${current} / ${total}`));
      card.append(labelRow, progressBar(current, total, `${badge.title}，進度 ${current}/${total}`));
    }
    return card;
  }

  function render(data, guest) {
    content.replaceChildren();
    const all = data.badges || [], unlocked = all.filter(b => b.unlocked), pct = data.total ? Math.round(data.unlocked_count * 100 / data.total) : 0;
    const hero = el("section", "achievement-hero");
    const heading = el("div", "achievement-heading");
    heading.append(el("div", "achievement-eyebrow", "ACHIEVEMENT COLLECTION"),
      el("h3", "", "清醒收藏室"),
      el("p", "", guest ? "先探索目標，完成練習後就能收藏徽章。" : "把每一次看清楚、做選擇的練習，變成可收藏的里程碑。"));
    const gauge = el("div", "achievement-gauge");
    gauge.style.setProperty("--percent", `${pct}%`);
    const inner = el("div", "achievement-gauge-inner");
    inner.append(el("strong", "", String(data.unlocked_count)), el("span", "", `/ ${data.total}`));
    gauge.append(inner); hero.append(heading, gauge);
    content.append(hero);

    const info = el("div", "achievement-overview-metrics");
    for (const [num, title] of [[unlocked.filter(b => b.group === "情境測驗").length, "小測驗徽章"],
      [unlocked.filter(b => b.group === "互動練習").length, "聊天闖關徽章"], [pct + "%", "收藏完成率"]]) {
      const metric = el("div", "achievement-metric"); metric.append(el("strong", "", String(num)), el("span", "", title)); info.append(metric);
    }
    content.append(info);
    const remaining = all.filter(b => !b.unlocked).sort((x, y) =>
      (y.progress / Math.max(y.target, 1)) - (x.progress / Math.max(x.target, 1)));
    if (remaining.length) {
      const next = remaining[0];
      const goal = el("section", "achievement-next");
      const icoBox = el("div", "achievement-next-icon"); icoBox.append(ico("flag"));
      const texts = el("div"); texts.append(el("span", "achievement-eyebrow", "下一個目標"),
        el("strong", "", next.title), el("small", "", `${next.description} · ${next.progress}/${next.target}`));
      goal.append(icoBox, texts); content.append(goal);
    } else if (all.length) {
      content.append(el("div", "achievement-finished", "全部徽章已解鎖！可以繼續自由練習與挑戰。"));
    }

    const filters = el("div", "achievement-filters");
    filters.setAttribute("role", "group"); filters.setAttribute("aria-label", "篩選成就圖鑑");
    for (const [key, label] of FILTERS) {
      const button = el("button", "achievement-filter", label); button.type = "button";
      button.setAttribute("aria-pressed", String(filter === key));
      button.onclick = () => {
        filter = key; render(data, guest);
        const active = content.querySelector('.achievement-filter[aria-pressed="true"]');
        if (active) active.focus();
      };
      filters.append(button);
    }
    content.append(filters);

    const visible = all.filter(b => filter === "all" || (filter === "unlocked" && b.unlocked) ||
      (filter === "locked" && !b.unlocked) || b.group === filter);
    if (!visible.length) content.append(el("p", "achievement-empty", filter === "unlocked" ?
      "還沒有解鎖成就。先完成一次小測驗，或完成聊天覆盤吧。" : "這個分類已經沒有待解鎖徽章。"));
    for (const group of ["情境測驗", "互動練習"]) {
      const members = visible.filter(b => b.group === group);
      if (!members.length) continue;
      const head = el("div", "achievement-group-head");
      head.append(el("h3", "", group === "情境測驗" ? "小測驗篇" : "聊天闖關篇"),
        el("span", "", `${members.filter(x => x.unlocked).length} / ${members.length} 枚`));
      content.append(head);
      const grid = el("div", "achievement-grid");
      for (const badge of members) grid.append(card(badge));
      content.append(grid);
    }
    content.append(el("p", "achievement-note", "成就依伺服器保存的答題與覆盤紀錄判定。已解鎖徽章會保留；刪除玩家資料才會清除。"));
    const refresh = el("button", "btn achievement-refresh", "↻ 更新成就進度");
    refresh.type = "button"; refresh.onclick = load; content.append(refresh);
  }

  async function load() {
    const id = ++generation, player = S.player, guest = !S.consentOk;
    content.setAttribute("aria-busy", "true");
    content.replaceChildren(el("p", "", "載入成就圖鑑中…"));
    try {
      const data = guest ? await api("/api/achievements/catalog") : await api("/api/achievements", { player });
      if (id === generation && player === S.player) render(data, guest);
    } catch (e) {
      if (id === generation) {
        const retry = el("button", "btn primary", "重新載入"); retry.type = "button"; retry.onclick = load;
        content.replaceChildren(el("p", "", "成就圖鑑暫時無法載入。"), retry); handleErr(e, "成就：");
      }
    } finally { if (id === generation) content.removeAttribute("aria-busy"); }
  }
  document.querySelectorAll("[data-achievements]").forEach(button => {
    button.onclick = () => {
      if (S.legacy) { legacyPrompt(); return; }
      filter = "all"; openModal("achievements-modal"); load();
    };
  });
})();
