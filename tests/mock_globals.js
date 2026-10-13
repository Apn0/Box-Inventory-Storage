global.window = {};
global.location = { protocol: 'http:' };
global.document = {
  documentElement: {
    getAttribute: () => null,
    setAttribute: () => {},
    removeAttribute: () => {}
  },
  getElementById: (id) => ({
    textContent: '',
    classList: { add: () => {}, remove: () => {} },
    onclick: () => {},
    querySelectorAll: () => [],
    addEventListener: () => {},
    querySelector: () => null,
  }),
  addEventListener: () => {},
  body: {
    appendChild: () => {},
    addEventListener: () => {},
  },
  createElement: () => ({
    appendChild: () => {},
    setAttribute: () => {},
    style: {},
    classList: { add: () => {}, remove: () => {} },
    addEventListener: () => {},
  }),
  head: {
    appendChild: () => {}
  },
  querySelector: () => null,
  querySelectorAll: () => [],
  activeElement: { tagName: 'BODY' },
};
global.localStorage = {
  getItem: () => null,
  setItem: () => {},
  removeItem: () => {}
};
global.navigator = { vibrate: () => {} };
global.fetch = async () => ({
  json: async () => ({}),
  text: async () => "",
  ok: true
});
