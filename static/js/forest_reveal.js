// 初见森林结果揭晓（刚测完时）：动物先藏在灌木丛后面
//   第 1 次点灌木丛：灌木丛摇晃，提示"再点一次"
//   第 2 次点：动物蹦出来，飘落树叶，结果文字出现，焦点移到动物名字上
// 随时可以按"直接揭晓"；减少动态效果时没有摇晃、蹦跳和树叶，但步骤一样。
// 没有 JavaScript 时页面直接显示结果（这里不运行，灌木丛按钮也不显示）。
(function () {
  var article = document.querySelector("[data-reveal]");
  if (!article) return;
  document.documentElement.classList.add("js");

  var bush = article.querySelector("[data-bush]");
  var hint = article.querySelector("[data-bush-hint]");
  var skip = article.querySelector("[data-reveal-skip]");
  var leafFall = article.querySelector("[data-leaf-fall]");
  var stage = article.querySelector("[data-bush-stage]");
  var name = article.querySelector("[data-result-name]");
  var clicks = 0;
  // 全站声音管理器（static/js/sound.js）；万一没加载，用什么都不做的替身
  var noop = function () {};
  var sound = window.UslandSound || { play: noop, event: noop, seen: noop, next: noop, expectLive: noop };

  var reduceMotion = function () {
    return window.uslandReduceMotion ? window.uslandReduceMotion() : false;
  };

  // 先把结果藏起来（灌木丛后面的动物、文字、猜猜看卡片）
  document.body.classList.add("is-veiled");

  var dropLeaves = function () {
    if (reduceMotion()) return;
    for (var i = 0; i < 12; i++) {
      var leaf = document.createElement("span");
      leaf.className = "falling-leaf";
      leaf.style.left = 8 + Math.random() * 84 + "%";
      leaf.style.animationDelay = Math.random() * 0.5 + "s";
      leaf.style.animationDuration = 1.6 + Math.random() * 1.2 + "s";
      leaf.style.setProperty("--drift", (Math.random() * 60 - 30).toFixed(0) + "px");
      leaf.style.setProperty("--spin", (Math.random() * 540 - 270).toFixed(0) + "deg");
      leafFall.appendChild(leaf);
    }
    setTimeout(function () {
      leafFall.innerHTML = "";
    }, 3500);
  };

  var reveal = function () {
    if (!document.body.classList.contains("is-veiled")) return;
    document.body.classList.remove("is-veiled");
    stage.classList.remove("is-shaking");
    stage.classList.add("is-revealed");
    hint.textContent = hint.dataset.done;
    bush.disabled = true;
    bush.setAttribute("aria-hidden", "true");
    skip.hidden = true;
    sound.play("animal_reveal"); // 个人动物结果
    dropLeaves();
    name.focus({ preventScroll: true });
  };

  bush.addEventListener("click", function () {
    clicks += 1;
    if (clicks === 1) {
      // 第一次：摇一摇
      hint.textContent = hint.dataset.hint2;
      sound.play("ui_select");
      if (!reduceMotion()) {
        stage.classList.remove("is-shaking");
        void stage.offsetWidth;
        stage.classList.add("is-shaking");
      }
    } else {
      reveal();
    }
  });

  skip.addEventListener("click", reveal);
})();
