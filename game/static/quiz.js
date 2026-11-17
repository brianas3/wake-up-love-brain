"use strict";

// Ten-question ABCD practice, using the existing authenticated, server-scored API.
(() => {
  const content = $("quiz-content");
  const LETTERS = ["A", "B", "C", "D"];
  let pending = false;
  let generation = 0;

  function button(label, click, primary = false, extraClass = "") {
    const b = el("button", `btn ${primary ? "primary" : ""} ${extraClass}`.trim(), label);
    b.type = "button";
    b.onclick = click;
    return b;
  }
  function focusPanel() {
    if ($("quiz-modal").classList.contains("hidden")) return;
    const heading = content.querySelector("h3");
    if (heading) { heading.tabIndex = -1; heading.focus({ preventScroll: true }); }
  }
  function sectionEyebrow(text) { return el("div", "quiz-eyebrow", text); }
  function resultCard(q, answer, number) {
    const card = el("section", `quiz-review ${answer.correct ? "quiz-correct" : "quiz-wrong"}`);
    const title = el("h4", "", `${String(number).padStart(2, "0")} · ${answer.correct ? "判斷正確" : "再留意這個訊號"}`);
    const question = el("p", "quiz-review-prompt", q.prompt);
    const mine = el("p", "quiz-answer-line", `你的答案：${LETTERS[answer.choice] || "?"} ${q.options[answer.choice] || ""}`);
    const correct = el("p", "quiz-answer-line is-correct", `參考答案：${LETTERS[answer.correct_choice] || "?"} ${q.options[answer.correct_choice] || ""}`);
    const why = el("p", "quiz-explanation", answer.explanation);
    card.append(title, question, mine, correct, why);
    if (!answer.correct && answer.confidence === 3) card.append(el("p", "quiz-insight", "這題原本很有把握，可以再看一次解析。"));
    return card;
  }
  function render(data, feedback = false) {
    content.replaceChildren();
    const a = data.active;
    if (feedback && a && a.answers.length) {
      const index = a.answers.length - 1;
      content.append(sectionEyebrow(`第 ${index + 1} 題 · 即時回饋`),
        el("h3", "quiz-section-title", a.answers[index].correct ? "答對了，這個觀察很重要" : "這個地方可以多留意"),
        resultCard(a.questions[index], a.answers[index], index + 1));
      if (a.completed && data.new_badges && data.new_badges.length) {
        content.append(el("div", "quiz-new-achievements", `解鎖成就：${data.new_badges.join("、")}`));
      }
      content.append(button(a.completed ? "查看本次結果" : "繼續下一題", () => { render(data); focusPanel(); }, true, "quiz-wide-button"));
      return;
    }
    if (!a) {
      const hero = el("section", "quiz-intro-hero");
      const emblem = el("div", "quiz-intro-icon"); emblem.append(ico("brain"));
      hero.append(emblem, sectionEyebrow("RED FLAG CHALLENGE · 10 題"),
        el("h3", "", "你的戀愛雷達準備好了嗎？"),
        el("p", "", "從聊天情境中找出需要留意的訊號，也練習分辨正常界線。每題都是 A／B／C／D 四選一。"));
      content.append(hero);
      const details = el("div", "quiz-intro-grid");
      for (const [icon, title, desc] of [["note", "10 題挑戰", "8 題紅旗＋2 題正常互動"],
        ["flag", "每題有解析", "選完就知道判斷依據"], ["medal", "挑戰成就", "滿分與精準觀察可解鎖徽章"]]) {
        const item = el("div", "quiz-intro-point"), symbol = el("span", "quiz-intro-point-icon"); symbol.append(ico(icon));
        item.append(symbol, el("strong", "", title), el("small", "", desc)); details.append(item);
      }
      content.append(details);
      if (data.needs_restart) content.append(el("p", "quiz-legacy-note", "偵測到舊版尚未完成的 6 題練習。開始新版後，會在存檔中保留舊紀錄備份。"));
      content.append(button("開始 10 題挑戰", () => request("start"), true, "quiz-wide-button"),
        el("p", "fine", "確認答案後會自動儲存，可以中途關閉再繼續；結果只用來練習判斷，不是心理診斷。"));
      return;
    }
    if (a.completed) {
      const isNew = a.questions.length === 10;
      const percentage = Math.round((a.score / a.questions.length) * 100);
      const box = el("div", "quiz-finish");
      const ring = el("div", "quiz-score-ring");
      ring.style.setProperty("--score", `${percentage}%`);
      ring.append(el("strong", "", String(a.score)), el("small", "", `/ ${a.questions.length} 題`));
      const title = percentage === 100 ? "紅旗辨識大師！" : percentage >= 80 ? "觀察力很敏銳！" : percentage >= 60 ? "繼續累積判斷力" : "每一次練習都有收穫";
      box.append(sectionEyebrow(isNew ? "本次挑戰完成" : "舊版測驗紀錄"), ring, el("h3", "", title),
        el("p", "", `答對 ${a.score} 題，正確率 ${percentage}%。分數反映本次情境判斷，不代表依附類型或受騙機率。`));
      content.append(box);
      const answered = a.answers || [];
      const accuracy = el("div", "quiz-result-stats");
      for (const [label, n] of [["答對", answered.filter(x => x.correct).length], ["再練習", answered.filter(x => !x.correct).length]]) {
        const small = el("div", "quiz-result-stat"); small.append(el("strong", "", String(n)), el("span", "", label)); accuracy.append(small);
      }
      content.append(accuracy);
      content.append(button("再挑戰 10 題", () => request("start"), true, "quiz-wide-button"));
      const mistakes = answered.map((ans, i) => ({ ans, q: a.questions[i], i })).filter(x => !x.ans.correct);
      if (mistakes.length) {
        const wrong = el("details", "quiz-accordion");
        wrong.open = true;
        wrong.append(el("summary", "", `錯題回顧 · ${mistakes.length} 題`));
        mistakes.forEach(x => wrong.append(resultCard(x.q, x.ans, x.i + 1)));
        content.append(wrong);
      }
      const all = el("details", "quiz-accordion");
      all.append(el("summary", "", "查看全部題目與解析"));
      a.answers.forEach((ans, i) => all.append(resultCard(a.questions[i], ans, i + 1)));
      content.append(all);
      if (data.history && data.history.length) {
        const history = el("details", "quiz-accordion");
        history.append(el("summary", "", "最近挑戰紀錄"));
        [...data.history].reverse().forEach(h => history.append(el("p", "quiz-history-line",
          `${new Date(h.completed_at * 1000).toLocaleString("zh-TW")} · ${h.score} / ${h.total} 題`)));
        content.append(history);
      }
      return;
    }

    const index = a.answers.length, q = a.questions[index];
    const progress = el("progress", "quiz-progress");
    progress.max = a.questions.length; progress.value = index;
    progress.setAttribute("aria-label", `已完成 ${index} 題，總共 ${a.questions.length} 題`);
    content.append(progress);

    const bubble = el("div", "quiz-scene");
    const head = el("div", "quiz-scene-heading"), avatar = el("span", "quiz-scene-avatar");
    avatar.append(ico("user"));
    head.append(avatar, el("span", "", "聊天對象"), el("span", "quiz-scene-time", "剛剛"));
    bubble.append(head, el("div", "quiz-chat-bubble", q.prompt));
    content.append(bubble);

    const form = el("form", "quiz-form"), choices = el("fieldset", "quiz-options");
    choices.append(el("legend", "", "這段互動，你會怎麼判斷或回應？"));
    q.options.forEach((option, i) => {
      const label = el("label", "quiz-option"), input = el("input");
      input.type = "radio"; input.name = "choice"; input.value = String(i); input.required = true;
      const mark = el("span", "quiz-option-letter", LETTERS[i]);
      label.append(input, mark, el("span", "quiz-option-text", option)); choices.append(label);
    });
    const confidence = el("fieldset", "quiz-confidence");
    confidence.append(el("legend", "", "你對自己的判斷有多大把握？"));
    const confidenceRow = el("div", "quiz-confidence-row");
    for (const [value, labelText] of [[1, "不太確定"], [2, "有點把握"], [3, "很有把握"]]) {
      const label = el("label", "quiz-confidence-pill"), inp = el("input");
      inp.type = "radio"; inp.name = "confidence"; inp.required = true; inp.value = String(value);
      label.append(inp, el("span", "", labelText)); confidenceRow.append(label);
    }
    confidence.append(confidenceRow);
    const submit = el("button", "btn primary quiz-wide-button", "確認答案，查看解析");
    submit.type = "submit";
    form.append(choices, confidence, submit);
    form.onsubmit = e => {
      e.preventDefault();
      if (!form.reportValidity()) return;
      const formData = new FormData(form);
      request("answer", { attempt_id: a.id, question_id: q.id,
        choice: Number(formData.get("choice")), confidence: Number(formData.get("confidence")) }, true);
    };
    content.append(form, el("p", "quiz-footnote", "作答確認後不能修改，關閉測驗不會遺失進度。"));
  }

  async function request(path, extra = {}, feedback = false) {
    if (pending) return;
    pending = true;
    const id = ++generation, player = S.player;
    content.setAttribute("aria-busy", "true");
    const controls = [...content.querySelectorAll("button, input, select")];
    controls.forEach(x => { x.disabled = true; });
    try {
      const data = await api("/api/quiz/" + path, { player, ...extra });
      if (id === generation && player === S.player) { render(data, feedback); focusPanel(); }
    } catch (e) {
      controls.forEach(x => { x.disabled = false; });
      if (path === "state") content.replaceChildren(el("p", "", "測驗暫時無法載入。"), button("重新載入", () => request("state"), true));
      handleErr(e, "小測驗：");
    } finally {
      pending = false;
      content.removeAttribute("aria-busy");
    }
  }
  document.querySelectorAll("[data-quiz]").forEach(b => {
    b.onclick = () => {
      if (S.legacy) { legacyPrompt(); return; }
      if (!S.consentOk) {
        show("home"); toast("請先閱讀並同意首頁的資料說明，再按「開始」進入。");
        $("consent-ok").focus(); return;
      }
      if (!$("quiz-modal").classList.contains("hidden")) return;
      content.replaceChildren(el("p", "", "載入測驗中…"));
      openModal("quiz-modal"); request("state");
    };
  });
})();
