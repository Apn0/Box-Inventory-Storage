import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  resolveSheet, parseSheetDate, parseCSV,
  containerOf, containerRange, findSplitItems
} from '../src/js/resolve.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

test('parseSheetDate parses ISO and DMY dates with and without times', () => {
  assert.equal(parseSheetDate("2026-05-12"), "2026-05-12T00:00:00");
  assert.equal(parseSheetDate("2026-05-12 14:30"), "2026-05-12T14:30:00");
  assert.equal(parseSheetDate("2026-05-12 14:30:45"), "2026-05-12T14:30:45");
  assert.equal(parseSheetDate("12/05/2026"), "2026-05-12T00:00:00");
  assert.equal(parseSheetDate("12/05/2026 14:30:45"), "2026-05-12T14:30:45");
  assert.equal(parseSheetDate("12-05-2026"), "2026-05-12T00:00:00");
  assert.equal(parseSheetDate("not a date"), null);
  assert.equal(parseSheetDate(""), null);
  assert.equal(parseSheetDate(null), null);
});

test('containerOf and containerRange default and household logic', () => {
  assert.equal(containerOf(1), "1");
  assert.equal(containerOf(30), "1");
  assert.equal(containerOf(31), "2");
  assert.equal(containerOf(401), "H1");
  assert.equal(containerOf(430), "H1");
  assert.equal(containerOf(431), "H2");

  assert.deepEqual(containerRange(1), [1, 30]);
  assert.deepEqual(containerRange(31), [31, 60]);
  assert.deepEqual(containerRange(401), [401, 430]);
  assert.deepEqual(containerRange(431), [431, 460]);
});

test('parseCSV handles quotes, commas, newlines', () => {
  const csv = 'Box,Item,"Qty, Note"\n1,"ESP32, ""NodeMCU""",10\n';
  const rows = parseCSV(csv);
  assert.equal(rows.length, 2);
  assert.deepEqual(rows[0], ['Box', 'Item', 'Qty, Note']);
  assert.deepEqual(rows[1], ['1', 'ESP32, "NodeMCU"', '10']);
});

test('findSplitItems detects parts located in multiple boxes', () => {
  const items = [
    { box: 1, name: "ESP32", status: "active" },
    { box: 5, name: "ESP32", status: "active" },
    { box: 2, name: "Capacitor", status: "active" },
    { box: 3, name: "Deleted Part", status: "gone" }
  ];
  const split = findSplitItems(items);
  assert.equal(split.length, 1);
  assert.equal(split[0].name, "ESP32");
  assert.deepEqual(split[0].boxes, [1, 5]);
});

test('resolver parity with PyCore', () => {
  const fixturesPath = path.join(__dirname, 'fixtures', 'resolver_cases.json');
  if (!fs.existsSync(fixturesPath)) {
    console.log('No fixtures found, skipping test (waiting for PyCore)');
    return;
  }
  
  const fixturesData = fs.readFileSync(fixturesPath, 'utf8');
  const cases = JSON.parse(fixturesData);

  for (const c of cases) {
    const { box_csv, form_csv, expected_items, seedMeta } = c;
    const result = resolveSheet(box_csv, form_csv, seedMeta || { containerSize: 30 });
    
    // We only care about the items list for now, but we can verify other aspects if provided
    assert.equal(result.items.length, expected_items.length, `Item count mismatch on case: ${c.name}`);
    for (let i = 0; i < expected_items.length; i++) {
      const exp = expected_items[i];
      const act = result.items[i];
      for (const k of Object.keys(exp)) {
        assert.deepEqual(act[k], exp[k], `Mismatch on case: ${c.name}, key: ${k}`);
      }
    }
  }
});
