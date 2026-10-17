// 初见森林：森林散步式的性格测试（templates/forest/quiz.html）
//
// - 一页一题；每答一题，小角色沿小路走到下一个路标，天色从清晨慢慢变成黄昏
// - 选择后森林小精灵说一句和选项有关的话：用鼠标 / 手指点选项时，约 1 秒后自动进入下一题，
//   点气泡或"跳过"马上继续；用键盘（方向键选、Enter 或"下一题"继续）时不自动跳题
// - 每走完一个维度的 3 题，弹出"森林发现"卡片；最后一张卡片的按钮直接提交看结果
// - 减少动态效果（系统设置或小信箱开关）时：不播放动画，但流程和键盘操作都一样
// 没有 JavaScript 时，12 题一起显示，也能直接提交
(function () {
  var form = document.querySelector("[data-forest-quiz]");
  if (!form) return;
  document.documentElement.classList.add("js");

  var REPLY_DELAY = 1100; // 小精灵的话停留多久（毫秒）
  var steps = Array.prototype.slice.call(form.querySelectorAll("[data-step]"));
  var progressText = form.querySelector("[data-progress-text]");
  var errorBox = form.querySelector("[data-wizard-error]");
  var prevBtn = form.querySelector("[data-prev]");
  var nextBtn = form.querySelector("[data-next]");
  var submitBtn = form.querySelector("[data-submit]");

  var scene = document.querySelector("[data-walk]");
  var walker = document.querySelector("[data-walker]");
  var points = JSON.parse(document.querySelector("[data-walk-points]").textContent);
  var posts = document.querySelectorAll("[data-post]");

  var bubble = document.querySelector("[data-spirit-bubble]");
  var spiritText = document.querySelector("[data-spirit-text]");
  var skipBtn = document.querySelector("[data-skip]");

  var dialog = document.querySelector("[data-discovery]");
  var discoveries = JSON.parse(document.getElementById("discoveries").textContent);

  var current = 0;
  var position = 0; // 小角色站在第几个路标（0 = 起点）
  var pending = null; // 等待自动进入下一题的计时器
  var shown = {}; // 每个维度上次弹出发现卡片时的答案，答案没变就不再弹

  form.classList.add("is-js");

  // 全站声音管理器（static/js/sound.js）；万一没加载，用什么都不做的替身
  var noop = function () {};
  var sound = window.UslandSound || { play: noop, event: noop, seen: noop, next: noop, expectLive: noop };

  var reduceMotion = function () {
    return window.uslandReduceMotion ? window.uslandReduceMotion() : false;
  };

  var answered = function (i) {
    return !!steps[i].querySelector("input:checked");
  };

  // ---------- 小路：小角色的位置和天色 ----------
  var moveWalker = function (n) {
    var moved = n !== position;
    position = n;
    var p = points[n];
    walker.style.left = p.x + "%";
    walker.style.top = p.y + "%";
    // 天色：0 = 清晨，0.5 = 白天，1 = 黄昏（style.css 用这几个变量混合三层天空）
    var progress = n / (points.length - 1);
    scene.style.setProperty("--progress", progress);
    scene.style.setProperty("--day", Math.min(1, progress * 2));
    scene.style.setProperty("--dusk", Math.max(0, progress * 2 - 1));
    posts.forEach(function (post) {
      var k = Number(post.dataset.post);
      post.classList.toggle("is-passed", k > 0 && k <= n);
      post.classList.toggle("is-here", k === n);
    });
    scene.setAttribute(
      "aria-label",
      scene.dataset.label.replace("{total}", points.length - 1).replace("{n}", n)
    );
    if (moved && n > 0) sound.play("pet_steps"); // 小角色真的走了一步
    // 走路时一蹦一跳（减少动态效果时不播放）
    if (moved && !reduceMotion()) {
      walker.classList.remove("is-walking");
      void walker.offsetWidth;
      walker.classList.add("is-walking");
    }
  };

  // ---------- 小精灵说话 ----------
  var say = function (text, canSkip) {
    spiritText.textContent = text;
    skipBtn.hidden = !canSkip;
    bubble.classList.toggle("is-waiting", canSkip);
    if (!reduceMotion()) {
      bubble.classList.remove("is-talking");
      void bubble.offsetWidth;
      bubble.classList.add("is-talking");
    }
  };

  var cancelPending = function () {
    if (pending) {
      clearTimeout(pending);
      pending = null;
    }
    skipBtn.hidden = true;
    bubble.classList.remove("is-waiting");
  };

  // ---------- 显示第 i 题 ----------
  var show = function (i, focus) {
    cancelPending();
    current = i;
    steps.forEach(function (step, n) {
      step.hidden = n !== i;
    });
    progressText.textContent = form.dataset.stepLabel.replace("{n}", i + 1).replace("{total}", steps.length);
    prevBtn.hidden = i === 0;
    nextBtn.hidden = i === steps.length - 1;
    submitBtn.hidden = i !== steps.length - 1;
    errorBox.textContent = "";
    moveWalker(i);
    if (focus) {
      var target = steps[i].querySelector("input:checked") || steps[i].querySelector("input");
      if (target) target.focus({ preventScroll: true });
    }
  };

  // ---------- 森林发现 ----------
  // 第 i 题是不是某个维度的最后一题（下一题属于别的维度，或者已经是最后一题）
  var endsDimension = function (i) {
    return i === steps.length - 1 || steps[i + 1].dataset.dimension !== steps[i].dataset.dimension;
  };

  var discoveryFor = function (i) {
    var dim = steps[i].dataset.dimension;
    var votes = {};
    var signature = "";
    steps.forEach(function (step) {
      if (step.dataset.dimension !== dim) return;
      var picked = step.querySelector("input:checked");
      if (!picked) return;
      votes[picked.dataset.pole] = (votes[picked.dataset.pole] || 0) + 1;
      signature += picked.value;
    });
    var best = null;
    Object.keys(votes).forEach(function (pole) {
      if (best === null || votes[pole] > votes[best]) best = pole;
    });
    return { dim: dim, pole: best, votes: votes[best], signature: signature };
  };

  var openDiscovery = function (info, isLast, then) {
    var data = discoveries[info.dim];
    var pole = data.poles[info.pole];
    dialog.querySelector("[data-discovery-label]").textContent = data.label;
    dialog.querySelector("[data-discovery-title]").textContent = dialog.dataset.lean.replace("{name}", pole.name);
    dialog.querySelector("[data-discovery-text]").textContent = pole.text;
    dialog.querySelector("[data-discovery-votes]").textContent = dialog.dataset.votes.replace("{n}", info.votes);
    var go = dialog.querySelector("[data-discovery-go]");
    go.textContent = isLast ? dialog.dataset.finish : dialog.dataset.continue;
    // 点按钮 = 确认继续；按 Esc 关闭 = 没确认（最后一张时只关闭卡片，不提交）
    var confirmed = false;
    go.onclick = function () {
      confirmed = true;
      dialog.close();
    };
    dialog.onclose = function () {
      then(confirmed);
    };
    if (dialog.showModal) {
      dialog.showModal();
      go.focus();
    } else {
      then(true); // 很老的浏览器不支持 <dialog>：直接继续
    }
  };

  // ---------- 前进 ----------
  var advance = function () {
    cancelPending();
    if (!answered(current)) {
      errorBox.textContent = form.dataset.pickHint;
      return;
    }
    var isLast = current === steps.length - 1;
    var goOn = function (confirmed) {
      if (isLast) {
        moveWalker(points.length - 1);
        if (confirmed) {
          submit();
        } else {
          submitBtn.focus();
        }
      } else {
        show(current + 1, true);
      }
    };

    if (endsDimension(current)) {
      var info = discoveryFor(current);
      if (shown[info.dim] !== info.signature) {
        shown[info.dim] = info.signature;
        moveWalker(current + 1); // 先走到这一题的路标，再弹卡片
        openDiscovery(info, isLast, function (confirmed) {
          goOn(isLast ? confirmed : true);
        });
        return;
      }
    }
    goOn(false);
  };

  var submit = function () {
    if (form.requestSubmit) {
      form.requestSubmit(submitBtn);
    } else {
      form.submit();
    }
  };

  nextBtn.addEventListener("click", advance);
  prevBtn.addEventListener("click", function () {
    show(current - 1, true);
  });
  skipBtn.addEventListener("click", function (event) {
    event.stopPropagation();
    advance();
  });
  // 点气泡本身也可以跳过等待
  bubble.addEventListener("click", function () {
    if (pending) advance();
  });

  // 选了一个选项：小精灵回应
  form.addEventListener("change", function (event) {
    if (event.target.type !== "radio") return;
    errorBox.textContent = "";
    say(event.target.dataset.reply, pending !== null);
  });

  // 鼠标 / 手指点选项：约 1 秒后自动进入下一题（键盘触发的 click 事件 detail 为 0，不自动跳）
  form.querySelectorAll(".option-card").forEach(function (card) {
    card.addEventListener("click", function (event) {
      if (event.detail === 0 || event.target.tagName === "INPUT") return;
      cancelPending();
      var input = card.querySelector("input");
      say(input.dataset.reply, true);
      pending = setTimeout(advance, REPLY_DELAY);
    });
  });

  // 在选项上按 Enter：进入下一题（最后一题时先弹森林发现卡片），不直接提交整张表单
  form.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && event.target.type === "radio") {
      event.preventDefault();
      advance();
    }
  });

  form.addEventListener("submit", function (event) {
    cancelPending();
    for (var i = 0; i < steps.length; i++) {
      if (!answered(i)) {
        event.preventDefault();
        show(i, true);
        errorBox.textContent = form.dataset.pickHint;
        return;
      }
    }
    submitBtn.disabled = true; // 防止重复提交
  });

  // 出错后回到测试页（服务器保留了已选答案）：从第一道没答的题开始
  var start = 0;
  while (start < steps.length - 1 && answered(start)) start++;
  show(start, false);
})();
