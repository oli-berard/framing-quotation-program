const els = {
  width: document.getElementById("width"),
  height: document.getElementById("height"),
  frameCode: document.getElementById("frameCode"),
  frameSuggest: document.getElementById("frameSuggest"),
  frameMeta: document.getElementById("frameMeta"),
  mountNeeded: document.getElementById("mountNeeded"),
  mountFields: document.getElementById("mountFields"),
  mountCode: document.getElementById("mountCode"),
  mountSuggest: document.getElementById("mountSuggest"),
  mountMeta: document.getElementById("mountMeta"),
  glassNeeded: document.getElementById("glassNeeded"),
  accessoriesNeeded: document.getElementById("accessoriesNeeded"),
  quoteStatus: document.getElementById("quoteStatus"),
  quoteBody: document.getElementById("quoteBody"),
};

let catalog = { mouldings: [], boards: [] };
let scales = {};

const rand = (n) => Intl.NumberFormat("en-ZA", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n);
const rnum = (n, digits = 2) => Number(n).toLocaleString("en-ZA", { minimumFractionDigits: digits, maximumFractionDigits: digits });

function money(n) {
  return `R ${rand(n)}`;
}

function hide(node) {
  node.hidden = true;
  node.innerHTML = "";
}

function renderSuggest(container, rows, onPick) {
  if (!rows.length) {
    hide(container);
    return;
  }
  container.hidden = false;
  container.innerHTML = rows.map((row) => {
    const extra = row.material
      ? `${row.material} · ${row.width_mm} mm · R ${rand(row.base)} / m`
      : `${row.width_mm} × ${row.height_mm} mm · R ${rand(row.price)} / sheet`;
    return `<button type="button" data-code="${row.code}"><span class="code">${row.code}</span>${row.description} · ${extra}</button>`;
  }).join("");
  container.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("mousedown", (event) => {
      event.preventDefault();
      onPick(btn.dataset.code, rows.find((row) => row.code === btn.dataset.code));
    });
  });
}

function bindAutocomplete(input, suggest, searchFn, meta, formatter) {
  let timer = null;
  input.addEventListener("input", () => {
    clearTimeout(timer);
    const query = input.value.trim();
    if (query.length < 2) {
      hide(suggest);
      return;
    }
    timer = setTimeout(() => {
      const rows = searchFn(query);
      renderSuggest(suggest, rows, (code, row) => {
        input.value = code;
        meta.textContent = formatter(row);
        hide(suggest);
        quote();
      });
    }, 160);
  });
  input.addEventListener("blur", () => setTimeout(() => hide(suggest), 120));
}

bindAutocomplete(
  els.frameCode,
  els.frameSuggest,
  (query) => searchRows(catalog.mouldings, query),
  els.frameMeta,
  (row) => `${row.description} · ${row.material} · ${row.width_mm} mm wide · R ${rand(row.base)} / m excl VAT`
);

bindAutocomplete(
  els.mountCode,
  els.mountSuggest,
  (query) => searchRows(catalog.boards, query, ["category"]),
  els.mountMeta,
  (row) => `${row.description} · ${row.width_mm} × ${row.height_mm} mm · R ${rand(row.price)} / sheet excl VAT`
);

els.mountNeeded.addEventListener("change", () => {
  els.mountFields.hidden = !els.mountNeeded.checked;
  quote();
});

["width", "height", "frameCode", "mountCode", "glassNeeded", "accessoriesNeeded"].forEach((key) => {
  els[key].addEventListener("change", quote);
  els[key].addEventListener("input", quote);
});

function lineDetail(line) {
  if (line.type === "frame") {
    return `${line.billed_metres} m billed (${rnum(line.perimeter_metres, 3)} m perimeter + 0.5 m, rounded up) × R ${rand(line.base_per_m)} / m + 15% VAT`;
  }
  if (line.type === "mount_board") {
    const pct = (line.percent_used * 100).toFixed(1);
    if (line.full_sheet) {
      return `${pct}% of ${line.sheet_w_mm} × ${line.sheet_h_mm} mm sheet (over 50%, full sheet charged) + 15% VAT`;
    }
    return `${pct}% of ${line.sheet_w_mm} × ${line.sheet_h_mm} mm sheet at R ${rand(line.sheet_price)} + 15% VAT`;
  }
  if (line.type === "glass") {
    const minNote = line.minimum_applied ? ` · minimum R ${rand(line.minimum_excl)} applied` : "";
    return `${rnum(line.area_m2, 3)} m² × R ${rand(line.effective_rate)} / m² (${line.size_factor}× vs 976×815 ref)${minNote}`;
  }
  if (line.type === "accessories") {
    const rate = line.tier === "large" ? `R50 over ${line.threshold_m2} m²` : `R30 up to ${line.threshold_m2} m²`;
    return `${rnum(line.area_m2, 3)} m² · ${rate}`;
  }
  return "";
}

function renderQuote(data) {
  if (!data.ok) {
    els.quoteStatus.textContent = "Cannot cost this job yet.";
    els.quoteBody.innerHTML = data.errors.map((err) => `<p class="error">${err}</p>`).join("");
    return;
  }

  els.quoteStatus.textContent = `${data.frame.width_mm} × ${data.frame.height_mm} mm`;
  const lines = data.lines.map((line) => {
    const title = line.code ? `${line.code} · ${line.description}` : line.description;
    return `
      <div class="line">
        <div class="line-top">
          <span>${title}</span>
          <span>${money(line.incl)}</span>
        </div>
        <p>${lineDetail(line)}</p>
      </div>
    `;
  }).join("");

  els.quoteBody.innerHTML = `
    ${lines}
    <div class="totals">
      <div><span>Materials</span><span>${money(data.totals.materials)}</span></div>
      <div><span>× ${data.totals.multiplier} overcuts, mistakes, labour</span><span></span></div>
      <div class="grand"><span>Total</span><span>${money(data.totals.quote)}</span></div>
    </div>
  `;
}

let quoteTimer = null;
function quote() {
  clearTimeout(quoteTimer);
  quoteTimer = setTimeout(() => {
    const payload = {
      width_mm: els.width.value,
      height_mm: els.height.value,
      frame_code: els.frameCode.value,
      mount_needed: els.mountNeeded.checked,
      mount_code: els.mountCode.value,
      glass_needed: els.glassNeeded.checked,
      accessories_needed: els.accessoriesNeeded.checked,
    };
    if (!payload.frame_code) {
      els.quoteStatus.textContent = "Enter a frame code to cost this job.";
      els.quoteBody.innerHTML = "";
      return;
    }
    renderQuote(calculateQuote(catalog, scales, payload));
  }, 180);
}

async function boot() {
  try {
    const [catalogRes, scalesRes] = await Promise.all([
      fetch("catalog.json"),
      fetch("scales.json"),
    ]);
    catalog = await catalogRes.json();
    scales = await scalesRes.json();
  } catch (err) {
    els.quoteStatus.textContent = "Could not load price lists.";
    els.quoteBody.innerHTML = `<p class="error">${err.message}</p>`;
  }
}

boot();
