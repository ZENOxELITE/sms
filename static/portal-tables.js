(function (root) {
  "use strict";

  const PAGE_SIZE = 20;

  function initializePortalTables(container) {
    container.querySelectorAll(".portal-card").forEach((card) => {
      const body = card.querySelector(".portal-table tbody");
      if (!body) return;

      const input = card.querySelector(".table-search");
      const status = card.querySelector(".table-page-status");
      const buttons = card.querySelectorAll("[data-page-change]");
      const emptyState = body.querySelector(".empty-state");
      const filterEmpty = body.querySelector(".filter-empty");
      const rows = Array.from(body.querySelectorAll("tr")).filter(
        (row) => !row.classList.contains("empty-state") &&
          !row.classList.contains("filter-empty")
      );
      let page = 0;

      function render() {
        const query = input ? input.value.trim().toLocaleLowerCase() : "";
        const matches = rows.filter((row) =>
          row.textContent.toLowerCase().includes(query)
        );
        const matchIndexes = new Map(matches.map((row, index) => [row, index]));
        const pageCount = Math.ceil(matches.length / PAGE_SIZE);
        page = Math.min(page, Math.max(0, pageCount - 1));
        const firstVisible = page * PAGE_SIZE;
        const endVisible = firstVisible + PAGE_SIZE;

        rows.forEach((row) => {
          const matchIndex = matchIndexes.get(row);
          row.hidden = matchIndex === undefined ||
            matchIndex < firstVisible || matchIndex >= endVisible;
        });
        if (emptyState) emptyState.hidden = rows.length > 0;
        if (filterEmpty) filterEmpty.hidden = rows.length === 0 || matches.length > 0;

        if (status) {
          status.textContent = matches.length === 0
            ? `Showing 0 of ${rows.length} records`
            : `Showing ${firstVisible + 1}-${Math.min(endVisible, matches.length)} of ${matches.length} records`;
        }
        buttons.forEach((button) => {
          const direction = Number(button.dataset.pageChange);
          button.disabled = direction < 0 ? page === 0 : page >= pageCount - 1;
        });
      }

      if (input) input.addEventListener("input", () => {
        page = 0;
        render();
      });
      buttons.forEach((button) => button.addEventListener("click", () => {
        page += Number(button.dataset.pageChange);
        render();
      }));
      render();
    });
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { initializePortalTables, PAGE_SIZE };
  } else {
    initializePortalTables(root.document);
  }
})(typeof globalThis === "undefined" ? this : globalThis);
