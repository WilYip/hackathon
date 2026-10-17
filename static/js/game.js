// 长凳五子棋（templates/game.html）：
// - 点空位落子：不刷新页面，先把棋子画上去，再用服务器返回的最新情况纠正
// - 每 2.5 秒问一次服务器（标签页在后台时暂停），对方落子 / 认输 / 开新局 / 扔道具时更新
// - 道具互动（像斗地主那样）：卡布奇诺 / 番茄 / 鸡蛋从一个头像飞到另一个头像上
// - 一局结束：弹出结算画面（胜利 / 输了 / 平局 + 手数、用时、总战绩），每局每台设备只弹一次
// - 没有 JavaScript 时：棋盘本身就是表单，点一下提交、页面刷新，同样能下（没有道具和结算画面）
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
  var reduceMotion = window.uslandReduceMotion ? window.uslandReduceMotion() : false;
  var text = JSON.parse(textEl.textContent);
  var images = JSON.parse(document.getElementById("gomoku-images").textContent);
  var state = JSON.parse(stateEl.textContent);
  var form = root.querySelector("[data-board-form]");
  var cells = {};
  root.querySelectorAll("[data-cell]").forEach(function (btn) {
    cells[btn.dataset.cell] = btn;
  });
  var statusEl = root.querySelector("[data-status]");
  var busy = false;

  function fill(template, values) {
    return template.replace(/\{(\w+)\}/g, function (_, key) {
      return values[key];
    });
  }

  function postJSON(url, body) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body || {}),
    }).then(function (resp) {
      return resp.json();
    });
  }

  // ---------- 棋盘 ----------

  function statusText(s) {
    if (!s.status) return text.no_game;
    if (s.result === "win") return text.result_win;
    if (s.result === "lose") return text.result_lose;
    if (s.result === "draw") return text.result_draw;
    return s.turn === "me" ? text.turn_me : text.turn_partner;
  }

  function cellLabel(key, stone) {
    var parts = key.split(",");
    var label = fill(text.cell, { row: +parts[0] + 1, col: +parts[1] + 1 });
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
      el.querySelector("[data-player-color]").className = "gomoku-chip stone-" + (color || "none");
      el.querySelector("[data-player-color-text]").textContent = color ? text[color] : "";
    });
    root.querySelector("[data-resign]").hidden = s.status !== "playing";
    root.querySelector("[data-new]").hidden = s.status === "playing";
  }

  // 新的情况：重画、播放对方扔来的道具；这一局刚结束时弹结算画面
  function update(next, fromPartner) {
    var partnerMoved = fromPartner && next.id === state.id && next.moves.length > state.moves.length;
    var justEnded = state.status === "playing" && next.id === state.id && next.status !== "playing";
    state = next;
    render(state);
    if (partnerMoved) sound.play("ui_select");
    playNewProps(next.props || []);
    if (justEnded) showSettle(state);
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
    postJSON(form.action, { row: +parts[0], col: +parts[1] })
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

  // ---------- 道具互动 ----------
  var propsBox = root.querySelector("[data-props]");
  var toastEl = root.querySelector("[data-toast]");
  var toastTimer = null;
  var lastPropId = 0;
  (state.props || []).forEach(function (p) {
    lastPropId = Math.max(lastPropId, p.id); // 打开页面之前扔的不补播
  });

  function toast(message) {
    toastEl.textContent = message;
    toastEl.classList.add("is-on");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      toastEl.classList.remove("is-on");
    }, 2600);
  }

  // 头像在屏幕上的中心点
  function avatarCenter(who) {
    var el = root.querySelector('[data-player="' + who + '"] .avatar');
    var r = el.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2, el: el };
  }

  // 一个临时的小元素（位置固定在屏幕上），动画结束后自动删掉
  function spawn(className, x, y, html) {
    var el = document.createElement("span");
    el.className = "fx " + className;
    el.style.left = x + "px";
    el.style.top = y + "px";
    if (html) el.innerHTML = html;
    document.body.appendChild(el);
    return el;
  }

  function remove(el, ms) {
    setTimeout(function () {
      el.remove();
    }, ms);
  }

  function shake(el) {
    el.classList.remove("fx-hit");
    void el.offsetWidth;
    el.classList.add("fx-hit");
  }

  // 砸中之后的效果
  function impact(kind, target) {
    if (kind === "tomato") {
      sound.play("pet_touch");
      shake(target.el);
      var boom = spawn("fx-img fx-splash", target.x, target.y, '<img src="' + images.splash + '" alt="">');
      remove(boom, 700);
      for (var i = 0; i < 7; i++) {
        var drop = spawn("fx-drop", target.x, target.y);
        drop.style.setProperty("--dx", Math.round(Math.cos((i / 7) * Math.PI * 2) * 34) + "px");
        drop.style.setProperty("--dy", Math.round(Math.sin((i / 7) * Math.PI * 2) * 26 + 24) + "px");
        remove(drop, 1300);
      }
    } else if (kind === "egg") {
      sound.play("pet_touch");
      shake(target.el);
      var splat = spawn("fx-egg", target.x, target.y, "<i></i>");
      remove(splat, 1900);
    } else {
      sound.play("ui_success");
      var cup = spawn("fx-img fx-cup", target.x + 30, target.y + 8, '<img src="' + images.coffee + '" alt=""><b></b><b></b><b></b>');
      remove(cup, 2400);
      var spark = spawn("fx-img fx-sparkles", target.x, target.y - 18, '<img src="' + images.sparkles + '" alt="">');
      remove(spark, 1200);
    }
  }

  // 道具从 from 的头像飞到 to 的头像（番茄、鸡蛋转着飞；咖啡平稳地送过去）
  function flyProp(kind, from, to) {
    if (reduceMotion) return;
    var a = avatarCenter(from);
    var b = avatarCenter(to);
    var el = spawn("fx-img fx-fly", a.x, a.y, '<img src="' + images[kind] + '" alt="">');
    var dx = b.x - a.x;
    var dy = b.y - a.y;
    var spin = kind === "coffee" ? 0 : 540 * (dx < 0 ? -1 : 1);
    var lift = kind === "coffee" ? -24 : -90; // 抛物线最高点
    var duration = kind === "coffee" ? 900 : 650;
    var anim = el.animate(
      [
        { transform: "translate(-50%, -50%) translate(0, 0) rotate(0deg) scale(0.7)" },
        { transform: "translate(-50%, -50%) translate(" + dx / 2 + "px, " + (dy / 2 + lift) + "px) rotate(" + spin / 2 + "deg) scale(1.1)" },
        { transform: "translate(-50%, -50%) translate(" + dx + "px, " + dy + "px) rotate(" + spin + "deg) scale(0.9)" },
      ],
      { duration: duration, easing: "ease-in" }
    );
    // 砸中：动画结束时；页面不在前台时浏览器会暂停动画，所以再用计时器兜底，哪个先到用哪个
    var landed = false;
    var land = function () {
      if (landed) return;
      landed = true;
      el.remove();
      impact(kind, b);
    };
    anim.onfinish = land;
    setTimeout(land, duration + 150);
  }

  function playNewProps(props) {
    props.forEach(function (p) {
      if (p.id <= lastPropId) return;
      lastPropId = p.id;
      if (p.from === "partner") {
        flyProp(p.kind, "partner", "me");
        toast(text["got_" + p.kind]);
      }
      // 自己扔的已经在点击时播过了
    });
  }

  if (propsBox) {
    propsBox.hidden = false; // 有 JavaScript 才能用道具
    propsBox.addEventListener("click", function (event) {
      var btn = event.target.closest("[data-prop]");
      if (!btn || btn.disabled) return;
      var kind = btn.dataset.prop;
      // 先播自己这边的动画，再告诉服务器（对方轮询时看到）
      flyProp(kind, "me", "partner");
      toast(text["sent_" + kind]);
      sound.play("ui_select");
      propsBox.querySelectorAll("[data-prop]").forEach(function (b) {
        b.disabled = true;
      });
      setTimeout(function () {
        propsBox.querySelectorAll("[data-prop]").forEach(function (b) {
          b.disabled = false;
        });
      }, 2000); // 和服务器的冷却时间一致（1～2 秒）
      postJSON(root.dataset.propUrl, { kind: kind })
        .then(function (data) {
          if (data.ok) lastPropId = Math.max(lastPropId, data.id);
          else if (data.message) toast(data.message);
        })
        .catch(noop);
    });
  }

  // ---------- 结算画面 ----------
  var settle = root.querySelector("[data-settle]");

  function formatTime(seconds) {
    var m = Math.floor(seconds / 60);
    var s = seconds % 60;
    return m ? fill(text.time_min_sec, { m: m, s: s }) : fill(text.time_sec, { s: s });
  }

  function confetti() {
    var box = settle.querySelector("[data-settle-confetti]");
    box.innerHTML = "";
    if (reduceMotion) return;
    var colors = ["var(--usland-amber)", "var(--usland-terracotta)", "var(--usland-sage)", "var(--usland-bay)", "#fff"];
    for (var i = 0; i < 28; i++) {
      var piece = document.createElement("i");
      piece.style.left = Math.random() * 100 + "%";
      piece.style.background = colors[i % colors.length];
      piece.style.animationDelay = Math.random() * 0.6 + "s";
      piece.style.setProperty("--drift", Math.round(Math.random() * 80 - 40) + "px");
      box.appendChild(piece);
    }
  }

  function showSettle(s) {
    if (!settle || !s.result || !s.settle || !settle.showModal) return;
    try {
      localStorage.setItem("gomoku_settled_" + s.id, "1");
    } catch (e) {
      // 存不了（隐私模式）也没关系，只是刷新后可能再弹一次
    }
    var result = s.result;
    settle.className = "panel gomoku-settle settle-" + result;
    settle.querySelector("[data-settle-icon]").src = images[result];
    settle.querySelector("[data-settle-title]").textContent = text["settle_" + result + "_title"];
    var key = "settle_" + result + (s.resigned_by && result !== "draw" ? "_resigned" : "_text");
    settle.querySelector("[data-settle-text]").textContent = text[key];
    settle.querySelector("[data-settle-moves]").textContent = s.settle.moves;
    settle.querySelector("[data-settle-time]").textContent = formatTime(s.settle.seconds);
    var rec = s.settle.record;
    settle.querySelector("[data-settle-record]").textContent =
      fill(text.record, { me: rec.me, partner: rec.partner }) + (rec.draw ? fill(text.draws, { n: rec.draw }) : "");
    if (result === "win") {
      confetti();
      sound.event("quest_complete", "gomoku:" + s.id + ":end");
    } else {
      settle.querySelector("[data-settle-confetti]").innerHTML = "";
      sound.seen("gomoku:" + s.id + ":end");
    }
    settle.showModal();
  }

  if (settle) {
    settle.querySelector("[data-settle-close]").addEventListener("click", function () {
      settle.close();
    });
    // 点结算卡片外面的半透明背景也可以关闭
    settle.addEventListener("click", function (event) {
      if (event.target === settle) settle.close();
    });
    // 再来一局：不刷新页面
    settle.querySelector("[data-settle-new]").addEventListener("submit", function (event) {
      event.preventDefault();
      postJSON(root.dataset.newUrl)
        .then(function (data) {
          settle.close();
          if (data.state) update(data.state, false);
          if (!data.ok && data.message) statusEl.textContent = data.message;
        })
        .catch(function () {
          event.target.submit(); // 网络有问题：退回普通表单
        });
    });
  }

  // 打开页面时：已经结束、但这台设备还没看过结算的局，弹一次
  if (state.result && state.id) {
    var seen = false;
    try {
      seen = localStorage.getItem("gomoku_settled_" + state.id) === "1";
    } catch (e) {
      seen = false;
    }
    if (seen) sound.seen("gomoku:" + state.id + ":end");
    else showSettle(state);
  }

  // ---------- 同步对方的落子和道具 ----------
  setInterval(function () {
    if (document.hidden || busy) return;
    fetch(root.dataset.stateUrl, { headers: { Accept: "application/json" } })
      .then(function (resp) {
        return resp.ok ? resp.json() : null;
      })
      .then(function (next) {
        if (!next) return;
        var newProp = (next.props || []).some(function (p) {
          return p.id > lastPropId;
        });
        if (next.version !== state.version || newProp) update(next, true);
      })
      .catch(function () {
        // 网络暂时不通：下次再试
      });
  }, 2500);
})();
