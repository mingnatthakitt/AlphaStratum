/**
 * CSV serialization helpers for the portfolio export.
 */

/**
 * Escape one CSV field per RFC 4180 and defuse spreadsheet formula injection.
 *
 * The backend's symbol pattern (`^[A-Z0-9.\-^=]{1,10}$`) explicitly permits a
 * leading `=`, so a lot created as `=1+1` would otherwise be written verbatim
 * and evaluated as a formula when the file is opened in Excel or Sheets.
 */
export function csvField(value: string | number): string {
  let text = String(value);

  // Leading = + - @ (and tab/CR, which some parsers also treat as a formula
  // prefix) get a leading apostrophe so spreadsheets treat them as text.
  if (/^[=+\-@\t\r]/.test(text)) {
    text = `'${text}`;
  }

  // Quote when the field contains a delimiter, quote or newline; double any
  // embedded quotes.
  if (/[",\n\r]/.test(text)) {
    return `"${text.replace(/"/g, '""')}"`;
  }
  return text;
}

export function csvRow(fields: Array<string | number>): string {
  return fields.map(csvField).join(",");
}

export function toCsv(rows: Array<Array<string | number>>): string {
  return rows.map(csvRow).join("\n");
}
