(function () {
  "use strict";

  document.querySelectorAll("[data-expert-review]").forEach(function (details) {
    var summary = details.querySelector("summary");
    var panel = details.querySelector(".expert-review-panel");
    var hovering = false;
    var pinned = false;
    var restoringFocus = false;

    function positionPanel() {
      panel.style.setProperty("--review-panel-left", "0px");
      var bounds = panel.getBoundingClientRect();
      var rightOverflow = Math.max(0, bounds.right - window.innerWidth + 16);
      var leftOverflow = Math.max(0, 16 - (bounds.left - rightOverflow));
      panel.style.setProperty("--review-panel-left", String(leftOverflow - rightOverflow) + "px");
    }

    function open() {
      details.open = true;
      positionPanel();
    }

    function close(restoreFocus) {
      pinned = false;
      details.open = false;
      if (restoreFocus && details.contains(document.activeElement)) {
        restoringFocus = true;
        summary.focus();
        restoringFocus = false;
      }
    }

    details.addEventListener("pointerenter", function (event) {
      if (event.pointerType === "mouse") {
        hovering = true;
        open();
      }
    });

    details.addEventListener("pointerleave", function (event) {
      if (event.pointerType === "mouse") {
        hovering = false;
        if (!pinned && !details.contains(document.activeElement)) {
          close(false);
        }
      }
    });

    details.addEventListener("focusin", function () {
      if (!restoringFocus) {
        open();
      }
    });

    details.addEventListener("focusout", function () {
      window.requestAnimationFrame(function () {
        if (!details.contains(document.activeElement) && !hovering) {
          close(false);
        }
      });
    });

    summary.addEventListener("click", function (event) {
      event.preventDefault();
      if (pinned) {
        close(false);
      } else {
        pinned = true;
        open();
      }
    });

    document.addEventListener("pointerdown", function (event) {
      if (!details.contains(event.target)) {
        close(false);
      }
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && details.open) {
        event.preventDefault();
        close(true);
      }
    });

    window.addEventListener("resize", function () {
      if (details.open) {
        positionPanel();
      }
    });
  });
})();
