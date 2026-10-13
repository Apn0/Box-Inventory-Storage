import './mock_globals.js';
import test from 'node:test';
import assert from 'node:assert/strict';

import { isRunningLow } from '../src/js/app.js';

test('isRunningLow returns false if countType is not exact', () => {
  assert.equal(isRunningLow({countType: 'bulk', qty: 1}), false);
  assert.equal(isRunningLow({countType: 'unknown', qty: 1}), false);
});

test('isRunningLow returns false if qty is 0 or greater than LOW_STOCK', () => {
  // LOW_STOCK is 2
  assert.equal(isRunningLow({countType: 'exact', qty: 0}), false);
  assert.equal(isRunningLow({countType: 'exact', qty: 3}), false);
});

test('isRunningLow returns true if qty is between 1 and LOW_STOCK and peak is > LOW_STOCK', () => {
  assert.equal(isRunningLow({countType: 'exact', qty: 1, peak: 3}), true);
  assert.equal(isRunningLow({countType: 'exact', qty: 2, peak: 4}), true);
});

test('isRunningLow returns false if qty is between 1 and LOW_STOCK but peak is not > LOW_STOCK', () => {
  assert.equal(isRunningLow({countType: 'exact', qty: 1, peak: 2}), false);
  assert.equal(isRunningLow({countType: 'exact', qty: 2, peak: 2}), false);
  assert.equal(isRunningLow({countType: 'exact', qty: 1, peak: 1}), false);
});

test('isRunningLow handles missing peak by defaulting to current qty', () => {
  assert.equal(isRunningLow({countType: 'exact', qty: 1}), false);
  assert.equal(isRunningLow({countType: 'exact', qty: 2}), false);
});
