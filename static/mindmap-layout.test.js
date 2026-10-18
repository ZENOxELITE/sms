(() => {
  const cases = [
    ["1-node site", window.mindmapFixtures.oneNode],
    ["2-page site", window.mindmapFixtures.twoPages],
    ["30-page test site", window.mindmapFixtures.thirtyPages],
    ["40-flat-pages site", window.mindmapFixtures.fortyFlatPages]
  ];
  const failed = cases.filter(([, data]) => !window.mindmapTest.checkNoOverlaps(data)).map(([name]) => name);
  const uncentered = [window.mindmapFixtures.oneNode, window.mindmapFixtures.twoPages]
    .some((data) => !window.mindmapTest.checkCentered(data));
  if (failed.length || uncentered) {
    document.body.dataset.layoutTests = "failed";
    document.querySelector("#map-details").textContent = failed.length
      ? `Overlapping labels found: ${failed.join(", ")}.`
      : "Small-map centering check failed.";
    throw new Error(failed.length ? `Map collision tests failed for ${failed.join(", ")}.` : "Map centering test failed.");
  }
  document.body.dataset.layoutTests = "passed";
  document.querySelector("#map-details").textContent = "Centering and collision checks passed for 1-, 2-, 30- and 40-page sites.";
})();
