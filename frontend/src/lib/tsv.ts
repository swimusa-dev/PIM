// Excel-compatible TSV helpers for grid copy and paste (DM-03).

/** Serialize a rectangular block of strings as TSV. Cells with tabs, newlines or quotes are quoted. */
export function toTsv(block: string[][]): string {
  return block
    .map((row) =>
      row
        .map((cell) => {
          if (/[\t\n\r"]/.test(cell)) return `"${cell.replace(/"/g, '""')}"`;
          return cell;
        })
        .join("\t"),
    )
    .join("\n");
}

/** Parse TSV text from the clipboard (Excel puts a trailing newline; quoted cells may span lines). */
export function fromTsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let inQuotes = false;
  let i = 0;
  const src = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  while (i < src.length) {
    const ch = src[i];
    if (inQuotes) {
      if (ch === '"') {
        if (src[i + 1] === '"') {
          cell += '"';
          i += 2;
          continue;
        }
        inQuotes = false;
        i += 1;
        continue;
      }
      cell += ch;
      i += 1;
      continue;
    }
    if (ch === '"' && cell === "") {
      inQuotes = true;
      i += 1;
      continue;
    }
    if (ch === "\t") {
      row.push(cell);
      cell = "";
      i += 1;
      continue;
    }
    if (ch === "\n") {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
      i += 1;
      continue;
    }
    cell += ch;
    i += 1;
  }
  if (cell !== "" || row.length > 0) {
    row.push(cell);
    rows.push(row);
  }
  // Drop the trailing empty row Excel adds.
  while (rows.length > 0 && rows[rows.length - 1].every((c) => c === "")) rows.pop();
  return rows;
}
