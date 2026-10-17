// 长凳五子棋（templates/game.html）：
// - 点空位落子：不刷新页面，先把棋子画上去，再用服务器返回的最新情况纠正
// - 每 2.5 秒问一次服务器（标签页在后台时暂停），对方落子 / 认输 / 开新局时更新棋盘
// - 没有 JavaScript 时：棋盘本身就是表单，点一下提交、页面刷新，同样能下
(function () {
  var root = document.querySelector("[data-gomoku]");
  if (!root) return;

  // 认输前先确认
  root.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });

  var stateEl = document.getElementById("gomoku-state");
  var textEl = document.getElementById("gomoku-text");
  if (!stateEl || !textEl) return; // 只有一个人：没有棋盘

  var noop = function () {};
  var sound = window.UslandSound || { play: noop, event: noop, seen: noop };
  var text = JSON.parse(textEl.textContent);
  var state = JSON.parse(stateEl.textContent);
  var form = root.querySelector("[data-board-form]");
  var cells = {};
  root.querySelectorAll("[data-cell]").forEach(function (btn) {
    cells[btn.dataset.cell] = btn;
  });
  var statusEl = root.querySelector("[data-status]");
  var busy = false;

  function statusText(s) {
    if (!s.status) return text.no_game;
    if (s.result === "win") return text.result_win;
    if (s.result === "lose") return text.result_lose;
    if (s.result === "draw") return text.result_draw;
    return s.turn === "me" ? text.turn_me : text.turn_partner;
  }

  function cellLabel(key, stone) {
    var parts = key.split(",");
    var label = text.cell.replace("{row}", +parts[0] + 1).replace("{col}", +parts[1] + 1);
    return stone ? label + "，" + text[stone] : label;
  }

  // 按服务器给的情况重画棋盘和周围的文字、按钮
  function render(s) {
    var stones = {};
    s.moves.forEach(function (m, i) {
      stones[m[0] + "," + m[1]] = i % 2 === 0 ? "black" : "white";
    });
    var last = s.moves.length ? s.moves[s.moves.length - 1].join(",") : "";
    var wins = {};
    s.win_line.forEach(function (w) {
      wins[w[0] + "," + w[1]] = true;
    });
    Object.keys(cells).forEach(function (key) {
      var btn = cells[key];
      var stone = stones[key];
      btn.classList.toggle("stone-black", stone === "black");
      btn.classList.toggle("stone-white", stone === "white");
      btn.classList.toggle("is-last", key === last);
      btn.classList.toggle("is-win", !!wins[key]);
      btn.disabled = !!stone || s.turn !== "me";
      btn.setAttribute("aria-label", cellLabel(key, stone));
    });
    statusEl.textContent = statusText(s);
    root.querySelectorAll("[data-player]").forEach(function (el) {
      el.classList.toggle("is-turn", s.turn === el.dataset.player);
      var mine = el.dataset.player === "me";
      var color = mine ? s.my_color : { black: "white", white: "black" }[s.my_color];
      var chip = el.querySelector("[data-player-color]");
      chip.className = "gomoku-chip stone-" + (color || "none");
      el.querySelector("[data-player-color-text]").textContent = color ? text[color] : "";
    });
    root.querySelector("[data-resign]").hidden = s.status !== "playing";
    root.querySelector("[data-new]").hidden = s.status === "playing";
  }

  // 这一局结束时（赢了才）响一声；每局只响一次，刷新页面不重复
  function announceEnd(s) {
    if (!s.result || !s.id) return;
    var key = "gomoku:" + s.id + ":end";
    if (s.result === "win") sound.event("quest_complete", key);
    else sound.seen(key);
  }

  function update(next, fromPartner) {
    var partnerMoved = fromPartner && next.id === state.id && next.moves.length > state.moves.length;
    state = next;
    render(state);
    if (partnerMoved) sound.play("ui_select");
    announceEnd(state);
  }

  // ---------- 落子 ----------
  form.addEventListener("submit", function (event) {
    event.preventDefault(); // 由脚本发请求，不刷新页面
    var btn = event.submitter;
    if (!btn || !btn.dataset.cell || busy || btn.disabled) return;
    var parts = btn.dataset.cell.split(",");
    busy = true;
    // 先画上去（看起来更快），等服务器确认
    btn.classList.add("stone-" + state.my_color);
    Object.keys(cells).forEach(function (key) {
      cells[key].disabled = true;
    });
    sound.play("ui_select");
    fetch(form.action, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ row: +parts[0], col: +parts[1] }),
    })
      .then(function (resp) {
        return resp.json();
      })
      .then(function (data) {
        if (data.state) update(data.state, false);
        if (!data.ok && data.message) statusEl.textContent = data.message;
      })
      .catch(function () {
        render(state); // 网络不通：退回落子前的样子
      })
      .then(function () {
        busy = false;
      });
  });

  // ---------- 同步对方的落子 ----------
  // 打开页面时已经结束的局：只记下"听过了"，不补播
  if (state.result && state.id) sound.seen("gomoku:" + state.id + ":end");
  setInterval(function () {
    if (document.hidden || busy) return;
    fetch(root.dataset.stateUrl, { headers: { Accept: "application/json" } })
      .then(function (resp) {
        return resp.ok ? resp.json() : null;
      })
      .then(function (next) {
        if (next && next.version !== state.version) update(next, true);
      })
      .catch(function () {
        // 网络暂时不通：下次再试
      });
  }, 2500);
})();
