// 通用的"一步一题"向导（约会选选选、初见森林都在用）
//
// 用法：<form data-wizard data-step-label="第 {n} 题 / 共 {total} 题" data-pick-hint="先选一个吧">
//   每一题是一个 <fieldset data-step>，里面是单选框；
//   进度文字 [data-progress-text]、小脚印 [data-footprint]、错误提示 [data-wizard-error]、
//   按钮 [data-prev] [data-next] [data-submit]
// 加上 data-auto-advance：用鼠标或手指点选项后自动进入下一题（用键盘时仍然按"下一题"，避免方向键选择时乱跳）
// 没有 JavaScript 时，所有题目一起显示，也能直接提交
(function () {
  document.documentElement.classList.add("js");

  document.querySelectorAll("[data-wizard]").forEach(function (wizard) {
    var steps = Array.prototype.slice.call(wizard.querySelectorAll("[data-step]"));
    var footprints = wizard.querySelectorAll("[data-footprint]");
    var progressText = wizard.querySelector("[data-progress-text]");
    var errorBox = wizard.querySelector("[data-wizard-error]");
    var prevBtn = wizard.querySelector("[data-prev]");
    var nextBtn = wizard.querySelector("[data-next]");
    var submitBtn = wizard.querySelector("[data-submit]");
    var autoAdvance = wizard.hasAttribute("data-auto-advance");
    var reduceMotion = window.uslandReduceMotion ? window.uslandReduceMotion() : false;
    var current = 0;
    var advanceTimer = null;

    wizard.classList.add("is-js");

    var answered = function (i) {
      return !!steps[i].querySelector("input:checked");
    };

    var show = function (i) {
      current = i;
      steps.forEach(function (step, n) {
        step.hidden = n !== i;
      });
      // 进度：一串小脚印，答过的题点亮
      footprints.forEach(function (fp, n) {
        fp.classList.toggle("is-done", answered(n));
        fp.classList.toggle("is-current", n === i);
      });
      progressText.textContent = wizard.dataset.stepLabel.replace("{n}", i + 1).replace("{total}", steps.length);
      prevBtn.hidden = i === 0;
      nextBtn.hidden = i === steps.length - 1;
      submitBtn.hidden = i !== steps.length - 1;
      errorBox.textContent = "";
    };

    var focusStep = function () {
      var target = steps[current].querySelector("input:checked") || steps[current].querySelector("input");
      if (target) target.focus({ preventScroll: true });
    };

    var goNext = function () {
      if (!answered(current)) {
        errorBox.textContent = wizard.dataset.pickHint;
        return;
      }
      if (current < steps.length - 1) {
        show(current + 1);
        focusStep();
      }
    };

    nextBtn.addEventListener("click", goNext);
    prevBtn.addEventListener("click", function () {
      show(current - 1);
      focusStep();
    });

    wizard.addEventListener("change", function () {
      errorBox.textContent = "";
      if (footprints[current]) footprints[current].classList.add("is-done");
    });

    // 自动进入下一题：只在鼠标 / 手指点击时（键盘触发的 click 事件 detail 为 0）
    if (autoAdvance) {
      wizard.querySelectorAll(".option-card").forEach(function (card) {
        card.addEventListener("click", function (event) {
          if (event.detail === 0) return;
          clearTimeout(advanceTimer);
          advanceTimer = setTimeout(function () {
            if (current < steps.length - 1) {
              goNext();
            } else {
              submitBtn.focus();
            }
          }, reduceMotion ? 0 : 280); // 稍等一下，让人看到选中的效果
        });
      });
    }

    // 在选项上按 Enter：不是最后一题时去下一题，而不是直接提交整张表单
    wizard.addEventListener("keydown", function (event) {
      if (event.key === "Enter" && event.target.type === "radio" && current < steps.length - 1) {
        event.preventDefault();
        goNext();
      }
    });

    wizard.addEventListener("submit", function (event) {
      for (var i = 0; i < steps.length; i++) {
        if (!answered(i)) {
          event.preventDefault();
          show(i);
          errorBox.textContent = wizard.dataset.pickHint;
          return;
        }
      }
      submitBtn.disabled = true; // 防止重复提交
    });

    show(0);
  });
})();
