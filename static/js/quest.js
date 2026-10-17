// 约会选选选页面脚本
// - 一步一题的选择向导在 static/js/wizard.js（没有 JavaScript 时四个问题一起显示，也能提交）
// - 每 4 秒查一次状态，变了就刷新（选择途中不刷新，免得打断）
// - 完成表单：字数统计、照片格式 / 大小检查和预览、防止重复提交
// - 完成后撒花
(function () {
  document.documentElement.classList.add("js");
  var root = document.querySelector("[data-quest]");
  if (!root) return;
  var reduceMotion = window.uslandReduceMotion ? window.uslandReduceMotion() : false;
  // 全站声音管理器（static/js/sound.js）；万一没加载，用什么都不做的替身
  var noop = function () {};
  var sound = window.UslandSound || { play: noop, event: noop, seen: noop, next: noop, expectLive: noop };

  // ---------- 结束这一轮前确认 ----------
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });

  // ---------- 一步一题 ----------
  // 由通用的 static/js/wizard.js 负责（页面上先加载 wizard.js）。这里只需要知道页面上有没有向导：
  // 正在一步一题选择时，下面的状态轮询不刷新页面，免得打断。
  var wizard = document.querySelector("[data-wizard]");

  // ---------- 完成表单 ----------
  var showComplete = document.querySelector("[data-show-complete]");
  var completeForm = document.querySelector("[data-complete-form]");
  if (completeForm) {
    var note = completeForm.querySelector("[data-note]");
    var count = completeForm.querySelector("[data-note-count]");
    var photo = completeForm.querySelector("[data-photo]");
    var preview = completeForm.querySelector("[data-photo-preview]");
    var photoError = completeForm.querySelector("[data-photo-error]");
    var saveBtn = completeForm.querySelector("[data-save-memory]");
    var allowed = ["image/jpeg", "image/png", "image/webp"];

    if (showComplete) {
      showComplete.addEventListener("click", function () {
        completeForm.classList.remove("js-collapsed");
        showComplete.hidden = true;
        note.focus();
      });
    }

    note.addEventListener("input", function () {
      count.textContent = note.value.length;
    });

    // 选照片后先在浏览器里检查格式和大小（服务器还会再检查一次）
    photo.addEventListener("change", function () {
      photoError.textContent = "";
      preview.hidden = true;
      var file = photo.files[0];
      if (!file) return;
      if (allowed.indexOf(file.type) === -1) {
        photoError.textContent = completeForm.dataset.badType;
        photo.value = "";
        return;
      }
      if (file.size > parseInt(completeForm.dataset.maxBytes, 10)) {
        photoError.textContent = completeForm.dataset.tooLarge;
        photo.value = "";
        return;
      }
      preview.src = URL.createObjectURL(file);
      preview.hidden = false;
    });

    completeForm.addEventListener("submit", function () {
      saveBtn.disabled = true; // 防止上传慢时重复点击
    });
  }

  // ---------- 撒花 ----------
  var confetti = document.querySelector("[data-confetti]");
  if (confetti && !reduceMotion) {
    // 第三版配色（static/usland/tokens.css）：琥珀、鼠尾草绿、陶土、海湾、沙色
    var colors = ["#E6B975", "#7F9279", "#B97870", "#6F9394", "#D8C7AD"];
    var layer = document.createElement("div");
    layer.className = "confetti-layer";
    layer.setAttribute("aria-hidden", "true");
    for (var i = 0; i < 60; i++) {
      var piece = document.createElement("span");
      piece.className = "confetti";
      piece.style.left = Math.random() * 100 + "%";
      piece.style.background = colors[i % colors.length];
      piece.style.animationDelay = Math.random() * 0.6 + "s";
      piece.style.animationDuration = 1.8 + Math.random() * 1.2 + "s";
      piece.style.setProperty("--spin", Math.round(Math.random() * 720 - 360) + "deg");
      layer.appendChild(piece);
    }
    document.body.appendChild(layer);
    setTimeout(function () {
      layer.remove();
    }, 3800);
  }

  // ---------- 状态轮询 ----------
  // 正在一步一题选择时不轮询：对方选好也不会打断你（提交后自然会看到最新状态）
  var stateUrl = root.dataset.stateUrl;
  if (stateUrl && !wizard) {
    var version = root.dataset.version;
    var check = function () {
      if (document.hidden) return;
      // 正在填写完成表单时也不刷新，免得写到一半的文字丢失
      if (completeForm && !completeForm.classList.contains("js-collapsed") && note.value.trim()) return;
      fetch(stateUrl, { headers: { Accept: "application/json" } })
        .then(function (resp) {
          if (resp.status === 401) {
            window.location.reload();
            return null;
          }
          return resp.ok ? resp.json() : null;
        })
        .then(function (data) {
          if (!data || data.version === version) return;
          sound.expectLive(); // 状态变了：刷新后的页面上的事件音（推荐出来了、对方提议了……）可以播放
          if (data.done_url && window.location.search.indexOf("done=") === -1) {
            window.location.href = data.done_url; // 另一半刚完成任务：一起看庆祝页
          } else {
            window.location.reload();
          }
        })
        .catch(function () {
          // 网络暂时不通，下次再试
        });
    };
    setInterval(check, 4000);
    document.addEventListener("visibilitychange", check);
  }
})();
