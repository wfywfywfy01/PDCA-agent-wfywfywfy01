import { initAgent } from "./engine/index.mjs";
import agentDef from "./engine/agents/clippy/index.mjs";
import { POEMS } from "./poems.mjs";

const host =
  window.petHost ||
  (() => {
    const noop = () => {};
    return {
      ready: noop,
      hover: noop,
      dragStart: noop,
      drag: noop,
      dragEnd: noop,
      menu: noop,
      quit: noop,
      log: (m) => console.log("[pet]", m),
      onPos: noop,
      onPlay: noop,
      onSpeak: noop,
      onMute: noop,
      onList: noop,
    };
  })();

const params = new URLSearchParams(location.search);
const muted = params.get("muted") === "1";
const smoke = params.get("smoke") === "1";
const diag = params.get("diag") === "1";
const testDblclick = params.get("testDblclick") === "1";

let el = null;
let agent = null;
let dragging = false;
// set right after a press so the second press of a double click cannot start a drag
let suppressDragUntil = 0;

function log(message) {
  try {
    host.log(message);
  } catch (e) {}
}

function silenceSounds(on) {
  const sounds = agent && agent._animator && agent._animator._sounds;
  if (!sounds) return;
  const keys = Object.keys(sounds);
  for (let i = 0; i < keys.length; i += 1) {
    const audio = sounds[keys[i]];
    if (audio) audio.muted = on;
  }
}

function scheduleReposition() {
  if (!agent) return;
  setTimeout(function () {
    if (agent) agent.reposition();
  }, 30);
}

// ---------------------------------------------------------------- 双击：随机动作 + 随机台词
// 备用：这些动作可能不存在于当前 agent 数据里，playRandomAction 会先过滤
const FALLBACK_ACTIONS = [
  "Greeting",
  "Congratulate",
  "Wave",
  "Thinking",
  "Explain",
  "GetAttention",
  "GetArtsy",
  "GetTechy",
  "GetWizardy",
  "GoodBye",
  "Writing",
  "Save",
  "Print",
  "Searching",
  "Processing",
  "Alert",
  "CheckingSomething",
  "EmptyTrash",
  "Hearing_1",
  "SendMail",
  "IdleEyeBrowRaise",
  "IdleFingerTap",
  "IdleHeadScratch",
  "RestPose",
];

const PHRASES = [
  "需要我帮你看点什么吗？",
  "又见面啦～",
  "这份报表我瞅着有点眼熟。",
  "别点我啦，快去写日报！",
  "日报交了吗？我先记小本本上。",
  "要我给你讲个回形针的冷笑话吗？",
  "拖我去哪儿都行，别拖到回收站就好。",
  "你今天的重点客户跟进了吗？",
  "我在这儿待命，随叫随到。",
  "刚才那个数对上了，放心。",
  "报告老板，我今天一根都没弯。",
  "有需要尽管双击我。",
  "这个月目标，咱们还差一点点。",
  "我看你眉头一皱，是不是哪个经销商又拖了？",
  "摸鱼可以，别忘了我还盯着你。",
  "会议纪要记得同步给我。",
];

function pick(list) {
  return list[Math.floor(Math.random() * list.length)];
}

// 双击背诗用的诗库，一格一条 "诗句|出处"。诗句和出处分两行显示（见 sayNow）。
const POEMS_PARSED = POEMS.map(function (raw) {
  const i = raw.lastIndexOf("|");
  return { t: raw.slice(0, i), a: raw.slice(i + 1) };
});
// 双击时背诗的概率，其余概率说 PHRASES 里的工作台词
const POEM_RATIO = 0.8;
// 气泡停留时长：按字数给，长的诗句别刚出来就收（实测读 45 字约 6 秒）
function holdFor(text) {
  return Math.max(2400, Math.min(7000, 1200 + 110 * text.length));
}

function playRandomAction() {
  if (!agent) return null;
  let pool = FALLBACK_ACTIONS.filter(function (n) {
    return agent.hasAnimation(n);
  });
  if (!pool.length) pool = agent.animations();
  const name = pick(pool);
  agent.play(name);
  return name;
}

function speakRandom() {
  if (!agent) return null;
  const text = pick(PHRASES);
  agent.speak(text);
  return text;
}

// The engine serialises animations and speech on one queue and only draws a new
// animation on the next frame timer. Measured from the sprite data: every Clippy
// animation changes its first pixel after 100 ms, so none of the perceived lag
// is in the artwork - it is all engine overhead. The helpers below remove it.
const ANIM_CAP_MS = 2800; // longest slice of a random animation we allow

const REACTIVE_ACTIONS = [
  "GetAttention",
  "Wave",
  "Alert",
  "Thinking",
  "Explain",
  "GetTechy",
  "GetArtsy",
  "CheckingSomething",
  "SendMail",
  "Writing",
  "Save",
  "Print",
  "Searching",
  "EmptyTrash",
  "GetWizardy",
];

// Drop everything the engine still believes is in flight. play() refuses to
// start while an idle animation is finishing (the _idlePromise gate), and a
// cleared queue can leave _active stuck true - both made the first double click
// after an idle stretch feel late.
function unblockEngine() {
  try {
    agent._idlePromise = null;
    agent._idleResolve = null;
  } catch (e) {
    log("idle reset failed: " + e);
  }
  try {
    if (agent._queue) {
      agent._queue._queue = [];
      agent._queue._active = false;
    }
  } catch (e) {
    log("queue reset failed: " + e);
  }
}

// Paint frame 0 right now instead of waiting for the previous animation's frame
// timer (which can be several hundred ms away).
function drawNow() {
  try {
    const an = agent._animator;
    window.clearTimeout(an._loop);
    an._step();
  } catch (e) {
    log("draw failed: " + e);
  }
}

// Say the line in parallel with the animation. Queued speech only starts after
// the animation finished - that is what pushed the balloon seconds behind the
// click.
function sayNow(text, hold) {
  const b = agent._balloon;
  if (!b) return;
  try {
    if (b._hiding) {
      window.clearTimeout(b._hiding);
      b._hiding = null;
    }
    b._hidden = false;
    // hide() 用的是这个常量，说话前调整即可；否则长句子会被默认的 2 秒切掉
    b.CLOSE_BALLOON_DELAY = hold || 2200;
    b.speak(function () {}, text);
  } catch (e) {
    log("say failed: " + e);
  }
}

function doRandomInteraction() {
  const t0 = performance.now();
  if (!agent) return;
  // stop whatever is playing and hide the balloon, then clear the engine state
  // that would otherwise make the new animation wait its turn
  try {
    agent.stop();
  } catch (e) {
    log("agent.stop failed: " + e);
  }
  unblockEngine();
  let pool = REACTIVE_ACTIONS.filter(function (n) {
    return agent.hasAnimation(n);
  });
  if (!pool.length) pool = FALLBACK_ACTIONS.filter(function (n) {
    return agent.hasAnimation(n);
  });
  if (!pool.length) pool = agent.animations();
  const name = pick(pool);
  const poem = Math.random() < POEM_RATIO ? pick(POEMS_PARSED) : null;
  const text = poem ? poem.t + "\n——" + poem.a : pick(PHRASES);

  // starts synchronously; the engine's timeout later walks the exit branch and
  // drops back to an idle animation
  agent.play(name, ANIM_CAP_MS);
  drawNow(); // first moved frame on screen in this same tick
  sayNow(text, holdFor(text)); // balloon appears together with the motion

  const dt = Math.round(performance.now() - t0);
  log(
    "double click -> action=" +
      name +
      (poem ? " poem=" : " say=") +
      text.replace(/\n/g, " ") +
      " dispatch=" +
      dt +
      "ms",
  );
}

function bindDrag() {
  el.addEventListener("mousedown", function (e) {
    if (e.button !== 0) return;
    e.preventDefault();
    // double clicks must not turn into a drag; the dblclick handler takes over
    if (Date.now() < suppressDragUntil) {
      log("mousedown during double-click window -> drag suppressed");
      return;
    }
    dragging = true;
    // hand the cursor's screen position to the main process, which moves the
    // window by the pointer delta (setPosition), throttled to 16 ms
    host.dragStart({ x: Math.round(e.screenX), y: Math.round(e.screenY) });
    const startX = e.clientX;
    const startY = e.clientY;
    let started = false;
    const THRESHOLD = 2;

    function onMove(ev) {
      const sx = Math.round(ev.screenX);
      const sy = Math.round(ev.screenY);
      if (!started) {
        if (Math.abs(ev.clientX - startX) < THRESHOLD && Math.abs(ev.clientY - startY) < THRESHOLD) return;
        started = true;
        log("drag move begins");
      }
      host.dragMove({ x: sx, y: sy });
    }
    function onUp() {
      dragging = false;
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      // only report a drag end if a real drag started, otherwise every plain
      // click would also end a "drag" and flood the log
      if (started) {
        host.dragEnd();
        scheduleReposition();
      }
      // if this press turns out to be the first half of a double click, the
      // following mousedown must not start a drag
      suppressDragUntil = Date.now() + 420;
      log("press up");
    }
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  });

  el.addEventListener("contextmenu", function (e) {
    e.preventDefault();
    host.menu();
  });

  // take over the double click completely: the engine binds its own dblclick
  // handler (which plays "ClickedOn"), and two handlers racing for the animation
  // made it look flaky. We play one random animation and one random line.
  try {
    el.removeEventListener("dblclick", agent._dblClickHandle);
  } catch (e) {
    log("could not detach engine dblclick: " + e);
  }

  el.addEventListener("dblclick", function () {
    dragging = false;
    suppressDragUntil = Date.now() + 420;
    doRandomInteraction();
  });
}

// diagnostic hook: lets the main process (or a human in DevTools) see what the
// renderer thinks the sprite rectangle is
window.__petRect = function () {
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return {
    left: Math.round(r.left),
    top: Math.round(r.top),
    width: Math.round(r.width),
    height: Math.round(r.height),
    screenX: window.screenX,
    screenY: window.screenY,
    display: getComputedStyle(el).display,
  };
};

// Diagnostics: log every mouse event that actually reaches the renderer, so a
// "mouse input never arrives" problem is provable from pet.log alone.
// Mouse-event diagnostics: only with --diag, they cost a log write per event.
if (diag) {
  ["mousedown", "mouseup", "dblclick", "contextmenu"].forEach(function (type) {
    document.addEventListener(
      type,
      function (e) {
        log(
          "evt " +
            type +
            " target=" +
            (e.target && e.target.id ? e.target.id : e.target && e.target.tagName) +
            " at " +
            Math.round(e.clientX) +
            "," +
            Math.round(e.clientY),
        );
      },
      true,
    );
  });
}

// Click-through is decided entirely by the main process (it polls the OS cursor),
// so the renderer must NOT report hover: doing it per mousemove cost one IPC
// message per event and the reports fought the hit loop.

window.addEventListener("contextmenu", function (e) {
  e.preventDefault();
});
window.addEventListener("resize", scheduleReposition);

host.onPos(function (pos) {
  if (!el || dragging) return;
  el.style.left = pos.x + "px";
  el.style.top = pos.y + "px";
});

  host.onPlay(function (name) {
  if (!agent) return;
  if (name === "__random__") doRandomInteraction();
  else agent.play(name);
});

host.onSpeak(function (text) {
  if (agent) agent.speak(text);
});

host.onMute(function (flag) {
  silenceSounds(flag);
});

host.onList(function () {
  if (agent) log("animations(" + agent.animations().length + "): " + agent.animations().join(", "));
});

// QA hooks (used by --smoke and by manual testing in DevTools)
window.__playAnim = function (name) {
  if (!agent) return false;
  if (name === "__random__") {
    agent.animate();
    return true;
  }
  return agent.play(name);
};
window.__speak = function (text) {
  if (agent) agent.speak(text);
};
window.__petInfo = function () {
  return agent ? { animations: agent.animations().length, current: agent._animator.currentAnimationName } : null;
};

async function boot() {
  agent = await initAgent(agentDef);
  el = agent._el;
  el.id = "pet";
  el.style.position = "absolute";
  el.style.left = (Number(params.get("x")) || 0) + "px";
  el.style.top = (Number(params.get("y")) || 0) + "px";

  silenceSounds(muted);
  bindDrag();
  agent.show();

  // the engine paints on the next animation frame, so size it after that
  setTimeout(function () {
    const r = el.getBoundingClientRect();
    const info = {
      w: el.offsetWidth || Math.round(r.width) || 124,
      h: el.offsetHeight || Math.round(r.height) || 93,
      animations: agent.animations().length,
      muted: muted,
      display: getComputedStyle(el).display,
    };
    host.ready(info);
    log("booted " + JSON.stringify(info));
  }, 300);

  // The engine builds the balloon with inline styles only (no class), so give it
  // one: the stylesheet can then fine-tune it, and it can be found for debugging.
  try {
    if (agent._balloon && agent._balloon._balloon) {
      agent._balloon._balloon.classList.add("clippy-balloon");
      agent._balloon._balloon.setAttribute("data-role", "balloon");
    }
    // 背诗时诗句和出处分两行，默认的 white-space 会把换行折成空格
    if (agent._balloon && agent._balloon._content) {
      agent._balloon._content.style.whiteSpace = "pre-line";
    }
  } catch (e) {
    log("balloon class tagging failed: " + e);
  }

  if (smoke) {
    setTimeout(function () {
      doRandomInteraction();
    }, 2500);
  }

  // Isolated balloon check: speaks directly (no animation queue in front of it)
  // and reports the DOM state, so "balloon does not show" can be told apart from
  // "balloon is queued behind an animation".
  if (params.get("testBalloon") === "1") {
    setTimeout(function () {
      agent.speak("测试气泡：会议纪要记得同步给我。");
    }, 600);
    [1400, 2600, 3800, 5000].forEach(function (ms) {
      setTimeout(function () {
        log("test-balloon at " + ms + "ms: " + window.__balloonState());
      }, ms);
    });
  }

  // Longest poem in the library, spoken through the real double-click path, so
  // "the balloon still fits the window" is checked against the worst case.
  if (params.get("testPoem") === "1") {
    setTimeout(function () {
      const longest = POEMS_PARSED.slice().sort(function (a, b) {
        return b.t.length + b.a.length - (a.t.length + a.a.length);
      })[0];
      const text = longest.t + "\n——" + longest.a;
      log("test-poem longest(" + text.length + " chars): " + JSON.stringify(longest));
      sayNow(text, holdFor(text));
      [500, 1600].forEach(function (ms) {
        setTimeout(function () {
          log("test-poem at " + ms + "ms: " + window.__balloonState());
        }, ms);
      });
      setTimeout(function () {
        host.quit();
      }, 3000);
    }, 700);
  }

  // Automated check for the double-click behaviour: fires two real press/release
  // pairs and reports what the handler chose. Enabled with --test-dblclick.
  if (testDblclick) {
    setTimeout(function () {
      const opts = { bubbles: true, cancelable: true, detail: 2, button: 0, clientX: 60, clientY: 50 };
      // sample what is on screen a moment after the click: the animation must
      // already be the random one (not an Idle*) and the balloon must be up
      const samples = [];
      const snap = function (start) {
        const an = agent && agent._animator;
        const b = agent && agent._balloon && agent._balloon._balloon;
        return {
          t: Math.round(performance.now() - start),
          anim: an ? an.currentAnimationName : "?",
          frame: an ? an._currentFrameIndex : -1,
          balloon:
            b && getComputedStyle(b).display === "block"
              ? (b.textContent || "").slice(0, 10)
              : "-",
        };
      };
      const t0 = performance.now();
      [120, 300, 900, 3000].forEach(function (ms) {
        setTimeout(function () {
          samples.push(snap(t0));
        }, ms);
      });
      el.dispatchEvent(new MouseEvent("mousedown", opts));
      el.dispatchEvent(new MouseEvent("mouseup", opts));
      el.dispatchEvent(new MouseEvent("dblclick", opts));
      setTimeout(function () {
        log("test-dblclick timeline: " + JSON.stringify(samples));
        setTimeout(function () {
          host.quit();
        }, 300);
      }, 3200);
      setTimeout(function () {
        const info = window.__petInfo ? window.__petInfo() : null;
        const b = agent && agent._balloon && agent._balloon._balloon ? agent._balloon._balloon : null;
        let balloonState = "none";
        if (b) {
          const r = b.getBoundingClientRect();
          balloonState = JSON.stringify({
            display: getComputedStyle(b).display,
            text: (b.textContent || "").slice(0, 24),
            rect: { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) },
            win: { w: window.innerWidth, h: window.innerHeight },
            fits: r.left >= 0 && r.top >= 0 && r.right <= window.innerWidth && r.bottom <= window.innerHeight,
          });
        }
        log(
          "test-dblclick result: current=" +
            (info ? info.current : "?") +
            " balloon=" +
            balloonState,
        );
      }, 900);
    }, 700);
  }
}

// Probe hook so the main process can log the balloon's real DOM state right
// before a screenshot: distinguishes "not shown" from "clipped by the window".
window.__balloonState = function () {
  try {
    const b = agent && agent._balloon && agent._balloon._balloon;
    if (!b) return "no-balloon";
    const r = b.getBoundingClientRect();
    return JSON.stringify({
      display: getComputedStyle(b).display,
      text: (b.textContent || "").slice(0, 20),
      rect: { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) },
      win: { w: window.innerWidth, h: window.innerHeight },
      fits: r.left >= 0 && r.top >= 0 && r.right <= window.innerWidth && r.bottom <= window.innerHeight,
    });
  } catch (e) {
    return "probe-error: " + e;
  }
};

boot().catch(function (err) {
  log("boot failed: " + (err && err.stack ? err.stack : err));
});
