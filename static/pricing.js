function money(value) {
  return Math.round((value + 1e-9) * 100) / 100;
}

function billedMetres(widthMm, heightMm) {
  const perimeterMetres = (2 * (widthMm + heightMm)) / 1000;
  const cutMetres = perimeterMetres + 0.5;
  const billed = Math.ceil(cutMetres - 1e-9);
  return {
    perimeter_metres: Number(perimeterMetres.toFixed(4)),
    cut_metres: Number(cutMetres.toFixed(4)),
    billed_metres: billed,
    rounded_up: Math.abs(cutMetres - billed) > 1e-9,
  };
}

function boardUsage(frameW, frameH, boardW, boardH) {
  const fits =
    (frameW <= boardW && frameH <= boardH) ||
    (frameW <= boardH && frameH <= boardW);
  const frameArea = frameW * frameH;
  const boardArea = boardW * boardH;
  return {
    fits,
    percent_used: boardArea ? frameArea / boardArea : 0,
  };
}

function lerp(start, end, t) {
  return start + (end - start) * t;
}

function glassSizeFactor(areaM2, glass) {
  const ref = glass.reference;
  const refArea = (ref.width_mm / 1000) * (ref.height_mm / 1000);
  const smallArea = glass.small_area_m2;
  const smallFactor = glass.small_factor;
  const largeArea = glass.large_area_m2;
  const largeFactor = glass.large_factor;
  if (areaM2 <= smallArea) return smallFactor;
  if (areaM2 <= refArea) {
    return lerp(smallFactor, 1, (areaM2 - smallArea) / (refArea - smallArea));
  }
  if (areaM2 >= largeArea) return largeFactor;
  return lerp(1, largeFactor, (areaM2 - refArea) / (largeArea - refArea));
}

function glassPrice(areaM2, glass) {
  const ref = glass.reference;
  const refArea = (ref.width_mm / 1000) * (ref.height_mm / 1000);
  const baseRate = ref.price_excl / refArea;
  const factor = glassSizeFactor(areaM2, glass);
  const raw = areaM2 * baseRate * factor;
  const minimum = glass.minimum_excl;
  return {
    price_excl: Math.max(minimum, raw),
    base_rate: Number(baseRate.toFixed(4)),
    size_factor: Number(factor.toFixed(4)),
    effective_rate: Number((baseRate * factor).toFixed(4)),
    minimum_applied: raw < minimum,
    minimum_excl: minimum,
    thickness_mm: glass.thickness_mm || 2,
    label: glass.label || "2mm glass",
  };
}

function accessoryPrice(areaM2, accessories) {
  const threshold = accessories.large_area_m2 ?? 1;
  const large = areaM2 > threshold;
  return {
    price_excl: large ? accessories.large_excl : accessories.base_excl,
    tier: large ? "large" : "base",
    threshold_m2: threshold,
  };
}

function lineTotals(amount, vatInclusive) {
  if (vatInclusive) {
    const price = money(amount);
    return { excl: price, vat: 0, incl: price, vat_inclusive: true };
  }
  const vat = money(amount * 0.15);
  return { excl: money(amount), vat, incl: money(amount + vat), vat_inclusive: false };
}

function findByCode(rows, code) {
  const needle = String(code || "").trim().toUpperCase();
  return rows.find((row) => row.code === needle) || null;
}

function searchRows(rows, query, extraFields = []) {
  const q = query.trim().toUpperCase();
  if (!q) return [];
  return rows
    .filter((row) => {
      if (row.code.includes(q) || String(row.description).toUpperCase().includes(q)) return true;
      return extraFields.some((field) => String(row[field] || "").toUpperCase().includes(q));
    })
    .sort((a, b) => {
      const aPref = a.code.startsWith(q) ? 0 : 1;
      const bPref = b.code.startsWith(q) ? 0 : 1;
      return aPref - bPref || a.code.localeCompare(b.code);
    })
    .slice(0, 12);
}

function calculateQuote(catalog, scales, payload) {
  const vatRate = scales.vat_rate || 0.15;
  const widthMm = Number(payload.width_mm || 0);
  const heightMm = Number(payload.height_mm || 0);
  const errors = [];

  if (widthMm <= 0 || heightMm <= 0) errors.push("Frame dimensions must be greater than zero.");
  const moulding = findByCode(catalog.mouldings, payload.frame_code);
  if (!moulding) errors.push(`Frame code '${payload.frame_code || ""}' was not found in the price lists.`);

  let mount = null;
  if (payload.mount_needed) {
    mount = findByCode(catalog.boards, payload.mount_code);
    if (!mount) errors.push(`Mount board code '${payload.mount_code || ""}' was not found.`);
  }
  if (errors.length) return { ok: false, errors };

  const length = billedMetres(widthMm, heightMm);
  const lines = [
    {
      type: "frame",
      code: moulding.code,
      description: moulding.description,
      material: moulding.material,
      width_mm: moulding.width_mm,
      base_per_m: moulding.base,
      ...length,
      ...lineTotals(length.billed_metres * moulding.base, false),
    },
  ];
  const areaM2 = (widthMm * heightMm) / 1_000_000;

  if (mount) {
    const usage = boardUsage(widthMm, heightMm, mount.width_mm, mount.height_mm);
    if (!usage.fits) {
      return {
        ok: false,
        errors: [
          `${mount.code} is ${mount.width_mm} × ${mount.height_mm} mm, which is too small for a ${widthMm} × ${heightMm} mm frame.`,
        ],
      };
    }
    const fullSheet = usage.percent_used > 0.5;
    const boardExcl = fullSheet ? mount.price : usage.percent_used * mount.price;
    lines.push({
      type: "mount_board",
      code: mount.code,
      description: mount.description,
      category: mount.category,
      sheet_w_mm: mount.width_mm,
      sheet_h_mm: mount.height_mm,
      sheet_price: mount.price,
      percent_used: Number(usage.percent_used.toFixed(6)),
      full_sheet: fullSheet,
      ...lineTotals(boardExcl, false),
    });
  }

  if (payload.glass_needed) {
    const priced = glassPrice(areaM2, scales.glass);
    lines.push({
      type: "glass",
      description: priced.label,
      status: scales.glass.status,
      area_m2: Number(areaM2.toFixed(4)),
      thickness_mm: priced.thickness_mm,
      base_rate: priced.base_rate,
      size_factor: priced.size_factor,
      effective_rate: priced.effective_rate,
      minimum_applied: priced.minimum_applied,
      minimum_excl: priced.minimum_excl,
      ...lineTotals(priced.price_excl, true),
    });
  }

  if (payload.accessories_needed) {
    const priced = accessoryPrice(areaM2, scales.accessories);
    lines.push({
      type: "accessories",
      description: "Accessories",
      status: scales.accessories.status,
      area_m2: Number(areaM2.toFixed(4)),
      tier: priced.tier,
      threshold_m2: priced.threshold_m2,
      ...lineTotals(priced.price_excl, true),
    });
  }

  const materials = money(lines.reduce((sum, line) => sum + line.incl, 0));
  const multiplier = scales.job_multiplier?.factor || 2.85;
  return {
    ok: true,
    vat_rate: vatRate,
    frame: { width_mm: widthMm, height_mm: heightMm, area_m2: Number(areaM2.toFixed(4)) },
    lines,
    totals: {
      materials,
      multiplier,
      quote: money(materials * multiplier),
    },
  };
}
