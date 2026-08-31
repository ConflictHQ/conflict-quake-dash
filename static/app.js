/* Inline SVG, no CDN — same reasoning as the sibling fixture: a private
   install should not reach the public internet to draw its own charts. */
"use strict";

const SEQ = ["#405d02", "#547a02", "#699700", "#80b508", "#96d507"];
const tip = document.getElementById("tip");

const fmt = (n, d = 0) =>
  n === null || n === undefined || Number.isNaN(n)
    ? "—"
    : Number(n).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });

const el = (tag, attrs = {}, kids = []) => {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  for (const kid of [].concat(kids)) node.appendChild(kid);
  return node;
};

function showTip(evt, html) {
  tip.innerHTML = html;
  tip.classList.add("on");
  const pad = 14;
  const r = tip.getBoundingClientRect();
  let x = evt.clientX + pad;
  let y = evt.clientY + pad;
  if (x + r.width > window.innerWidth - 8) x = evt.clientX - r.width - pad;
  if (y + r.height > window.innerHeight - 8) y = evt.clientY - r.height - pad;
  tip.style.left = `${x}px`;
  tip.style.top = `${y}px`;
}
const hideTip = () => tip.classList.remove("on");

function niceTicks(max, count = 4) {
  const raw = max / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) || 10 * mag;
  const out = [];
  for (let v = 0; v <= max + step * 0.001; v += step) out.push(v);
  return { ticks: out, top: out[out.length - 1] };
}

function barPath(x, y, w, h, r) {
  const rr = Math.max(0, Math.min(r, w / 2, h));
  return `M${x},${y + h}V${y + rr}a${rr},${rr} 0 0 1 ${rr},${-rr}h${w - 2 * rr}a${rr},${rr} 0 0 1 ${rr},${rr}V${y + h}Z`;
}

/** One vertical-bar chart, single series, used for both the daily cadence and
 *  the magnitude distribution. `label` formats the axis and the tooltip key. */
function barChart(host, rows, { xKey, yKey, label, everyNth, axisTitle, width = 1000 }) {
  // The viewBox width has to track the panel the chart sits in: a 1000-wide
  // box scaled into a 5-column panel shrinks 10px axis text to unreadable.
  const W = width, H = 300, m = { t: 14, r: 12, b: 40, l: 52 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const { ticks, top: max } = niceTicks(Math.max(...rows.map((d) => d[yKey])));
  const step = iw / rows.length;
  const bw = Math.max(1, step - 2);
  const y = (v) => ih - (v / max) * ih;

  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": axisTitle });
  const g = el("g", { transform: `translate(${m.l},${m.t})` });

  for (const v of ticks) {
    g.appendChild(el("line", { class: "gridline", x1: 0, x2: iw, y1: y(v), y2: y(v) }));
    g.appendChild(el("text", { class: "axis", x: -8, y: y(v) + 3.5, "text-anchor": "end" },
      [document.createTextNode(fmt(v))]));
  }

  rows.forEach((d, i) => {
    const h = ih - y(d[yKey]);
    const p = el("path", { class: "bar", d: barPath(i * step, y(d[yKey]), bw, h, 4) });
    p.addEventListener("mousemove", (e) =>
      showTip(e, `<div>${label(d[xKey])}</div><div><span class="k">events</span> ${fmt(d[yKey])}</div>`));
    p.addEventListener("mouseleave", hideTip);
    g.appendChild(p);
    if (i % everyNth === 0 || i === rows.length - 1) {
      g.appendChild(el("text", { class: "axis", x: i * step + bw / 2, y: ih + 16,
        "text-anchor": "middle" }, [document.createTextNode(label(d[xKey]))]));
    }
  });
  g.appendChild(el("line", { class: "axis", x1: 0, x2: iw, y1: ih, y2: ih }));
  if (axisTitle) {
    g.appendChild(el("text", { class: "axis", x: iw / 2, y: ih + 34, "text-anchor": "middle" },
      [document.createTextNode(axisTitle)]));
  }
  svg.appendChild(g);
  host.replaceChildren(svg);
}

function magTable(host, rows) {
  const total = rows.reduce((a, r) => a + r.n, 0);
  host.innerHTML =
    `<table class="table"><thead><tr><th>Magnitude</th>` +
    `<th style="text-align:right">Events</th><th style="text-align:right">Share</th>` +
    `</tr></thead><tbody>` +
    rows.map((d) =>
      `<tr><td class="mono">M${fmt(d.bucket, 1)}</td><td class="num">${fmt(d.n)}</td>` +
      `<td class="num">${((d.n / total) * 100).toFixed(1)}%</td></tr>`).join("") +
    "</tbody></table>";
}

/* ---------- scatter: depth vs magnitude, sequential by depth ---------- */
function chartScatter(host, rows) {
  const W = 760, H = 380, m = { t: 14, r: 16, b: 44, l: 60 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;

  const mags = rows.map((d) => d.mag), depths = rows.map((d) => d.depth);
  const x0 = Math.min(...mags), x1 = Math.max(...mags);
  const d0 = Math.min(...depths), d1 = Math.max(...depths);
  const X = (v) => ((v - x0) / (x1 - x0 || 1)) * iw;
  const Y = (v) => ih - ((v - d0) / (d1 - d0 || 1)) * ih;
  const band = (v) => SEQ[Math.min(SEQ.length - 1,
    SEQ.length - 1 - Math.floor(((v - d0) / (d1 - d0 || 1)) * SEQ.length))];

  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img",
    "aria-label": "Event depth against magnitude" });
  const g = el("g", { transform: `translate(${m.l},${m.t})` });

  const { ticks: xt } = niceTicks(x1, 5);
  for (const v of xt) {
    if (v < x0) continue;
    g.appendChild(el("line", { class: "gridline", x1: X(v), x2: X(v), y1: 0, y2: ih }));
    g.appendChild(el("text", { class: "axis", x: X(v), y: ih + 16, "text-anchor": "middle" },
      [document.createTextNode(`M${fmt(v, 1)}`)]));
  }
  const { ticks: yt } = niceTicks(d1, 4);
  for (const v of yt) {
    if (v < d0) continue;
    g.appendChild(el("line", { class: "gridline", x1: 0, x2: iw, y1: Y(v), y2: Y(v) }));
    g.appendChild(el("text", { class: "axis", x: -8, y: Y(v) + 3.5, "text-anchor": "end" },
      [document.createTextNode(fmt(v))]));
  }

  rows.forEach((d) => {
    const c = el("circle", { cx: X(d.mag), cy: Y(d.depth), r: 2.8,
      fill: band(d.depth), "fill-opacity": ".85" });
    c.addEventListener("mousemove", (e) => showTip(e,
      `<div>${d.place}</div>` +
      `<div><span class="k">magnitude</span> M${fmt(d.mag, 1)}</div>` +
      `<div><span class="k">depth</span> ${fmt(d.depth, 1)} km</div>` +
      `<div><span class="k">time</span> ${d.time.slice(0, 16).replace("T", " ")}Z</div>`));
    c.addEventListener("mouseleave", hideTip);
    g.appendChild(c);
  });

  g.appendChild(el("text", { class: "axis", x: iw / 2, y: ih + 36, "text-anchor": "middle" },
    [document.createTextNode("magnitude")]));
  g.appendChild(el("text", { class: "axis", transform: `translate(-44,${ih / 2}) rotate(-90)`,
    "text-anchor": "middle" }, [document.createTextNode("depth (km)")]));
  svg.appendChild(g);

  const legend = document.createElement("div");
  legend.className = "legend";
  legend.innerHTML =
    `<span class="ramp"><span>shallow ${fmt(d0, 1)} km</span>` +
    SEQ.slice().reverse().map((c) => `<i style="background:${c}"></i>`).join("") +
    `<span>${fmt(d1, 0)} km deep</span></span>`;
  host.replaceChildren(svg, legend);
}

function regionsTable(host, rows) {
  host.innerHTML =
    `<table class="table"><thead><tr><th>Region</th>` +
    `<th style="text-align:right">Events</th><th style="text-align:right">Strongest</th>` +
    `</tr></thead><tbody>` +
    rows.map((d) =>
      `<tr><td>${d.region}</td><td class="num">${fmt(d.n)}</td>` +
      `<td class="num">M${fmt(d.max_mag, 1)}</td></tr>`).join("") +
    "</tbody></table>";
}

function strongestTable(host, rows) {
  host.innerHTML =
    `<table class="table"><thead><tr><th>Place</th>` +
    `<th style="text-align:right">Mag</th><th style="text-align:right">Depth</th>` +
    `</tr></thead><tbody>` +
    rows.map((d) =>
      `<tr><td>${d.place}</td><td class="num">M${fmt(d.mag, 1)}</td>` +
      `<td class="num">${fmt(d.depth, 1)} km</td></tr>`).join("") +
    "</tbody></table>";
}

function tiles(host, s) {
  const items = [
    { num: fmt(s.events), lbl: "events on file", sub: `${(s.first_time || "").slice(0, 10)} → ${(s.last_time || "").slice(0, 10)}` },
    { num: `M${fmt(s.max_mag, 1)}`, lbl: "strongest event", sub: s.strongest_place || "—" },
    { num: fmt(s.significant), lbl: "at M4.5 or above", sub: "the reportable band" },
    { num: `${fmt(s.avg_depth, 1)}`, lbl: "mean depth (km)", sub: `dataset from ${s.dataset_source}` },
  ];
  host.innerHTML = items.map((i) =>
    `<div class="tile"><div class="num">${i.num}</div>` +
    `<div class="lbl">${i.lbl}</div><div class="sub">${i.sub}</div></div>`).join("");
}

const get = (p) => fetch(p).then((r) => {
  if (!r.ok) throw new Error(`${p} -> ${r.status}`);
  return r.json();
});

async function main() {
  document.querySelectorAll(".toggle[data-table]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const t = document.getElementById(btn.dataset.table);
      const chart = t.previousElementSibling;
      const showTable = t.hidden;
      t.hidden = !showTable;
      chart.hidden = showTable;
      btn.textContent = showTable ? "chart" : "table";
    });
  });

  try {
    const [s, day, mag, scat, regions, strong, dbg] = await Promise.all([
      get("/api/summary"), get("/api/by-day"), get("/api/by-magnitude"),
      get("/api/scatter"), get("/api/regions"), get("/api/strongest"), get("/debug"),
    ]);
    tiles(document.getElementById("tiles"), s);
    barChart(document.getElementById("c-day"), day, {
      xKey: "day", yKey: "n", everyNth: 3,
      label: (v) => v.slice(5), axisTitle: "",
    });
    barChart(document.getElementById("c-mag"), mag, {
      xKey: "bucket", yKey: "n", everyNth: 4, width: 520,
      label: (v) => `M${Number(v).toFixed(1)}`, axisTitle: "magnitude",
    });
    magTable(document.getElementById("t-mag"), mag);
    chartScatter(document.getElementById("c-scatter"), scat);
    regionsTable(document.getElementById("t-regions"), regions);
    strongestTable(document.getElementById("t-strongest"), strong);
    document.getElementById("f-version").textContent = `version ${dbg.version}`;
    document.getElementById("f-pod").textContent = `pod ${dbg.hostname}`;
    document.getElementById("f-source").textContent = `dataset ${dbg.dataset.source}`;
  } catch (err) {
    const h = document.getElementById("health");
    h.className = "status status--err";
    h.textContent = "degraded";
    console.error(err);
  }
}
main();
