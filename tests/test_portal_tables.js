const assert = require("node:assert/strict");
const test = require("node:test");
const { initializePortalTables, PAGE_SIZE } = require("../static/portal-tables.js");

class FakeClassList {
  constructor(...classes) {
    this.classes = new Set(classes);
  }

  contains(className) {
    return this.classes.has(className);
  }
}

class FakeRow {
  constructor(text, ...classes) {
    this.textContent = text;
    this.classList = new FakeClassList(...classes);
    this.hidden = false;
  }
}

class FakeButton {
  constructor(direction) {
    this.dataset = { pageChange: String(direction) };
    this.disabled = false;
    this.listeners = {};
  }

  addEventListener(event, callback) {
    this.listeners[event] = callback;
  }

  click() {
    this.listeners.click();
  }
}

function makeCard(records) {
  const rows = records.map((record) => new FakeRow(record));
  const input = {
    value: "",
    addEventListener(_event, callback) {
      this.onInput = callback;
    },
  };
  const status = { textContent: "" };
  const previous = new FakeButton(-1);
  const next = new FakeButton(1);
  const emptyState = new FakeRow("No records", "empty-state");
  const filterEmpty = new FakeRow("No matches", "filter-empty");
  const body = {
    querySelector(selector) {
      return selector === ".empty-state" ? emptyState : filterEmpty;
    },
    querySelectorAll() {
      return [...rows, emptyState, filterEmpty];
    },
  };
  const card = {
    querySelector(selector) {
      return {
        ".portal-table tbody": body,
        ".table-search": input,
        ".table-page-status": status,
      }[selector] || null;
    },
    querySelectorAll() {
      return [previous, next];
    },
  };
  return { card, rows, input, status, previous, next, emptyState, filterEmpty };
}

test("portal tables paginate at 20 rows and filter across all pages", () => {
  assert.equal(PAGE_SIZE, 20);
  const table = makeCard(Array.from({ length: 45 }, (_, index) => `Student ${index + 1}`));
  initializePortalTables({ querySelectorAll: () => [table.card] });

  assert.equal(table.rows.filter((row) => !row.hidden).length, 20);
  assert.equal(table.status.textContent, "Showing 1-20 of 45 records");
  assert.equal(table.previous.disabled, true);
  assert.equal(table.next.disabled, false);

  table.next.click();
  assert.equal(table.rows.filter((row) => !row.hidden).length, 20);
  assert.equal(table.status.textContent, "Showing 21-40 of 45 records");

  table.input.value = "Student 44";
  table.input.onInput();
  assert.deepEqual(table.rows.filter((row) => !row.hidden).map((row) => row.textContent), ["Student 44"]);
  assert.equal(table.status.textContent, "Showing 1-1 of 1 records");
  assert.equal(table.next.disabled, true);

  table.input.value = "missing";
  table.input.onInput();
  assert.equal(table.rows.filter((row) => !row.hidden).length, 0);
  assert.equal(table.filterEmpty.hidden, false);
});
