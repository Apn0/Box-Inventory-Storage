import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { resolveSheet } from '../src/js/resolve.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

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
