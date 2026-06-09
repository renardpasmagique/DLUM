// DLUM weaving draft editor — threading + liftplan + drawdown + colors.
// Inspired by WeavePoint's compact 3-pane layout, adapted for our 4-shaft loom.

// Shaft count default 4, can be overridden per-instance via opts.shaftCount.
const DEFAULT_SHAFTS = 4;
const DEFAULT_ENDS = 32;
const DEFAULT_PICKS = 16;
const CELL = 18;

const PALETTE = [
  "#1a1a1a", "#ffffff", "#c0392b", "#27ae60", "#2980b9", "#f39c12",
  "#8e44ad", "#16a085", "#d35400", "#7f8c8d", "#e74c3c", "#2ecc71",
  "#3498db", "#f1c40f", "#9b59b6", "#1abc9c",
];

// --- Pure-data state model. Held in the DraftEditor instance.
function emptyMatrix(rows, cols, val = 0) {
  return Array.from({ length: rows }, () => Array(cols).fill(val));
}

// Standard threading patterns (shaft count parameterized)
function threadingStraight(ends, shafts) {
  const t = new Array(ends).fill(0);
  for (let i = 0; i < ends; i++) t[i] = i % shafts;
  return t;
}
function threadingPointTwill(ends, shafts) {
  const t = new Array(ends).fill(0);
  const period = (shafts - 1) * 2;
  for (let i = 0; i < ends; i++) {
    const k = i % period;
    t[i] = k < shafts ? k : period - k;
  }
  return t;
}

// Standard liftplans
function liftplanPlain(picks, shafts) {
  return Array.from({ length: picks }, (_, p) =>
    Array.from({ length: shafts }, (_, s) => (s % 2 === p % 2 ? 1 : 0))
  );
}
function liftplanTwill22(picks, shafts) {
  // 2/2 twill : 2 adjacent shafts up, advances 1 each pick (cyclic).
  return Array.from({ length: picks }, (_, p) => {
    const r = new Array(shafts).fill(0);
    r[p % shafts] = 1;
    r[(p + 1) % shafts] = 1;
    return r;
  });
}
function liftplanTwill13(picks, shafts) {
  return Array.from({ length: picks }, (_, p) => {
    const r = new Array(shafts).fill(0); r[p % shafts] = 1; return r;
  });
}
function liftplanTwill31(picks, shafts) {
  return Array.from({ length: picks }, (_, p) => {
    const r = new Array(shafts).fill(1); r[p % shafts] = 0; return r;
  });
}
function liftplanBrokenTwill(picks, shafts) {
  // Variant of 2/2 with a break each shafts/2 picks
  return Array.from({ length: picks }, (_, p) => {
    const r = new Array(shafts).fill(0);
    const offset = p % shafts;
    r[offset] = 1;
    r[(offset + 1) % shafts] = 1;
    if (Math.floor(p / shafts) % 2 === 1) {
      // shift by half on alternate periods to break the diagonal
      r.fill(0);
      r[(offset + Math.floor(shafts/2)) % shafts] = 1;
      r[(offset + Math.floor(shafts/2) + 1) % shafts] = 1;
    }
    return r;
  });
}

const PRESETS = [
  { name: "Toile (plain)",    threading: threadingStraight, liftplan: liftplanPlain },
  { name: "Sergé 2/2",        threading: threadingStraight, liftplan: liftplanTwill22 },
  { name: "Sergé 1/3",        threading: threadingStraight, liftplan: liftplanTwill13 },
  { name: "Sergé 3/1",        threading: threadingStraight, liftplan: liftplanTwill31 },
  { name: "Sergé brisé",      threading: threadingStraight, liftplan: liftplanBrokenTwill },
  { name: "Pointe (point)",   threading: threadingPointTwill, liftplan: liftplanPlain },
];

export class DraftEditor {
  constructor(container, opts = {}) {
    this.container = container;
    this.shaftCount = opts.shaftCount ?? DEFAULT_SHAFTS;
    this.ends = opts.ends ?? DEFAULT_ENDS;
    this.picks = opts.picks ?? DEFAULT_PICKS;
    this.threading = threadingStraight(this.ends, this.shaftCount);
    this.liftplan = liftplanPlain(this.picks, this.shaftCount);
    this.warpColors = new Array(this.ends).fill(0);
    this.weftColors = new Array(this.picks).fill(1);
    this.activeColor = 0;
    this.onSendLiftplan = opts.onSendLiftplan || (() => {});
    this.onLibraryLoad = opts.onLibraryLoad || (() => {});
    this.libraryEntries = []; // [{id, name}]
    this._build();
  }

  setLibraryEntries(entries) {
    this.libraryEntries = entries || [];
    // Re-render the toolbar so the dropdown picks up the new entries
    const sel = this.container.querySelector("#d-preset");
    if (sel) {
      const previousValue = sel.value;
      sel.innerHTML = this._presetOptionsHtml();
      if (previousValue) sel.value = previousValue;
    }
  }

  _presetOptionsHtml() {
    let html = "<optgroup label='Préréglages'>";
    for (let i = 0; i < PRESETS.length; i++) {
      html += `<option value="preset:${i}">${PRESETS[i].name}</option>`;
    }
    html += "</optgroup>";
    if (this.libraryEntries.length) {
      html += "<optgroup label='📚 Bibliothèque'>";
      for (const e of this.libraryEntries) {
        html += `<option value="lib:${e.id}">${e.name}</option>`;
      }
      html += "</optgroup>";
    }
    return html;
  }

  _build() {
    this.container.innerHTML = "";
    this.container.appendChild(this._toolbar());
    const wrap = document.createElement("div");
    wrap.className = "draft-wrap";
    this.container.appendChild(wrap);
    this._buildGrid(wrap);
    this._buildLegend();
  }

  _toolbar() {
    const t = document.createElement("div");
    t.className = "draft-toolbar";
    t.innerHTML = `
      <label title="Nombre de fils de chaîne">Fils <input type="number" min="4" max="128" id="d-ends" value="${this.ends}" style="width:60px;"></label>
      <label title="Nombre de duites (passages de trame)">Duites <input type="number" min="2" max="128" id="d-picks" value="${this.picks}" style="width:60px;"></label>
      <button class="ghost" id="d-apply" title="Redimensionne en gardant le motif (ajoute des cellules vides ou tronque)">↔ Redimensionner</button>
      <button class="ghost" id="d-reset" title="Efface complètement le motif courant (toile vide)">⌫ Réinitialiser</button>
      <span style="margin-left:.5rem; color:var(--muted); font-size:.8rem;">Préréglage / motif</span>
      <select id="d-preset">${this._presetOptionsHtml()}</select>
      <button class="primary" id="d-load-preset" title="Applique le préréglage ou motif sauvegardé sélectionné">↓ Charger</button>
      <span style="flex:1;"></span>
      <button class="ghost" id="d-export">Exporter JSON</button>
      <button class="ghost" id="d-import">Importer JSON</button>
      <button class="primary" id="d-send">Envoyer au métier →</button>
    `;
    setTimeout(() => {
      t.querySelector("#d-apply").onclick = () => this._resize();
      t.querySelector("#d-reset").onclick = () => this._resetPlan();
      t.querySelector("#d-load-preset").onclick = () => this._loadPreset();
      t.querySelector("#d-export").onclick = () => this._export();
      t.querySelector("#d-import").onclick = () => this._import();
      t.querySelector("#d-send").onclick = () => this._sendToLoom();
    });
    return t;
  }

  _resetPlan() {
    if (!confirm("Effacer complètement le motif courant ? Les dimensions et couleurs sont conservées.")) return;
    this.threading = new Array(this.ends).fill(0);
    this.liftplan = Array.from({ length: this.picks }, () => new Array(this.shaftCount).fill(0));
    this._build();
  }

  _resize() {
    // Redimensionne en conservant le motif existant. Cellules ajoutées = 0 ;
    // si on rétrécit, les valeurs au-delà sont coupées.
    const e = parseInt(this.container.querySelector("#d-ends").value) || DEFAULT_ENDS;
    const p = parseInt(this.container.querySelector("#d-picks").value) || DEFAULT_PICKS;
    this.ends = Math.max(4, Math.min(128, e));
    this.picks = Math.max(2, Math.min(128, p));
    // threading: extend with default straight pattern, truncate if shorter
    if (this.threading.length < this.ends) {
      while (this.threading.length < this.ends) {
        this.threading.push(this.threading.length % this.shaftCount);
      }
    } else if (this.threading.length > this.ends) {
      this.threading.length = this.ends;
    }
    // warp colors: extend with 0, truncate if shorter
    if (this.warpColors.length < this.ends) {
      while (this.warpColors.length < this.ends) this.warpColors.push(0);
    } else if (this.warpColors.length > this.ends) {
      this.warpColors.length = this.ends;
    }
    // liftplan: extend with empty rows of correct size, also fix existing rows
    // that may have wrong size (e.g. after a shaft count change).
    for (let i = 0; i < this.liftplan.length; i++) {
      const r = this.liftplan[i] || [];
      const fixed = new Array(this.shaftCount).fill(0);
      for (let j = 0; j < Math.min(r.length, this.shaftCount); j++) fixed[j] = r[j] ? 1 : 0;
      this.liftplan[i] = fixed;
    }
    if (this.liftplan.length < this.picks) {
      while (this.liftplan.length < this.picks) {
        this.liftplan.push(new Array(this.shaftCount).fill(0));
      }
    } else if (this.liftplan.length > this.picks) {
      this.liftplan.length = this.picks;
    }
    // weft colors: extend with default, truncate if shorter
    if (this.weftColors.length < this.picks) {
      while (this.weftColors.length < this.picks) this.weftColors.push(1);
    } else if (this.weftColors.length > this.picks) {
      this.weftColors.length = this.picks;
    }
    this._build();
  }

  _loadPreset() {
    const v = this.container.querySelector("#d-preset").value || "";
    if (v.startsWith("preset:")) {
      const i = parseInt(v.slice(7));
      const p = PRESETS[i];
      if (!p) return;
      this.threading = p.threading(this.ends, this.shaftCount);
      this.liftplan = p.liftplan(this.picks, this.shaftCount);
      this._build();
    } else if (v.startsWith("lib:")) {
      const id = v.slice(4);
      this.onLibraryLoad(id);
    }
  }

  _buildGrid(wrap) {
    const W = this.ends, P = this.picks;
    const grid = document.createElement("div");
    grid.className = "draft-grid";
    grid.style.setProperty("--cell", CELL + "px");
    grid.style.setProperty("--ends", W);
    grid.style.setProperty("--picks", P);

    // top-left empty
    grid.appendChild(this._spacer());

    // top: warp color strip (W cells)
    const warpRow = document.createElement("div");
    warpRow.className = "row warp-colors";
    for (let i = 0; i < W; i++) {
      const c = document.createElement("div");
      c.className = "cell color";
      c.style.background = PALETTE[this.warpColors[i]];
      c.title = `Warp end ${i + 1}`;
      c.onclick = () => { this.warpColors[i] = this.activeColor; c.style.background = PALETTE[this.activeColor]; this._redrawDrawdown(); };
      warpRow.appendChild(c);
    }
    grid.appendChild(warpRow);

    // top-right empty (4 cols liftplan area)
    grid.appendChild(this._spacer());

    // left empty
    grid.appendChild(this._spacer());

    // threading (4 shafts × W ends)
    const thr = document.createElement("div");
    thr.className = "row threading";
    thr.style.setProperty("--cols", W);
    for (let s = this.shaftCount - 1; s >= 0; s--) {
      for (let i = 0; i < W; i++) {
        const c = document.createElement("div");
        c.className = "cell threading-cell" + (this.threading[i] === s ? " on" : "");
        c.dataset.s = s; c.dataset.i = i;
        c.title = `End ${i + 1}, shaft ${s + 1}`;
        c.onclick = () => {
          this.threading[i] = s;
          thr.querySelectorAll(`[data-i="${i}"]`).forEach(x => x.classList.remove("on"));
          c.classList.add("on");
          this._redrawDrawdown();
        };
        thr.appendChild(c);
      }
    }
    grid.appendChild(thr);

    // right of threading: shaft labels
    const shaftLabels = document.createElement("div");
    shaftLabels.className = "row shaft-labels";
    for (let s = this.shaftCount - 1; s >= 0; s--) {
      const l = document.createElement("div");
      l.className = "label";
      l.textContent = "S" + (s + 1);
      shaftLabels.appendChild(l);
    }
    grid.appendChild(shaftLabels);

    // weft color strip (P × 1)
    const weftCol = document.createElement("div");
    weftCol.className = "col weft-colors";
    for (let p = 0; p < P; p++) {
      const c = document.createElement("div");
      c.className = "cell color";
      c.style.background = PALETTE[this.weftColors[p]];
      c.title = `Pick ${p + 1}`;
      c.onclick = () => { this.weftColors[p] = this.activeColor; c.style.background = PALETTE[this.activeColor]; this._redrawDrawdown(); };
      weftCol.appendChild(c);
    }
    grid.appendChild(weftCol);

    // drawdown (P × W)
    this.drawdownEl = document.createElement("div");
    this.drawdownEl.className = "row drawdown";
    this.drawdownEl.style.setProperty("--cols", W);
    grid.appendChild(this.drawdownEl);

    // liftplan (P × 4)
    const lift = document.createElement("div");
    lift.className = "row liftplan";
    lift.style.setProperty("--cols", this.shaftCount);
    for (let p = 0; p < P; p++) {
      const raised = this.liftplan[p].reduce((a, b) => a + b, 0);
      const validRow = raised >= 1 && raised <= 3;
      for (let s = this.shaftCount - 1; s >= 0; s--) {
        const c = document.createElement("div");
        c.className = "cell lift-cell" + (this.liftplan[p][s] ? " on" : "") + (validRow ? "" : " invalid");
        c.dataset.p = p; c.dataset.s = s;
        c.title = `Pick ${p + 1}, shaft ${s + 1}`;
        c.onclick = () => this._toggleLiftCell(p, s);
        lift.appendChild(c);
      }
    }
    grid.appendChild(lift);

    wrap.appendChild(grid);
    this._redrawDrawdown();
  }

  _spacer() {
    const s = document.createElement("div");
    s.className = "spacer";
    return s;
  }

  // Toggle a single liftplan cell without rebuilding the whole editor.
  // Updates the cell class, row validity classes, and redraws the drawdown.
  _toggleLiftCell(p, s) {
    this.liftplan[p][s] = this.liftplan[p][s] ? 0 : 1;
    const liftEl = this.container.querySelector('.liftplan');
    if (!liftEl) { this._build(); return; }
    const raised = this.liftplan[p].reduce((a, b) => a + b, 0);
    const validRow = raised >= 1 && raised <= this.shaftCount - 1;
    for (let sj = 0; sj < this.shaftCount; sj++) {
      const cell = liftEl.querySelector(`[data-p="${p}"][data-s="${sj}"]`);
      if (!cell) { this._build(); return; }
      cell.classList.toggle('on', !!this.liftplan[p][sj]);
      cell.classList.toggle('invalid', !validRow);
    }
    this._redrawDrawdown();
  }

  _redrawDrawdown() {
    if (!this.drawdownEl) return;
    const W = this.ends, P = this.picks;
    this.drawdownEl.innerHTML = "";
    for (let p = 0; p < P; p++) {
      for (let i = 0; i < W; i++) {
        const shaft = this.threading[i];
        const up = this.liftplan[p][shaft] === 1;
        const c = document.createElement("div");
        c.className = "cell";
        c.style.background = PALETTE[up ? this.warpColors[i] : this.weftColors[p]];
        this.drawdownEl.appendChild(c);
      }
    }
  }

  _buildLegend() {
    const leg = document.createElement("div");
    leg.className = "draft-legend";
    leg.innerHTML = `<span style="color:var(--muted);font-size:.8rem;">Couleur active :</span>`;
    PALETTE.forEach((color, i) => {
      const sw = document.createElement("button");
      sw.className = "color-swatch" + (i === this.activeColor ? " active" : "");
      sw.style.background = color;
      sw.title = color;
      sw.onclick = () => {
        this.activeColor = i;
        leg.querySelectorAll(".color-swatch").forEach(x => x.classList.remove("active"));
        sw.classList.add("active");
      };
      leg.appendChild(sw);
    });
    leg.innerHTML += `<span style="margin-left:.75rem; color:var(--muted); font-size:.8rem;">Clique sur une bande de couleur (warp/trame) pour appliquer.</span>`;
    PALETTE.forEach((color, i) => {
      // attach handlers to the freshly-built swatches
    });
    // re-attach (innerHTML += wiped event handlers above)
    leg.querySelectorAll(".color-swatch").forEach((sw, i) => {
      sw.onclick = () => {
        this.activeColor = i;
        leg.querySelectorAll(".color-swatch").forEach(x => x.classList.remove("active"));
        sw.classList.add("active");
      };
    });
    this.container.appendChild(leg);
  }

  _export() {
    const blob = new Blob([JSON.stringify({
      ends: this.ends, picks: this.picks, threading: this.threading,
      liftplan: this.liftplan, warpColors: this.warpColors, weftColors: this.weftColors,
      palette: PALETTE,
    }, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "draft.json";
    a.click();
  }

  _import() {
    const inp = document.createElement("input");
    inp.type = "file"; inp.accept = "application/json";
    inp.onchange = () => {
      const r = new FileReader();
      r.onload = () => {
        try {
          const d = JSON.parse(r.result);
          if (!Array.isArray(d.threading) || !Array.isArray(d.liftplan)) throw new Error();
          this.ends = d.ends || d.threading.length;
          this.picks = d.picks || d.liftplan.length;
          this.threading = d.threading.slice(0, this.ends);
          this.liftplan = d.liftplan.slice(0, this.picks).map(r => r.slice(0, this.shaftCount));
          this.warpColors = (d.warpColors || []).slice(0, this.ends);
          while (this.warpColors.length < this.ends) this.warpColors.push(0);
          this.weftColors = (d.weftColors || []).slice(0, this.picks);
          while (this.weftColors.length < this.picks) this.weftColors.push(1);
          this._build();
        } catch (e) { alert("JSON invalide"); }
      };
      r.readAsText(inp.files[0]);
    };
    inp.click();
  }

  _sendToLoom() {
    // Filter only the rows that respect the 1-3 constraint (skip invalid)
    const valid = this.liftplan.filter(r => {
      const s = r.reduce((a, b) => a + b, 0);
      return s >= 1 && s <= 3;
    });
    if (!valid.length) {
      alert("Aucune ligne valide (chaque ligne doit lever 1 à 3 cadres).");
      return;
    }
    this.onSendLiftplan(valid);
  }
}
