/* Shelf mode must never claim a part has moved when it has not.
 *
 * "Done" is not a stored tick — it is read back out of the inventory, so the
 * list is the same on every device. That makes the derivation the thing worth
 * pinning down: a row that says done when the part is still on the old shelf
 * sends Arno past a box he has not emptied, and the sheet would carry the lie
 * forever (the app writes the move, nobody re-checks it).
 */
import './mock_globals.js';
import test from 'node:test';
import assert from 'node:assert/strict';

import { moveRows, shelfRows } from '../src/js/app.js';

const plan = {
  boxes: {
    "10": {category: "power",  parts: [{name: "INA219", oldBox: 5, qty: 2, countType: "exact"}]},
    "7":  {category: "sensor", parts: [{name: "Heart-rate", oldBox: 7, qty: 1, countType: "exact"}]},
    "12": {category: "sensor", parts: [{name: "GUVA", oldBox: 7, qty: 2, countType: "exact"}]},
    "16": {category: "sensor", parts: [{name: "NEO-6M", oldBox: 7, qty: 1, countType: "exact"}]},
    "70": {category: "connector", parts: [{name: "Clips", oldBox: 4, qty: null, countType: "bulk"}]},
    "111": {category: "fastener", parts: [{name: "Countersink", oldBox: 1, qty: 1, countType: "exact"}]},
    "35": {category: "power",  parts: [{name: "Buck module", oldBox: 44, qty: 1, countType: "exact"}]},
  },
};
const item = (box, name, qty = 1, countType = "exact") => ({box, name, qty, countType});
const rows = (list) => shelfRows(1, plan, list, 90, 30);
const row = (list, name) => rows(list).find(r => r.name === name);

test('a part still in its old box is work, and carries its destination', () => {
  const r = row([item(5, "INA219", 2)], "INA219");
  assert.equal(r.done, false);
  assert.equal(r.from, 5);
  assert.equal(r.to, 10);
});

test('a part in the new box and gone from the old one is done', () => {
  const r = row([item(10, "INA219", 2)], "INA219");
  assert.equal(r.done, true);
  assert.equal(r.split, false);
});

test('a part in BOTH boxes is half-moved, not done', () => {
  const r = row([item(5, "INA219", 1), item(10, "INA219", 1)], "INA219");
  assert.equal(r.done, false, 'a split part would be skipped as finished');
  assert.equal(r.split, true);
});

test('a part in neither box is missing, and still not done', () => {
  const r = row([], "NEO-6M");          // the GPS that sat in an unsorted basket
  assert.equal(r.missing, true);
  assert.equal(r.done, false);
});

test('a part whose box does not change needs no carrying', () => {
  const r = row([item(7, "Heart-rate")], "Heart-rate");
  assert.equal(r.done, true);
  assert.equal(r.from, r.to);
  // Its one entry is both "here" and "there", which must not read as half-moved
  // — the live app showed "also still in 7" on a part that was never to move.
  assert.equal(r.split, false);
});

test('a finished row shows the count that is now in the new box', () => {
  // He found three INA219 in box 5 where the plan said two. Once they are in
  // box 10 the row must say three, not the number the plan was written with.
  const r = row([item(10, "INA219", 3)], "INA219");
  assert.equal(r.done, true);
  assert.equal(r.qty, 3);
});

test('a destination past the written labels waits instead of moving', () => {
  const r = row([item(1, "Countersink")], "Countersink");
  assert.equal(r.waits, true);
  assert.equal(r.done, false);
  assert.equal(r.to, 111, 'the real number, not an invented holding bin');
  assert.equal(row([item(5, "INA219", 2)], "INA219").waits, false);
});

test('only the old boxes of the chosen container are listed', () => {
  const list = [item(5, "INA219", 2), item(44, "Buck module")];
  assert.deepEqual(rows(list).map(r => r.from).filter(b => b > 30), []);
  assert.deepEqual(shelfRows(2, plan, list, 90, 30).map(r => r.from), [44]);
});

test('the live count wins over the count the plan was written with', () => {
  // Arno found three INA219 in box 5 where the plan said two; the row that gets
  // posted has to be the three he is actually holding.
  const r = row([item(5, "INA219", 3)], "INA219");
  assert.equal(r.qty, 3);
  assert.equal(r.countType, "exact");
});

test('a bulk pile keeps its bulk count type so it posts as "many"', () => {
  const r = shelfRows(1, plan, [item(4, "Clips", null, "bulk")], 90, 30)
    .find(x => x.name === "Clips");
  assert.equal(r.countType, "bulk");
  assert.equal(r.to, 70);
});

test('every plan part of the container is listed, in old-box order', () => {
  // Also the ones not on the shelf: box 7 keeps its three rows even though only
  // GUVA is there, or the NEO-6M in the basket would vanish from the list.
  const list = [item(5, "INA219", 2), item(7, "GUVA", 2), item(1, "Countersink")];
  assert.deepEqual(rows(list).map(r => r.from), [1, 4, 5, 7, 7, 7]);
});

/* The two rows a tick writes. Order is the whole safety story: the log resolves
 * newest-row-wins per (box, name), so zeroing the old box before filling the
 * new one leaves a window where the part exists nowhere — and if the second
 * post fails, it stays that way. */
test('a move fills the new box first, then zeroes the old one', () => {
  const [fill, empty] = moveRows({name: "INA219", from: 5, to: 10, qty: 3});
  assert.deepEqual(fill,  {box: 10, name: "INA219", qty: "3", note: "reorg"});
  assert.deepEqual(empty, {box: 5,  name: "INA219", qty: "0", note: "reorg"});
});

test('a bulk pile posts as "many", never as an empty or null count', () => {
  const [fill] = moveRows({name: "Alligator clips", from: 4, to: 70, qty: null});
  assert.equal(fill.qty, "many");
  assert.equal(moveRows({name: "x", from: 1, to: 2, qty: undefined})[0].qty, "many");
  assert.equal(moveRows({name: "x", from: 1, to: 2, qty: "many"})[0].qty, "many");
});

test('a count of zero is still written as a count, not as "many"', () => {
  assert.equal(moveRows({name: "x", from: 1, to: 2, qty: 0})[0].qty, "0");
});
