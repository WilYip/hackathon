// 回忆小屋页面：
// - 房间里的三个互动区域：相框 → 照片墙，相册 → 完整时间线，明信片 → 添加回忆
//   （发光层由 CSS 的 :hover / :focus-visible 控制；没有 JavaScript 时链接直接跳到对应位置）
// - 右下角"＋"打开添加回忆的窗口（字数统计、照片格式 / 大小检查和预览、防止重复提交）
// - 点照片看大图，Esc 或点背景关闭
(function () {
  var addDialog = document.getElementById("add-memory");
  var lightbox = document.getElementById("lightbox");
  if (!addDialog) return;
  // 全站声音管理器（static/js/sound.js）；万一没加载，用什么都不做的替身
  var noop = function () {};
  var sound = window.UslandSound || { play: noop, event: noop, seen: noop, next: noop, expectLive: noop };

  var open = function (dialog) {
    if (dialog.showModal && !dialog.open) dialog.showModal();
  };

  // 点弹窗外的背景关闭
  [addDialog, lightbox].forEach(function (dialog) {
    dialog.addEventListener("click", function (event) {
      if (event.target === dialog) {
        sound.play("ui_close");
        dialog.close();
      }
    });
  });

  // ---------- 照片墙 / 完整时间线：一次只显示一块 ----------
  var views = document.querySelectorAll("[data-memory-view]");
  function showView(name, focus) {
    views.forEach(function (view) {
      view.hidden = view.dataset.memoryView !== name;
      if (!view.hidden && focus) {
        view.scrollIntoView({ behavior: window.uslandReduceMotion && window.uslandReduceMotion() ? "auto" : "smooth" });
        view.focus({ preventScroll: true });
      }
    });
  }
  // 打开页面时：网址是 #photo-wall 就显示照片墙，否则显示时间线
  showView(location.hash === "#photo-wall" ? "photos" : "timeline", false);
  document.querySelectorAll("[data-show-view]").forEach(function (link) {
    link.addEventListener("click", function (event) {
      event.preventDefault();
      sound.play("memory_open");
      showView(link.dataset.showView, true);
      if (history.replaceState) history.replaceState(null, "", link.getAttribute("href"));
    });
  });

  // ---------- 添加回忆 ----------
  document.querySelectorAll("[data-open-add]").forEach(function (link) {
    link.addEventListener("click", function (event) {
      if (!addDialog.showModal) return; // 很旧的浏览器：跳到 #add-memory（CSS 会直接显示表单）
      event.preventDefault();
      open(addDialog);
      addDialog.querySelector("[data-note]").focus();
    });
  });

  // 提交出错后重新打开窗口，显示错误和已写的文字
  if (addDialog.hasAttribute("data-open-on-load")) open(addDialog);

  var form = addDialog.querySelector("[data-memory-form]");
  var note = form.querySelector("[data-note]");
  var count = form.querySelector("[data-note-count]");
  var photo = form.querySelector("[data-photo]");
  var preview = form.querySelector("[data-photo-preview]");
  var photoError = form.querySelector("[data-photo-error]");
  var allowed = ["image/jpeg", "image/png", "image/webp"];

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
      photoError.textContent = form.dataset.badType;
      photo.value = "";
      return;
    }
    if (file.size > parseInt(form.dataset.maxBytes, 10)) {
      photoError.textContent = form.dataset.tooLarge;
      photo.value = "";
      return;
    }
    preview.src = URL.createObjectURL(file);
    preview.hidden = false;
  });

  form.addEventListener("submit", function () {
    form.querySelector("[data-save]").disabled = true;
  });

  // ---------- 照片大图 ----------
  var bigImg = lightbox.querySelector("[data-lightbox-img]");
  document.querySelectorAll("[data-lightbox]").forEach(function (button) {
    button.addEventListener("click", function () {
      bigImg.src = button.dataset.lightbox;
      sound.play("memory_open");
      open(lightbox);
    });
  });
})();
