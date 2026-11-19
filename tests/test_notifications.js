const assert = require("node:assert/strict");
const test = require("node:test");
const { toastFor, formatCount } = require("../static/notifications.js");

const summary = {
  unread: 2,
  latest: [
    { id: 9, title: "Exam week", body: "Exams start Monday" },
    { id: 8, title: "Fee reminder", body: "Pay by Friday" },
  ],
};

test("pops up the newest unread notification once", () => {
  const toast = toastFor(summary, null, false);
  assert.equal(toast.id, 9);
  assert.equal(toast.heading, "2 unread notifications");
  assert.equal(toast.title, "Exam week");
  assert.equal(toastFor(summary, "9", false), null);
});

test("pops up again when a newer notification arrives", () => {
  const newer = { unread: 3, latest: [{ id: 10, title: "Holiday" }, ...summary.latest] };
  assert.equal(toastFor(newer, "9", false).title, "Holiday");
});

test("uses singular wording for one notification", () => {
  const one = { unread: 1, latest: [summary.latest[0]] };
  assert.equal(toastFor(one, null, false).heading, "New notification");
});

test("stays quiet with nothing unread or on the notifications page", () => {
  assert.equal(toastFor({ unread: 0, latest: [] }, null, false), null);
  assert.equal(toastFor(summary, null, true), null);
});

test("caps the badge text", () => {
  assert.equal(formatCount(3), "3");
  assert.equal(formatCount(150), "99+");
});
