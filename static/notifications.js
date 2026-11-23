(function (root) {
  "use strict";

  const POLL_INTERVAL_MS = 15000;
  const TOAST_DURATION_MS = 9000;
  const TOASTED_KEY = "sms-last-toasted-notification";

  function formatCount(count) {
    return count > 99 ? "99+" : String(count);
  }

  // Decides whether a pop-up should appear for the newest unread announcement.
  // It pops up once per announcement, so moving between pages does not repeat it.
  function toastFor(summary, lastToastedId, onNotificationsPage) {
    if (onNotificationsPage || !summary || !summary.unread) return null;
    const newest = (summary.latest || [])[0];
    if (!newest || String(newest.id) === String(lastToastedId)) return null;
    return {
      id: newest.id,
      heading: summary.unread === 1
        ? "New notification"
        : `${summary.unread} unread notifications`,
      title: newest.title || "Announcement",
      body: newest.body || "",
    };
  }

  function readStorage(storage, key) {
    try { return storage ? storage.getItem(key) : null; } catch (_error) { return null; }
  }

  function writeStorage(storage, key, value) {
    try { if (storage) storage.setItem(key, value); } catch (_error) { /* storage disabled */ }
  }

  function initializeNotifications(doc, win) {
    const bell = doc.querySelector("[data-notification-root]");
    if (!bell) return;
    const toastHost = doc.querySelector("[data-notification-toasts]");
    const onNotificationsPage = bell.dataset.onNotificationsPage === "true";
    const baseTitle = doc.title;
    let unread = Number(bell.dataset.unread) || 0;
    let timer = null;
    const storage = win.sessionStorage;

    function render(count) {
      unread = count;
      doc.querySelectorAll("[data-notification-count]").forEach((badge) => {
        badge.textContent = formatCount(count);
        badge.hidden = count === 0;
      });
      bell.setAttribute("aria-label", count ? `Notifications: ${count} unread` : "Notifications");
      doc.title = count ? `(${formatCount(count)}) ${baseTitle}` : baseTitle;
    }

    function ring() {
      bell.classList.remove("ringing");
      void bell.offsetWidth; // restart the animation
      bell.classList.add("ringing");
    }

    function showToast(toast) {
      writeStorage(storage, TOASTED_KEY, String(toast.id));
      ring();
      if (!toastHost) return;
      const card = doc.createElement("div");
      card.className = "notification-toast";
      card.setAttribute("role", "status");

      const heading = doc.createElement("strong");
      heading.textContent = toast.heading;
      const title = doc.createElement("p");
      title.className = "notification-toast-title";
      title.textContent = toast.title;
      const body = doc.createElement("p");
      body.className = "notification-toast-body";
      body.textContent = toast.body.length > 140 ? `${toast.body.slice(0, 137)}...` : toast.body;
      const actions = doc.createElement("div");
      actions.className = "notification-toast-actions";
      const view = doc.createElement("a");
      view.href = bell.dataset.notificationsUrl;
      view.textContent = "View";
      const close = doc.createElement("button");
      close.type = "button";
      close.textContent = "Dismiss";
      close.addEventListener("click", () => card.remove());
      actions.append(view, close);

      card.append(heading, title);
      if (toast.body) card.append(body);
      card.append(actions);
      toastHost.append(card);
      win.setTimeout(() => card.remove(), TOAST_DURATION_MS);
    }

    function handle(summary) {
      const previous = unread;
      render(summary.unread || 0);
      const toast = toastFor(summary, readStorage(storage, TOASTED_KEY), onNotificationsPage);
      if (toast) showToast(toast);
      else if ((summary.unread || 0) > previous) ring();
    }

    async function poll() {
      try {
        const response = await win.fetch(bell.dataset.summaryUrl, {
          headers: { Accept: "application/json" },
          credentials: "same-origin",
        });
        if (response.status === 401) {
          stop();
          return;
        }
        if (!response.ok) return;
        const summary = await response.json();
        if (summary.status === "ok") handle(summary);
      } catch (_error) {
        // Network hiccup: try again on the next interval.
      }
    }

    function start() {
      if (timer === null) timer = win.setInterval(poll, POLL_INTERVAL_MS);
    }

    function stop() {
      if (timer !== null) win.clearInterval(timer);
      timer = null;
    }

    let initialLatest = [];
    const latestScript = doc.getElementById("notification-latest");
    try {
      initialLatest = JSON.parse(latestScript ? latestScript.textContent : "[]");
    } catch (_error) {
      initialLatest = [];
    }
    handle({ unread, latest: initialLatest });

    doc.addEventListener("visibilitychange", () => {
      if (doc.hidden) {
        stop();
      } else {
        poll();
        start();
      }
    });
    if (!doc.hidden) start();
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { toastFor, formatCount };
  } else {
    initializeNotifications(root.document, root);
  }
})(typeof globalThis === "undefined" ? this : globalThis);
