(() => {
  const svg = d3.select("#mindmap");
  const details = document.querySelector("#map-details");
  const search = document.querySelector("#map-search");
  const filter = document.querySelector("#map-filter");
  const problemsOnly = document.querySelector("#problems-only");
  const palette = ["#a7aaa9", "#c4c4bb", "#b4c5bd"];
  const state = {
    layout: null,
    selected: null,
    query: "",
    filter: "all",
    problemsOnly: false,
    root: d3.hierarchy(window.mindmapData),
    nodes: [],
    width: 0,
    height: 0,
    treeOffsetX: 0,
    treeOffsetY: 0,
    initialized: false
  };
  const outer = svg.append("g").attr("class", "map-viewport");
  const linkLayer = outer.append("g").attr("class", "map-links");
  const nodeLayer = outer.append("g").attr("class", "map-nodes");
  const zoom = d3.zoom().scaleExtent([0.08, 3]).on("zoom", (event) => {
    outer.attr("transform", event.transform);
  });
  svg.call(zoom);
  state.root.each((node) => {
    node.id = node.ancestors().reverse().map((ancestor) => ancestor.data.name).join("/");
  });

  const countNodes = (node) => 1 + (node.children || []).reduce((sum, child) => sum + countNodes(child), 0);
  const hasProblem = (node) => Boolean(node && node.data.problem) ||
    (node ? (node.children || node._children || []).some(hasProblem) : false);
  const wordLines = (text, maxChars) => {
    const lines = [];
    let line = "";
    text.split(/\s+/).forEach((word) => {
      const next = line ? `${line} ${word}` : word;
      if (line && next.length > maxChars) {
        lines.push(line);
        line = word;
      } else {
        line = next;
      }
    });
    if (line) lines.push(line);
    return lines;
  };
  const boxSize = (node) => {
    const root = node.depth === 0;
    const maxChars = root ? 20 : 28;
    const lines = wordLines(node.data.name, maxChars);
    const moreWidth = node.data._hiddenCount ? 60 : 0;
    const width = root ? 205 : Math.max(72, Math.min(210, Math.max(...lines.map((line) => line.length)) * 6.7 + 22)) + moreWidth;
    const height = Math.max(root ? 54 : 32, lines.length * 13 + 14) + (node.data._hiddenCount ? 12 : 0);
    return { width, height, lines };
  };
  const rootCircleRadius = (node) => Math.max(...boxSize(node).lines.map((line) => line.length * 6.7)) / 2 + 18;
  const filterIsActive = () => Boolean(state.query || state.filter !== "all" || state.problemsOnly);
  const nodeMatches = (node) => {
    const typeMatches = state.filter === "all" ||
      (state.filter === "actors" && node.data.type === "actor") ||
      (state.filter === "pages" && node.data.type === "page");
    const textMatches = !state.query || `${node.data.name} ${node.data.type || ""}`.toLowerCase().includes(state.query);
    const problemMatches = !state.problemsOnly || node.data.problem === true;
    return typeMatches && textMatches && problemMatches;
  };
  const makeVisibleData = (source) => {
    const sourceChildren = source.children || (filterIsActive() ? source._children : null) || [];
    const children = sourceChildren.map(makeVisibleData).filter(Boolean);
    if (source !== state.root && !nodeMatches(source) && children.length === 0) return null;
    const data = {
      ...source.data,
      _key: source.id,
      _source: source,
      _hiddenCount: source._children?.length || 0
    };
    delete data.children;
    delete data._children;
    if (children.length) data.children = children;
    return data;
  };
  const branchColor = (node) => {
    let branch = node;
    while (branch.parent && branch.parent.depth > 0) branch = branch.parent;
    const index = branch.parent ? branch.parent.children.indexOf(branch) : 0;
    return palette[index % palette.length];
  };
  const ringRadii = (root) => {
    const levels = d3.group(root.descendants(), (node) => node.depth);
    const sizes = new Map();
    levels.forEach((nodes, depth) => {
      sizes.set(depth, {
        width: Math.max(...nodes.map((node) => boxSize(node).width)),
        height: Math.max(...nodes.map((node) => boxSize(node).height)),
        totalWidth: nodes.reduce((sum, node) => sum + boxSize(node).width + 16, 0)
      });
    });
    const rings = [0];
    for (let depth = 1; depth <= root.height; depth += 1) {
      const previous = sizes.get(depth - 1);
      const current = sizes.get(depth);
      const circumferenceRadius = current.totalWidth / (2 * Math.PI);
      if (depth === 1) {
        rings[depth] = Math.max(circumferenceRadius, (previous.width + current.width) / 2 + 24, 105);
      } else {
        rings[depth] = Math.max(circumferenceRadius, rings[depth - 1] +
          (previous.width + current.width) / 2 + (previous.height + current.height) / 2 + 18);
      }
    }
    return rings;
  };
  const arrangeRadial = (root) => {
    const rings = ringRadii(root);
    const radius = rings.at(-1) || 0;
    d3.tree()
      .size([2 * Math.PI, radius || 1])
      .separation((a, b) => {
        const aWeight = a.children ? a.value : 1;
        const bWeight = b.children ? b.value : 1;
        return (a.parent === b.parent ? 1 : 1.25) * (1 + Math.log2(aWeight + bWeight) * 0.15);
      })(root);
    const byRing = d3.group(root.descendants().filter((node) => node.depth > 0), (node) => node.depth);
    byRing.forEach((nodes, depth) => {
      nodes.sort((a, b) => a.x - b.x);
      const gaps = nodes.map((node, index) => {
        const next = nodes[(index + 1) % nodes.length];
        return {
          min: ((boxSize(node).width + boxSize(next).width) / 2 + 14) / rings[depth],
          ideal: ((next.x - node.x + 2 * Math.PI) % (2 * Math.PI))
        };
      });
      const remaining = Math.max(0, 2 * Math.PI - gaps.reduce((sum, gap) => sum + gap.min, 0));
      const weights = gaps.map((gap) => Math.max(0, gap.ideal - gap.min));
      const totalWeight = weights.reduce((sum, weight) => sum + weight, 0);
      let angle = nodes[0].x;
      nodes.forEach((node, index) => {
        node.angle = angle;
        node.radius = rings[depth];
        node.x = Math.cos(angle) * node.radius;
        node.y = Math.sin(angle) * node.radius;
        angle += gaps[index].min + remaining * (totalWeight ? weights[index] / totalWeight : 1 / nodes.length);
      });
    });
    root.angle = 0;
    root.radius = 0;
    root.x = 0;
    root.y = 0;
    return { radius, rings };
  };
  const treeLinkPath = (link) => {
    const sourceX = link.source.y + state.treeOffsetX;
    const targetX = link.target.y + state.treeOffsetX;
    const sourceY = link.source.x + state.treeOffsetY;
    const targetY = link.target.x + state.treeOffsetY;
    const middle = (sourceX + targetX) / 2;
    return `M${sourceX},${sourceY}C${middle},${sourceY} ${middle},${targetY} ${targetX},${targetY}`;
  };
  const radialLinkPath = (link) => {
    const radial = d3.linkRadial().angle((node) => node.angle + Math.PI / 2).radius((node) => node.radius);
    return radial(link);
  };
  const fitToView = (contentWidth, contentHeight) => {
    const scale = Math.min(state.width / contentWidth, state.height / contentHeight);
    svg.call(zoom.transform, d3.zoomIdentity.translate(state.width / 2, state.height / 2).scale(Math.max(0.08, Math.min(1, scale))));
  };
  const render = (animate = false) => {
    const bounds = svg.node().getBoundingClientRect();
    state.width = Math.max(1, bounds.width);
    state.height = Math.max(1, bounds.height);
    svg.attr("viewBox", `0 0 ${state.width} ${state.height}`);
    const data = makeVisibleData(state.root);
    const root = d3.hierarchy(data).sum((item) => item.children ? 0 : 1);
    root.each((node) => { node.id = node.data._key; });
    let extent;
    let contentWidth;
    let contentHeight;
    if (state.layout === "radial") {
      state.treeOffsetX = 0;
      state.treeOffsetY = 0;
      const radial = arrangeRadial(root);
      extent = radial.radius + Math.max(...root.descendants().map((node) => boxSize(node).width)) + 36;
      contentWidth = extent * 2;
      contentHeight = extent * 2;
    } else {
      d3.tree().nodeSize([58, 235]).separation((a, b) => a.parent === b.parent ? 1 : 1.2)(root);
      root.each((node) => { node.angle = 0; node.radius = 0; });
      const minX = d3.min(root.descendants(), (node) => node.y - (node.depth ? 0 : boxSize(node).width / 2));
      const maxX = d3.max(root.descendants(), (node) => node.y + (node.depth ? boxSize(node).width + 8 : boxSize(node).width / 2));
      const minY = d3.min(root.descendants(), (node) => node.x - boxSize(node).height / 2);
      const maxY = d3.max(root.descendants(), (node) => node.x + boxSize(node).height / 2);
      contentWidth = maxX - minX + 36;
      contentHeight = maxY - minY + 36;
      extent = Math.max(contentWidth, contentHeight) / 2;
      state.treeOffsetX = -(minX + maxX) / 2;
      state.treeOffsetY = -(minY + maxY) / 2;
    }
    state.nodes = root.descendants();
    const links = root.links();
    const linkSelection = linkLayer.selectAll("path").data(links, (link) => link.target.id);
    linkSelection.exit().remove();
    const linkEnter = linkSelection.enter().append("path").attr("class", "map-link");
    const renderedLinks = linkEnter.merge(linkSelection)
      .attr("class", (link) => `map-link ${hasProblem(link.target.data._source) ? "broken" : ""}`)
      .attr("stroke", (link) => hasProblem(link.target.data._source) ? "#a34b3f" : branchColor(link.target))
      .attr("stroke-width", (link) => [6, 4, 3, 2, 1][Math.min(link.target.depth - 1, 4)]);
    if (animate) renderedLinks.transition().duration(300).attr("d", state.layout === "radial" ? radialLinkPath : treeLinkPath);
    else renderedLinks.attr("d", state.layout === "radial" ? radialLinkPath : treeLinkPath);
    const nodeSelection = nodeLayer.selectAll("g.map-node").data(state.nodes, (node) => node.id);
    nodeSelection.exit().remove();
    const nodeEnter = nodeSelection.enter().append("g").attr("class", "map-node").attr("tabindex", 0).attr("role", "button");
    nodeEnter.append("rect");
    nodeEnter.append("circle").attr("class", "root-circle");
    nodeEnter.append("text").attr("class", "node-label");
    nodeEnter.append("circle").attr("class", "problem-dot").attr("r", 4);
    nodeEnter.append("text").attr("class", "node-more");
    const nodes = nodeEnter.merge(nodeSelection);
    nodes.attr("aria-label", (node) => node.data.name)
      .on("click", (event, node) => {
        event.stopPropagation();
        state.selected = node.id;
        details.textContent = `${node.data.name} · ${node.data.type || "item"}`;
        if (node.data._source.children || node.data._source._children) {
          const source = node.data._source;
          if (source.children) {
            source._children = source.children;
            source.children = null;
          } else {
            source.children = source._children;
            source._children = null;
          }
          render(true);
        } else {
          details.textContent = `${node.data.name} · ${node.data.type || "item"} · ${countNodes(node.data)} item${countNodes(node.data) === 1 ? "" : "s"}`;
          render();
        }
      })
      .on("keydown", (event, node) => {
        if (["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp"].includes(event.key)) {
          event.preventDefault();
          const current = state.nodes.findIndex((item) => item.id === node.id);
          const next = ["ArrowRight", "ArrowDown"].includes(event.key) ? current + 1 : current - 1;
          nodeLayer.selectAll("g.map-node").nodes()[(next + state.nodes.length) % state.nodes.length]?.focus();
        } else if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          d3.select(event.currentTarget).dispatch("click");
        }
      });
    nodes.attr("class", (node) => `map-node ${node.data.type || ""} ${node.id === state.selected ? "selected" : ""}`);
    const nodeTransform = (node) => {
      const x = state.layout === "radial" ? node.x : node.y + state.treeOffsetX;
      const y = state.layout === "radial" ? node.y : node.x + state.treeOffsetY;
      return `translate(${x},${y})`;
    };
    if (animate) nodes.transition().duration(300).attr("transform", nodeTransform);
    else nodes.attr("transform", nodeTransform);
    nodes.each(function(node) {
        const group = d3.select(this);
        const size = boxSize(node);
        const radial = state.layout === "radial";
        const x = node.depth === 0 ? -size.width / 2 : radial && Math.cos(node.angle) < 0 ? -size.width : radial ? 0 : 8;
        const y = -size.height / 2;
        group.select("rect").attr("x", x).attr("y", y).attr("width", size.width).attr("height", size.height)
          .attr("class", `${node.data.type || ""} ${node.data.problem ? "broken" : ""} ${node.depth === 0 ? "root-box" : ""}`)
          .attr("fill", node.depth === 0 ? "#26364a" : branchColor(node))
          .style("display", radial && node.depth === 0 ? "none" : null);
        group.select(".root-circle").attr("r", rootCircleRadius(node))
          .attr("fill", "#26364a").attr("stroke", "#26364a")
          .style("display", radial && node.depth === 0 ? null : "none");
        const label = group.select("text.node-label")
          .attr("x", radial && node.depth === 0 ? 0 : x + 10)
          .attr("text-anchor", radial && node.depth === 0 ? "middle" : "start")
          .attr("y", -((size.lines.length - 1) * 6))
          .attr("fill", node.depth === 0 ? "#fff" : "#26364a");
        label.selectAll("tspan").remove();
        size.lines.forEach((line, index) => {
          label.append("tspan").attr("x", radial && node.depth === 0 ? 0 : x + 10)
            .attr("dy", index === 0 ? "0.35em" : "1.15em").text(line);
        });
        group.select(".problem-dot").attr("cx", x + size.width - 7).attr("cy", y + 7)
          .style("display", hasProblem(node.data._source) && (node.data.problem || node.data._source._children) ? null : "none");
        group.select(".node-more").attr("x", x + size.width - 8).attr("y", size.height / 2 - 5)
          .attr("text-anchor", "end")
          .text(node.data._hiddenCount ? `+${node.data._hiddenCount} more` : "");
      });
    nodeLayer.attr("transform", null);
    linkLayer.attr("transform", null);
    if (!state.initialized || !animate) fitToView(contentWidth, contentHeight);
    state.initialized = true;
    if (!state.selected) details.textContent = "Select a node to see its details.";
  };

  const setLayout = (layout) => {
    state.layout = layout;
    sessionStorage.setItem("mindmap-layout", layout);
    document.querySelectorAll("[data-layout-choice]").forEach((button) => {
      button.classList.toggle("active", button.dataset.layoutChoice === layout);
      button.setAttribute("aria-pressed", String(button.dataset.layoutChoice === layout));
    });
    render(true);
  };
  document.querySelectorAll("[data-layout-choice]").forEach((button) => button.addEventListener("click", () => setLayout(button.dataset.layoutChoice)));
  search.addEventListener("input", () => { state.query = search.value.trim().toLowerCase(); render(); });
  filter.addEventListener("change", () => { state.filter = filter.value; render(); });
  problemsOnly.addEventListener("change", () => { state.problemsOnly = problemsOnly.checked; render(); });
  document.querySelector("#download-png").addEventListener("click", () => {
    const clone = svg.node().cloneNode(true);
    const bounds = svg.node().getBoundingClientRect();
    clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    clone.setAttribute("width", bounds.width);
    clone.setAttribute("height", bounds.height);
    clone.style.background = "#f3f0e8";
    const style = document.createElementNS("http://www.w3.org/2000/svg", "style");
    style.textContent = ".map-link{fill:none;stroke-opacity:.68}.map-node rect{stroke:#f3f0e8;stroke-width:2}.map-node text{font-family:Arial,sans-serif;font-size:11px;font-weight:600}.map-node .problem-dot{fill:#a34b3f}";
    clone.insertBefore(style, clone.firstChild);
    const blob = new Blob([new XMLSerializer().serializeToString(clone)], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const image = new Image();
    image.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = Math.ceil(bounds.width * 2);
      canvas.height = Math.ceil(bounds.height * 2);
      const context = canvas.getContext("2d");
      context.fillStyle = "#f3f0e8";
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.drawImage(image, 0, 0, canvas.width, canvas.height);
      URL.revokeObjectURL(url);
      canvas.toBlob((png) => {
        if (!png) {
          details.textContent = "PNG export failed. Please try again.";
          return;
        }
        const link = document.createElement("a");
        link.download = "student-management-map.png";
        link.href = URL.createObjectURL(png);
        link.click();
        URL.revokeObjectURL(link.href);
      }, "image/png");
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      details.textContent = "PNG export failed. Please try again.";
    };
    image.src = url;
  });
  window.addEventListener("resize", () => render());
  state.root.each((node) => { node._children = null; });
  window.mindmapTest = {
    checkCentered(data) {
      const testRoot = d3.hierarchy(data);
      const { radius } = arrangeRadial(testRoot);
      const extent = radius + Math.max(...testRoot.descendants().map((node) => boxSize(node).width)) + 36;
      const scale = Math.min(state.width / (extent * 2), state.height / (extent * 2));
      return testRoot.x === 0 && testRoot.y === 0 && Number.isFinite(scale) && scale > 0 &&
        testRoot.descendants().every((node) => Number.isFinite(node.x) && Number.isFinite(node.y));
    },
    checkNoOverlaps(data) {
      const testRoot = d3.hierarchy(data).sum((item) => item.children ? 0 : 1);
      arrangeRadial(testRoot);
      const nodes = testRoot.descendants();
      return nodes.every((node, index) => nodes.slice(index + 1).every((other) => {
        const a = boxSize(node);
        const b = boxSize(other);
        const ax = node.depth === 0 ? node.x - a.width / 2 : node.x + (Math.cos(node.angle) < 0 ? -a.width : 0);
        const ay = node.y - a.height / 2;
        const bx = other.depth === 0 ? other.x - b.width / 2 : other.x + (Math.cos(other.angle) < 0 ? -b.width : 0);
        const by = other.y - b.height / 2;
        return ax + a.width <= bx || bx + b.width <= ax || ay + a.height <= by || by + b.height <= ay;
      }));
    }
  };
  const savedLayout = sessionStorage.getItem("mindmap-layout");
  const defaultLayout = state.root.descendants().length <= 60 ? "radial" : "tree";
  state.layout = savedLayout === "tree" || savedLayout === "radial" ? savedLayout : defaultLayout;
  document.querySelectorAll("[data-layout-choice]").forEach((button) => {
    button.classList.toggle("active", button.dataset.layoutChoice === state.layout);
    button.setAttribute("aria-pressed", String(button.dataset.layoutChoice === state.layout));
  });
  render();
})();
