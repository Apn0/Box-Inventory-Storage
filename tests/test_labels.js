/* The Labels tab has to print the boxes that do not exist yet.
 *
 * It used to list only boxes that already held something, which is precisely
 * backwards: a box with parts in it already has a label stuck on it. The 34
 * boxes the re-organisation still has to create — every number past the labels
 * Arno has written — are the ones he needs to print, and they are empty, so
 * they were the ones left out.
 */
import './mock_globals.js';
import test from 'node:test';
import assert from 'node:assert/strict';

import { labelBoxes, labelsToWrite } from '../src/js/app.js';

const plan = {
  boxes: {
    "111": {category: "fastener", parts: [{name: "Countersink", qty: 1, countType: "exact"}]},
    "103": {category: "fastener", parts: [{name: "Drill stoppers", qty: null, countType: "bulk"}]},
    "10":  {category: "power",    parts: [{name: "INA219", qty: 3, countType: "exact"}]},
  },
};
const item = (box, name, qty = 1, countType = "exact") => ({box, name, qty, countType});
const at = (labels, box) => labels.find(l => l.box === box);

test('a box that does not exist yet still gets a label, marked as planned', () => {
  const l = at(labelBoxes([], plan), 111);
  assert.ok(l, 'box 111 had no label to print');
  assert.equal(l.planned, true);
  assert.deepEqual(l.lines, [{name: "Countersink", n: 1}]);
});

test('a box that holds something is labelled with what is in it', () => {
  const l = at(labelBoxes([item(5, "Vibration motor", 4)], plan), 5);
  assert.equal(l.planned, false);
  assert.deepEqual(l.lines, [{name: "Vibration motor", n: 4}]);
});

test('a box that is both filled and planned is listed once, as it stands now', () => {
  const labels = labelBoxes([item(10, "INA219", 3), item(10, "Shunt", 1)], plan);
  assert.equal(labels.filter(l => l.box === 10).length, 1);
  assert.equal(at(labels, 10).planned, false);
  assert.equal(at(labels, 10).lines.length, 2);
});

test('a bulk pile gets no count printed on the label', () => {
  assert.deepEqual(at(labelBoxes([], plan), 103).lines, [{name: "Drill stoppers", n: null}]);
  assert.deepEqual(at(labelBoxes([item(2, "Clips", null, "bulk")], plan), 2).lines,
                   [{name: "Clips", n: null}]);
});

test('labels come out in box order, so a printed sheet can be cut in one run', () => {
  const labels = labelBoxes([item(5, "Vibration motor"), item(1, "Countersink bit")], plan);
  assert.deepEqual(labels.map(l => l.box), [1, 5, 10, 103, 111]);
});

test('without a plan it still prints every box that holds something', () => {
  const labels = labelBoxes([item(5, "Vibration motor")], null);
  assert.deepEqual(labels.map(l => l.box), [5]);
});

test('the household boxes are not labels he has to write', () => {
  // 401-438 are hangers and kitchen things. They have their own labels and the
  // electronics plan never touches them — counting them said 77 to write where
  // the real number is 39.
  const labels = [{box: 95}, {box: 130}, {box: 401}, {box: 438}, {box: 12}];
  assert.deepEqual(labelsToWrite(labels, 90).map(l => l.box), [95, 130]);
});

test('nothing is left to write when every box is within the labels he has', () => {
  assert.deepEqual(labelsToWrite([{box: 12}, {box: 90}, {box: 401}], 90), []);
});
