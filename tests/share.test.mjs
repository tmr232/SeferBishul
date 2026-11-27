import { expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";

const script = readFileSync(
  new URL("../src/sefer_bishul/static/share.js", import.meta.url),
  "utf8",
);
const url = "https://tmr232.github.io/SeferBishul/%D7%9C%D7%97%D7%9D.html";

function page(navigator) {
  const link = {
    href: url,
    addEventListener(_event, listener) {
      this.click = listener;
    },
  };
  const status = { textContent: "" };
  let now = 0;
  let nextTimer = 0;
  const timers = new Map();
  runInNewContext(script, {
    navigator,
    setTimeout(callback, delay) {
      timers.set(++nextTimer, { callback, at: now + delay });
      return nextTimer;
    },
    clearTimeout(id) {
      timers.delete(id);
    },
    document: {
      title: "לחם & זיתים",
      getElementById: (id) => (id === "share-link" ? link : status),
    },
  });
  return {
    link,
    status,
    advance(ms) {
      now += ms;
      for (const [id, timer] of timers) {
        if (timer.at <= now) {
          timers.delete(id);
          timer.callback();
        }
      }
    },
  };
}

function click(overrides = {}) {
  return {
    button: 0,
    defaultPrevented: false,
    preventDefault() {
      this.defaultPrevented = true;
    },
    ...overrides,
  };
}

test("ordinary link activation shares the title and real link URL without navigating", async () => {
  let shared;
  const { link, status } = page({
    share: async (data) => {
      shared = data;
    },
  });
  const event = click();
  await link.click(event);
  expect(shared).toEqual({ title: "לחם & זיתים", url });
  expect(event.defaultPrevented).toBe(true);
  expect(link.href).toBe(url);
  expect(status.textContent).toBe("");
});

test("modified and non-primary clicks retain normal browser link behavior", async () => {
  const { link, status } = page({
    share() {
      throw Error("must not share");
    },
  });
  for (const overrides of [
    { ctrlKey: true },
    { metaKey: true },
    { shiftKey: true },
    { altKey: true },
    { button: 1 },
    { button: 2 },
  ]) {
    const event = click(overrides);
    await link.click(event);
    expect(event.defaultPrevented).toBe(false);
  }
  expect(link.href).toBe(url);
  expect(status.textContent).toBe("");
});

test("unavailable or failed native sharing copies the link and announces it", async () => {
  for (const native of [
    {},
    {
      share() {
        throw Error("must not share");
      },
      canShare: () => false,
    },
    {
      share: async () => {
        throw new DOMException("Blocked", "NotAllowedError");
      },
    },
  ]) {
    let copied;
    const { link, status } = page({
      ...native,
      clipboard: {
        writeText: async (value) => {
          copied = value;
        },
      },
    });
    await link.click(click());
    expect(copied).toBe(url);
    expect(status.textContent).toBe("הקישור הועתק.");
  }
});

test("canceling native sharing does not copy the link", async () => {
  const { link, status } = page({
    share: async () => {
      throw new DOMException("Canceled", "AbortError");
    },
    clipboard: {
      writeText() {
        throw Error("must not copy");
      },
    },
  });
  await link.click(click());
  expect(status.textContent).toBe("השיתוף בוטל או שאין יעד זמין.");
});

test("a pending earlier share cannot silently block another activation", async () => {
  let requests = 0;
  let copied;
  let rejectFirst;
  const { link, status } = page({
    share() {
      requests++;
      if (requests === 1) {
        return new Promise((_resolve, reject) => {
          rejectFirst = reject;
        });
      }
      return Promise.reject(
        new DOMException("Still pending", "InvalidStateError"),
      );
    },
    clipboard: {
      writeText: async (value) => {
        copied = value;
      },
    },
  });
  const first = link.click(click());
  await link.click(click());
  expect(requests).toBe(2);
  expect(copied).toBe(url);
  expect(status.textContent).toBe("הקישור הועתק.");
  rejectFirst(new DOMException("Late cancellation", "AbortError"));
  await first;
  expect(status.textContent).toBe("הקישור הועתק.");
});

test("sharing can reopen when the browser accepts another activation after a pending request", async () => {
  let requests = 0;
  const { link } = page({
    share() {
      requests++;
      return requests === 1 ? new Promise(() => {}) : Promise.resolve();
    },
  });
  void link.click(click());
  await link.click(click());
  expect(requests).toBe(2);
});

test("unavailable or denied clipboard explains native link copying without changing href", async () => {
  for (const navigator of [
    {},
    {
      clipboard: {
        writeText: async () => {
          throw Error("Denied");
        },
      },
    },
  ]) {
    const { link, status } = page(navigator);
    await link.click(click());
    expect(link.href).toBe(url);
    expect(status.textContent).toContain("לחיצה ארוכה על ״שיתוף״");
  }
});

test("all sharing messages remain for five seconds, then disappear", async () => {
  for (const navigator of [
    {},
    { clipboard: { writeText: async () => {} } },
    {
      share: async () => {
        throw new DOMException("Canceled", "AbortError");
      },
    },
  ]) {
    const { link, status, advance } = page(navigator);
    await link.click(click());
    const message = status.textContent;
    expect(message).not.toBe("");
    advance(4999);
    expect(status.textContent).toBe(message);
    advance(1);
    expect(status.textContent).toBe("");
  }
});

test("another sharing attempt gives the new message a full five seconds", async () => {
  const { link, status, advance } = page({});
  await link.click(click());
  advance(4000);
  await link.click(click());
  advance(1000);
  expect(status.textContent).toContain("לחיצה ארוכה");
  advance(3999);
  expect(status.textContent).toContain("לחיצה ארוכה");
  advance(1);
  expect(status.textContent).toBe("");
});
