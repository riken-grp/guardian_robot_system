const STATUS_INTERVAL_MS = 1000;  // ROS から受け取る状態 (バッテリー・位置・聞き取り) の更新間隔
const BLACKBOARD_INTERVAL_MS = 3000;  // DB の情報 (行動・シナリオ) の更新間隔
const TIMELINE_INTERVAL_MS = 5000;  // シナリオのタイムラインの更新間隔
const DESTINATIONS_INTERVAL_MS = 10000;  // 「部屋を見に行く」の行き先 (DB) の更新間隔
const LOW_BATTERY = Number(document.body.dataset.lowBattery);
const SVG_NS = 'http://www.w3.org/2000/svg';

/**
 * fn を interval ミリ秒ごとに実行する (前回の完了を待ってから次を予約する).
 * タブが裏に回っている間は止め, 表に戻ったらすぐ実行する. 返り値の関数を呼ぶと今すぐ実行する
 */
function poll(fn, interval) {
    let timer = null;
    let running = false;
    async function run() {
        clearTimeout(timer);
        if (running) return;
        running = true;
        try {
            await fn();
        } finally {
            running = false;
            if (!document.hidden) timer = setTimeout(run, interval);
        }
    }
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) clearTimeout(timer);
        else run();
    });
    run();
    return run;
}

/** JSON を取得する. エラー時はサーバのメッセージ付きで例外にする */
async function fetchJson(url, init = {}) {
    const res = await fetch(url, { cache: 'no-store', ...init });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'HTTP error: ' + res.status);
    return data;
}

function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
}

function svgEl(tag, attrs) {
    const node = document.createElementNS(SVG_NS, tag);
    for (const [key, value] of Object.entries(attrs || {})) node.setAttribute(key, value);
    return node;
}

function timedItem(time, tagInfo, text) {
    const li = el('li', tagInfo ? 'actions__item' : 'actions__item actions__item--notag');
    li.append(el('span', 'actions__time', time));
    if (tagInfo) li.append(el('span', 'tag ' + tagInfo[1], tagInfo[0]));
    li.append(el('span', 'actions__text', text));
    return li;
}

// ---- 地図とロボットの位置 ----
const mapView = (() => {
    const svg = document.getElementById('map-svg');
    if (!svg) return { setPose() {}, setGoal() {} };
    const message = document.getElementById('map-message');
    const status = document.getElementById('map-status');
    let info = null;
    let robot = null;
    let goal = null;
    let pendingGoal = null;

    const toPx = (x, y) => [(x - info.left_x) / info.resolution, (info.top_y - y) / info.resolution];

    // 場所の点と名前を描く. 名前は互いに重ならない位置 (上下・斜め・引き出し線付き) を順に探す
    function placeLabels(parent, locations) {
        const FONT = 20, LINE = FONT + 4;
        const placed = [];
        const overlaps = (box) => placed.some(b =>
            box.x < b.x + b.w && b.x < box.x + box.w && box.y < b.y + b.h && b.y < box.y + box.h);
        const items = locations.map(loc => ({ loc, p: toPx(loc.x, loc.y) }))
            .sort((a, b) => a.p[0] - b.p[0]);
        for (const { p: [px, py] } of items) placed.push({ x: px - 7, y: py - 7, w: 14, h: 14 });
        for (const { loc, p: [px, py] } of items) {
            const g = svgEl('g', { class: loc.active ? 'map__place' : 'map__place map__place--inactive' });
            g.append(svgEl('circle', { cx: px, cy: py, r: 7 }));
            const width = loc.name.length * FONT * 0.68;
            let chosen = null;
            for (let step = 1; step <= 6 && !chosen; step++) {
                for (const dir of [-1, 1]) {
                    const cy = py + dir * (12 + (step - 1) * LINE) + (dir > 0 ? FONT : 0);
                    const box = { x: px - width / 2, y: cy - FONT, w: width, h: FONT + 2 };
                    if (!overlaps(box) && box.x >= 0 && box.x + box.w <= info.width) {
                        chosen = { cy, box, step };
                        break;
                    }
                }
            }
            if (!chosen) chosen = { cy: py - 12, box: { x: px - width / 2, y: py - 12 - FONT, w: width, h: FONT }, step: 1 };
            placed.push(chosen.box);
            if (chosen.step > 1) {  // 点から離れたときは引き出し線を描く
                const ly = chosen.cy > py ? chosen.box.y : chosen.box.y + chosen.box.h;
                g.append(svgEl('line', { x1: px, y1: py, x2: px, y2: ly, class: 'map__leader' }));
            }
            const label = svgEl('text', { x: px, y: chosen.cy, 'text-anchor': 'middle' });
            label.textContent = loc.name;
            g.append(label);
            parent.append(g);
        }
    }

    async function load() {
        try {
            const data = await fetchJson('/map.json');
            info = data.info;
            svg.setAttribute('viewBox', `0 0 ${info.width} ${info.height}`);
            svg.append(svgEl('image', { href: '/map.png?v=' + info.version, width: info.width, height: info.height }));
            const places = svgEl('g', { class: 'map__places' });
            svg.append(places);
            placeLabels(places, data.locations);
            goal = svgEl('g', { class: 'map__goal', visibility: 'hidden' });
            goal.append(svgEl('circle', { r: 16 }), svgEl('circle', { r: 5, class: 'map__goal-center' }));
            robot = svgEl('g', { class: 'map__robot', visibility: 'hidden' });
            robot.append(svgEl('circle', { r: 15 }), svgEl('path', { d: 'M 10 0 L -6 -8 L -3 0 L -6 8 Z' }));
            svg.append(goal, robot);
            svg.parentElement.hidden = false;
            message.hidden = true;
            if (pendingGoal !== null) setGoal(pendingGoal);
        } catch (error) {
            console.error('Map error:', error);
            message.textContent = '地図を取得できません';
        }
    }

    function setPose(pose) {
        if (!robot) return;
        if (!pose) {
            robot.setAttribute('visibility', 'hidden');
            status.textContent = '位置情報を受信していません';
            return;
        }
        const [px, py] = toPx(pose.x, pose.y);
        if (px < 0 || py < 0 || px > info.width || py > info.height) {
            robot.setAttribute('visibility', 'hidden');
            status.textContent = `表示範囲の外にいます (${pose.x.toFixed(2)}, ${pose.y.toFixed(2)})`;
            return;
        }
        const deg = -pose.yaw * 180 / Math.PI;  // 画面の y 軸は下向きなので回転を反転
        robot.setAttribute('transform', `translate(${px} ${py}) rotate(${deg})`);
        robot.setAttribute('visibility', 'visible');
        status.textContent = `現在位置 (${pose.x.toFixed(2)}, ${pose.y.toFixed(2)})`;
    }

    function setGoal(target) {
        pendingGoal = target;
        if (!goal) return;
        if (!target) {
            goal.setAttribute('visibility', 'hidden');
            return;
        }
        const [px, py] = toPx(target.x, target.y);
        goal.setAttribute('transform', `translate(${px} ${py})`);
        goal.setAttribute('visibility', 'visible');
    }

    load();
    return { setPose, setGoal };
})();

// ---- シナリオのタイムライン (メインを1本の線にし, 割り込みは下の段に枝分かれさせる) ----
(() => {
    const svg = document.getElementById('timeline-svg');
    if (!svg) return;
    const message = document.getElementById('timeline-message');
    const buttons = document.querySelectorAll('.segmented__button[data-minutes]');
    const STORAGE_KEY = 'timelineMinutes';
    const AXIS = 26, LANE = 30, GAP = 22, PAD = 8;
    let minutes = 30;
    let lastData = null;
    let refresh = () => {};
    try { minutes = Number(localStorage.getItem(STORAGE_KEY)) || minutes; } catch (e) {}

    function selectButton() {
        buttons.forEach(b => b.setAttribute('aria-pressed', String(Number(b.dataset.minutes) === minutes)));
    }
    buttons.forEach(b => b.addEventListener('click', () => {
        minutes = Number(b.dataset.minutes);
        try { localStorage.setItem(STORAGE_KEY, String(minutes)); } catch (e) {}
        selectButton();
        refresh();
    }));
    selectButton();

    const charWidth = c => (c.charCodeAt(0) > 255 ? 14 : 8);
    function fitText(text, width) {
        const chars = [...text];
        if (chars.reduce((w, c) => w + charWidth(c), 0) <= width) return text;
        let used = 14;  // … の分
        let n = 0;
        while (n < chars.length && used + charWidth(chars[n]) <= width) used += charWidth(chars[n++]);
        return n >= 2 ? chars.slice(0, n).join('') + '…' : '';
    }

    function fmt(ms) {
        const d = new Date(ms);
        return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
    }

    function render(data) {
        const width = Math.max(svg.clientWidth || svg.parentElement.clientWidth || 800, 320);
        const maxDepth = Math.max(0, ...data.items.map(i => i.depth));
        const laneY = d => AXIS + d * (LANE + GAP);
        const height = laneY(maxDepth) + LANE + PAD;
        const span = data.now - data.start;
        const x = t => PAD + Math.min(Math.max((t - data.start) / span, 0), 1) * (width - PAD * 2);
        svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
        svg.setAttribute('height', height);
        const nodes = [];

        // 時刻の目盛り (6〜10本程度になる間隔を選ぶ)
        const stepMin = [1, 2, 5, 10, 15, 30, 60].find(m => span / (m * 60000) <= 10) || 120;
        const step = stepMin * 60000;
        for (let t = Math.ceil(data.start / step) * step; t <= data.now; t += step) {
            nodes.push(svgEl('line', { x1: x(t), x2: x(t), y1: AXIS - 6, y2: height, class: 'timeline__grid' }));
            const label = svgEl('text', { x: x(t), y: AXIS - 10, 'text-anchor': 'middle', class: 'timeline__tick' });
            label.textContent = fmt(t);
            nodes.push(label);
        }

        const byId = Object.fromEntries(data.items.map(i => [i.id, i]));
        const sorted = [...data.items].sort((a, b) => a.depth - b.depth || a.start - b.start);
        let mainIndex = 0;
        for (const item of sorted) {
            const x1 = x(item.start), x2 = Math.max(x(item.end), x1 + 6);
            const y = laneY(item.depth);
            // 親の段から枝分かれ・合流する線
            if (item.depth > 0) {
                const parent = byId[item.parent];
                const py = laneY(parent ? parent.depth : item.depth - 1) + LANE;
                let d = `M ${x1} ${py} C ${x1} ${y - GAP / 2}, ${x1} ${y - GAP / 2}, ${x1} ${y}`;
                if (!item.open) d += ` M ${x2} ${y} C ${x2} ${y - GAP / 2}, ${x2} ${y - GAP / 2}, ${x2} ${py}`;
                nodes.push(svgEl('path', { d, class: 'timeline__branch' }));
            }
            let cls = item.interruption ? 'timeline__bar timeline__bar--interrupt'
                : `timeline__bar timeline__bar--main${mainIndex++ % 2 ? ' timeline__bar--alt' : ''}`;
            if (item.open) cls += ' timeline__bar--open';
            if (item.id === tip.itemId) cls += ' timeline__bar--active';
            // マウスを重ねる・フォーカスする・クリックすると詳細を出す (下の tip)
            const g = svgEl('g', {
                class: cls, 'data-id': item.id, tabindex: 0, role: 'button',
                'aria-label': `${item.name}（${item.start_text}–${item.end_text || '実行中'}）の詳細`,
            });
            g.append(svgEl('rect', { x: x1, y, width: x2 - x1, height: LANE, rx: 4 }));
            // 名前は棒に収まる分だけ描く (省略したときは … を付ける. 全体は詳細に出る)
            const label = fitText(item.name, x2 - x1 - 12);
            if (label) {
                const text = svgEl('text', { x: x1 + 6, y: y + LANE / 2 + 5 });
                text.textContent = label;
                g.append(text);
            }
            nodes.push(g);
        }
        const nowX = x(data.now);
        nodes.push(svgEl('line', { x1: nowX, x2: nowX, y1: AXIS - 6, y2: height, class: 'timeline__now' }));
        svg.replaceChildren(...nodes);
        tip.refresh(data);
    }

    // ---- シナリオの詳細 (マウスを重ねると出る. クリック/タップ/Enter で固定) ----
    const tip = (() => {
        const box = el('div', 'tl-tip');
        box.hidden = true;
        box.setAttribute('role', 'dialog');
        box.setAttribute('aria-label', 'シナリオの詳細');
        document.body.append(box);
        const definitions = new Map();  // scenario_id -> Promise (定義はめったに変わらないので使い回す)
        const EXIT_CODES = {
            success: '成功', return: '元のシナリオへ戻った', failure: '失敗', redirect: '別のシナリオへ移った',
            aborted: '中断', error: 'エラー',
        };
        const state = { itemId: null, pinned: false, data: null };

        function duration(ms) {
            const sec = Math.max(Math.round(ms / 1000), 0);
            const h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s = sec % 60;
            return h ? `${h}時間${m}分` : m ? `${m}分${s}秒` : `${s}秒`;
        }

        function row(list, label, value) {
            if (value === undefined || value === null || value === '') return;
            list.append(el('dt', '', label), el('dd', '', String(value)));
        }

        function definitionOf(item) {
            const key = `${item.scenario_id}:${item.interruption}`;
            if (!definitions.has(key)) {
                const url = `/scenario_definition/${encodeURIComponent(item.scenario_id)}?interruption=${item.interruption}`;
                definitions.set(key, fetchJson(url).catch(error => {
                    definitions.delete(key);  // 次に開いたときに取り直す
                    return { error: error.message };
                }));
            }
            return definitions.get(key);
        }

        function renderDefinition(section, def) {
            section.replaceChildren(el('h4', '', 'シナリオの定義'));
            if (def.error) {
                section.append(el('p', 'muted', def.error));
                return;
            }
            if (def.description) section.append(el('p', '', def.description));
            const list = el('dl', 'tl-tip__list');
            row(list, '種類', def.kind);
            if (def.status && def.status !== 'active') row(list, '状態', `無効（${def.status}）`);
            row(list, '優先度', def.priority);
            row(list, '発動条件', def.condition);
            if (def.returns !== null && def.returns !== undefined) row(list, '終了後', def.returns ? '元のシナリオへ戻る' : '戻らない');
            if (def.force_interrupt) row(list, '強制割り込み', 'する');
            if (def.important) row(list, '重要', 'はい');
            const types = Object.entries(def.event_types).map(([t, n]) => `${t} ${n}`).join('、');
            row(list, 'イベント', `${def.event_count}件${types ? `（${types}）` : ''}`);
            section.append(list);
            if (def.events.length) {
                const events = el('ol', 'tl-tip__events');
                events.append(...def.events.map(text => el('li', '', text)));
                section.append(events);
                if (def.event_count > def.events.length) {
                    section.append(el('p', 'muted', `ほか ${def.event_count - def.events.length} 件`));
                }
            }
        }

        function fill(item) {
            const data = state.data;
            const head = el('div', 'tl-tip__head');
            head.append(el('strong', 'tl-tip__name', item.name));
            head.append(el('span', item.interruption ? 'tag tag--warning' : 'tag tag--info',
                item.interruption ? `割り込み（深さ ${item.depth}）` : 'メイン'));
            if (item.open) head.append(el('span', 'tag tag--success', '実行中'));
            const close = el('button', 'tl-tip__close', '閉じる');
            close.type = 'button';
            close.hidden = !state.pinned;
            close.addEventListener('click', hide);
            head.append(close);

            const list = el('dl', 'tl-tip__list');
            row(list, '時間', `${item.start_text}–${item.end_text || '現在'}（${duration(item.end - item.start)}）`);
            if (item.exit_code) row(list, '終わり方', EXIT_CODES[item.exit_code] || item.exit_code);
            const parent = data.items.find(i => i.id === item.parent);
            if (parent) row(list, '割り込んだ先', `${parent.name}（${parent.start_text}–）`);
            const children = data.items.filter(i => i.parent === item.id);
            if (children.length) {
                const names = [...new Set(children.map(c => c.name))].join('、');
                row(list, '割り込まれた回数', `${children.length}回（${names}）`);
            }
            const defSection = el('section', 'tl-tip__def');
            defSection.append(el('p', 'muted', 'シナリオの定義を読み込み中…'));
            box.replaceChildren(head, list, defSection);
            if (item.scenario_id) {
                definitionOf(item).then(def => {
                    if (state.itemId === item.id) renderDefinition(defSection, def);
                });
            } else {
                defSection.replaceChildren();
            }
        }

        function place(clientX, clientY) {
            const margin = 12;
            const rect = box.getBoundingClientRect();
            let left = clientX + 16, top = clientY + 16;
            if (left + rect.width > window.innerWidth - margin) left = Math.max(margin, clientX - rect.width - 16);
            if (top + rect.height > window.innerHeight - margin) top = Math.max(margin, clientY - rect.height - 16);
            box.style.left = `${left}px`;
            box.style.top = `${top}px`;
        }

        function show(itemId, clientX, clientY) {
            const item = state.data && state.data.items.find(i => i.id === itemId);
            if (!item) return;
            if (state.itemId !== itemId) {
                state.itemId = itemId;
                fill(item);
                markActive();
            }
            box.hidden = false;
            place(clientX, clientY);
        }

        function hide() {
            state.itemId = null;
            state.pinned = false;
            box.hidden = true;
            markActive();
        }

        function markActive() {
            svg.querySelectorAll('.timeline__bar').forEach(g =>
                g.classList.toggle('timeline__bar--active', g.dataset.id === state.itemId));
        }

        const barOf = target => target.closest && target.closest('.timeline__bar');
        const centerOf = g => {
            const r = g.getBoundingClientRect();
            return [r.left + Math.min(r.width / 2, 40), r.bottom - 8];
        };

        svg.addEventListener('pointermove', e => {
            const g = barOf(e.target);
            if (state.pinned) return;
            if (g && e.pointerType === 'mouse') show(g.dataset.id, e.clientX, e.clientY);
            else if (!g && e.pointerType === 'mouse') hide();
        });
        svg.addEventListener('pointerleave', () => { if (!state.pinned) hide(); });
        svg.addEventListener('click', e => {
            const g = barOf(e.target);
            if (!g) return;
            if (state.pinned && state.itemId === g.dataset.id) { hide(); return; }
            state.pinned = true;
            state.itemId = null;  // 閉じるボタンを出すため作り直す
            show(g.dataset.id, e.clientX, e.clientY);
        });
        svg.addEventListener('focusin', e => {
            const g = barOf(e.target);
            if (g && !state.pinned) show(g.dataset.id, ...centerOf(g));
        });
        svg.addEventListener('focusout', () => { if (!state.pinned) hide(); });
        svg.addEventListener('keydown', e => {
            const g = barOf(e.target);
            if (g && (e.key === 'Enter' || e.key === ' ')) {
                e.preventDefault();
                state.pinned = !state.pinned || state.itemId !== g.dataset.id;
                state.itemId = null;
                if (state.pinned) show(g.dataset.id, ...centerOf(g)); else hide();
            }
        });
        document.addEventListener('keydown', e => { if (e.key === 'Escape' && !box.hidden) hide(); });
        document.addEventListener('pointerdown', e => {
            if (state.pinned && !box.contains(e.target) && !barOf(e.target)) hide();
        });

        return {
            get itemId() { return state.itemId; },
            // タイムラインを描き直したとき: 表示中のシナリオの時間などを新しいデータで更新する
            refresh(data) {
                state.data = data;
                if (state.itemId === null) return;
                const item = data.items.find(i => i.id === state.itemId);
                if (!item) { hide(); return; }
                const [left, top] = [parseFloat(box.style.left), parseFloat(box.style.top)];
                const def = box.querySelector('.tl-tip__def');
                const keepDef = def && def.querySelector('h4');
                fill(item);
                if (keepDef) box.querySelector('.tl-tip__def').replaceWith(def);
                box.style.left = `${left}px`;
                box.style.top = `${top}px`;
            },
        };
    })();

    async function update() {
        try {
            const data = await fetchJson(`/timeline?minutes=${minutes}`);
            lastData = data;
            render(data);
            message.hidden = data.items.length > 0;
            message.textContent = 'この期間のシナリオの記録はありません';
        } catch (error) {
            console.error('Timeline error:', error);
            message.hidden = false;
            message.textContent = 'シナリオの遷移を取得できません（再試行しています）';
        }
    }
    let resizeFrame = 0;
    window.addEventListener('resize', () => {
        cancelAnimationFrame(resizeFrame);
        resizeFrame = requestAnimationFrame(() => { if (lastData) render(lastData); });
    });
    refresh = poll(update, TIMELINE_INTERVAL_MS);
})();

// ---- ROS から受け取る状態 (バッテリー・位置・聞き取った言葉) の自動更新 ----
const batteryValue = document.getElementById('battery-value');
const batteryCharging = document.getElementById('battery-charging');
const batteryLow = document.getElementById('battery-low');
const heardList = document.getElementById('heard-list');
const heardEmpty = document.getElementById('heard-empty');
let lastHeard = '';

// 聞き取った言葉: 音声が残っているものはクリック (Enter / Space) でその時の音声を再生する
const clipPlayer = new Audio();
let playingClip = null;

// 発話者の顔画像があれば言葉の右に出す (無ければ同じ大きさの空きにして揃える). クリックで拡大表示する
function heardFace(item) {
    if (!item.face) return el('span', 'heard__face heard__face--none');
    const button = el('button', 'heard__face-button');
    button.type = 'button';
    button.dataset.face = item.face;
    button.setAttribute('aria-label', '発話者の顔を拡大：' + item.text);
    const img = el('img', 'heard__face');
    img.src = '/speech_face/' + encodeURIComponent(item.face);
    img.alt = '';
    img.width = img.height = 56;
    img.addEventListener('error', () => button.replaceWith(el('span', 'heard__face heard__face--none')));
    button.append(img);
    return button;
}

// 顔画像の拡大表示 (モーダル). Esc・背景クリック・閉じるボタンで閉じる
const faceDialog = document.getElementById('face-dialog');
function openFace(button) {
    if (!faceDialog) return;
    const li = button.closest('li');
    faceDialog.querySelector('img').src = '/speech_face/' + encodeURIComponent(button.dataset.face);
    faceDialog.querySelector('.face-dialog__caption').textContent =
        li ? `${li.querySelector('.actions__time').textContent}　${li.querySelector('.actions__text').textContent}` : '';
    faceDialog.showModal();
}
if (faceDialog) {
    faceDialog.addEventListener('click', event => {
        // 画像の外 (背景) か閉じるボタンのクリックで閉じる
        if (event.target === faceDialog || event.target.closest('.face-dialog__close')) faceDialog.close();
    });
}

function heardItem(item) {
    const playing = item.clip && item.clip === playingClip;
    const tag = !item.clip ? ['音声なし', 'tag--neutral'] : playing ? ['■ 停止', 'tag--warning'] : ['▶ 再生', 'tag--info'];
    const li = timedItem(item.time, tag, item.text);
    li.classList.add('heard__item');
    li.append(heardFace(item));
    if (!item.clip) return li;
    li.classList.add('actions__item--playable');
    li.dataset.clip = item.clip;
    li.tabIndex = 0;
    li.setAttribute('role', 'button');
    li.setAttribute('aria-pressed', String(playing));
    li.setAttribute('aria-label', (playing ? '停止：' : '音声を再生：') + item.text);
    return li;
}

function setPlayingClip(clip) {
    playingClip = clip;
    if (!heardList) return;
    for (const li of heardList.querySelectorAll('[data-clip]')) {
        const playing = li.dataset.clip === clip;
        const tag = li.querySelector('.tag');
        tag.textContent = playing ? '■ 停止' : '▶ 再生';
        tag.className = 'tag ' + (playing ? 'tag--warning' : 'tag--info');
        li.setAttribute('aria-pressed', String(playing));
        li.setAttribute('aria-label', (playing ? '停止：' : '音声を再生：') + li.querySelector('.actions__text').textContent);
    }
}

function toggleClip(clip) {
    if (clip === playingClip) {
        clipPlayer.pause();
        setPlayingClip(null);
        return;
    }
    clipPlayer.src = '/speech_clip/' + encodeURIComponent(clip);
    setPlayingClip(clip);
    clipPlayer.play().catch(error => {
        console.error('Clip error:', error);
        if (playingClip === clip) setPlayingClip(null);
        showNotification('音声を再生できませんでした（古い音声は消えています）', true);
    });
}
clipPlayer.addEventListener('ended', () => setPlayingClip(null));

if (heardList) {
    heardList.addEventListener('click', event => {
        const face = event.target.closest('[data-face]');
        if (face) {
            openFace(face);
            return;
        }
        const li = event.target.closest('[data-clip]');
        if (li) toggleClip(li.dataset.clip);
    });
    heardList.addEventListener('keydown', event => {
        if (event.target.closest('[data-face]')) return; // 顔のボタンは自身の click で拡大する
        const li = event.target.closest('[data-clip]');
        if (li && (event.key === 'Enter' || event.key === ' ')) {
            event.preventDefault();
            toggleClip(li.dataset.clip);
        }
    });
}

async function updateStatus() {
    try {
        const status = await fetchJson('/status');
        batteryValue.textContent = Math.round(status.battery) + '%';
        batteryCharging.hidden = !status.is_charging;
        batteryLow.hidden = status.is_charging || status.battery >= LOW_BATTERY;
        mapView.setPose(status.pose);
        const heard = JSON.stringify(status.heard);
        if (heardList && heard !== lastHeard) {
            lastHeard = heard;
            heardList.replaceChildren(...status.heard.map(heardItem));
            heardEmpty.hidden = status.heard.length > 0;
        }
    } catch (error) {
        console.error('Status error:', error);
    }
}
poll(updateStatus, STATUS_INTERVAL_MS);

// ---- DB の情報 (ロボットの行動・シナリオ) の自動更新 ----
const ACTION_STATUS = {
    waiting: ['待機中', 'tag--info'],
    is_playing: ['実行中', 'tag--warning'],
    done: ['完了', 'tag--success'],
    canceled: ['キャンセル', 'tag--neutral'],
    cancelled: ['キャンセル', 'tag--neutral'],
    stopped: ['中断', 'tag--neutral'],
    failed: ['失敗', 'tag--error'],
};
const actionsGroups = document.getElementById('actions-groups');
const actionsMessage = document.getElementById('actions-message');
const scenarioMessage = document.getElementById('scenario-message');
let lastActions = '';
let lastScenario = '';

function renderActions(kinds) {
    if (!actionsGroups) return;
    actionsGroups.replaceChildren(...kinds.map(group => {
        const section = el('section', `actions__group actions__group--${group.kind}`);
        section.append(el('h3', '', group.label));
        if (group.items.length === 0) {
            section.append(el('p', 'actions__empty', '最近の記録はありません'));
            return section;
        }
        const list = el('ol', 'actions__list');
        list.append(...group.items.map(item =>
            timedItem(item.time, ACTION_STATUS[item.status] || [item.status, 'tag--neutral'], item.text)));
        section.append(list);
        return section;
    }));
}

function renderScenario(scenario) {
    const current = document.getElementById('scenario-current');
    if (!current) return;
    const cur = scenario.current;
    document.getElementById('scenario-name').textContent = cur.name || '（なし）';
    const interrupt = document.getElementById('scenario-interrupt');
    interrupt.hidden = !cur.interrupted;
    interrupt.textContent = cur.interrupted ? `割り込み中：${cur.subscenario}` : '';
    document.getElementById('scenario-event').textContent =
        cur.event_index !== null && cur.event_index !== undefined ? `イベント ${cur.event_index}` : '';
    document.getElementById('scenario-processing').replaceChildren(
        ...cur.processing.map(label => el('span', 'tag tag--warning', label)));
    document.getElementById('scenario-updated').textContent = cur.updated ? `更新 ${cur.updated}` : '';
    document.getElementById('scenario-event').textContent =
        cur.event_index !== null && cur.event_index !== undefined
            ? `イベント ${cur.event_index}${cur.event_type ? `（${cur.event_type}）` : ''}` : '';
    renderWaits(cur);
    current.hidden = false;

    document.getElementById('scenario-history').replaceChildren(...scenario.history.map(item => {
        const tag = item.running ? ['実行中', 'tag--warning']
            : item.end ? [item.exit_code === 'success' ? '完了' : '終了', 'tag--success']
            : ['記録なし', 'tag--neutral'];
        const range = item.end ? `${item.start}–${item.end}` : item.start;
        const li = timedItem(range, tag, item.name);
        if (item.interruption) li.querySelector('.actions__text').append(el('span', 'tag tag--info scenario__inline-tag', '割り込み'));
        return li;
    }));
}

// 待ち状態. 入れ子は外側から順に並ぶ (最後が今の待ち). 残り時間は 1 秒ごとに数え直す
function renderWaits(cur) {
    const list = document.getElementById('scenario-waits');
    const received = performance.now();
    list.replaceChildren(...cur.waiting.map((w, i) => {
        const isCurrent = i === cur.waiting.length - 1;
        const li = el('li', isCurrent ? 'waits__item waits__item--current' : 'waits__item');
        li.style.marginLeft = `${i * 24}px`;
        const head = el('p', 'waits__head');
        head.append(el('span', 'waits__kind', w.kind));
        if (!isCurrent) head.append(el('span', 'tag tag--neutral', '外側'));
        if (w.interruption) head.append(el('span', 'tag tag--info', '割り込み中'));
        if (w.scenario_name) head.append(el('span', 'muted', w.scenario_name));
        li.append(head);
        if (w.condition) li.append(el('p', 'waits__detail', `条件：${w.condition}`));
        if (w.actions) li.append(el('p', 'waits__detail', `動作：${w.actions}`));
        const time = el('p', 'waits__time muted');
        if (w.remaining !== null) {
            time.dataset.remaining = w.remaining;
            time.dataset.timeout = w.timeout === null || w.timeout === undefined ? '' : w.timeout;
            time.dataset.received = received;
        } else if (w.started) {
            time.textContent = `${w.started} から`;
        }
        li.append(time);
        return li;
    }));
    document.getElementById('scenario-waits-empty').hidden = cur.waiting.length > 0;
    const last = document.getElementById('scenario-last-wait');
    last.hidden = !cur.last_wait;
    if (cur.last_wait) {
        const lw = cur.last_wait;
        last.textContent = `直前の待ち：${lw.kind}${lw.condition ? `（${lw.condition}）` : ''} → ${lw.result}（${lw.ended}）`;
    }
    document.getElementById('scenario-wait-note').hidden = cur.wait_supported;
    tickWaits();
}

function tickWaits() {
    for (const node of document.querySelectorAll('.waits__time[data-remaining]')) {
        const passed = (performance.now() - Number(node.dataset.received)) / 1000;
        const remaining = Math.max(Number(node.dataset.remaining) - passed, 0);
        const timeout = node.dataset.timeout ? ` / ${Number(node.dataset.timeout).toFixed(0)}秒` : '';
        node.textContent = `残り ${remaining.toFixed(0)}秒${timeout}`;
    }
}
setInterval(tickWaits, 1000);

async function updateBlackboard() {
    try {
        const data = await fetchJson('/blackboard');
        // 変化があった部分だけ描き直す (シナリオは待ちの残り時間で毎回変わるので行動とは別に比べる)
        const actionsJson = JSON.stringify([data.actions, data.goal]);
        if (actionsJson !== lastActions) {
            lastActions = actionsJson;
            renderActions(data.actions);
            mapView.setGoal(data.goal);
        }
        const scenarioJson = JSON.stringify(data.scenario);
        if (scenarioJson !== lastScenario) {
            lastScenario = scenarioJson;
            renderScenario(data.scenario);
        }
        if (actionsMessage) actionsMessage.hidden = true;
        if (scenarioMessage) scenarioMessage.hidden = true;
    } catch (error) {
        console.error('Blackboard error:', error);
        for (const msg of [actionsMessage, scenarioMessage]) {
            if (!msg) continue;
            msg.hidden = false;
            msg.textContent = 'DB から取得できません（再試行しています）';
        }
    }
}
poll(updateBlackboard, BLACKBOARD_INTERVAL_MS);

// 発話音声の再生 (WebSocket で受信した発話を順番に連続再生する)
const speechToggle = document.getElementById('speech-toggle');
if (speechToggle && !speechToggle.disabled) {
    const speechStatus = document.getElementById('speech-status');
    let audioCtx = null;
    let socket = null;
    let enabled = false;
    let nextStartTime = 0;

    function connectSpeech() {
        const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
        const ws = new WebSocket(`${scheme}://${location.host}/speech`);
        socket = ws;
        ws.binaryType = 'arraybuffer';
        ws.onopen = () => { if (audioReady()) speechStatus.textContent = '再生中（発話を待っています）'; };
        // 音を出せない間に届いた発話は溜めずに捨てる
        ws.onmessage = (event) => { if (audioReady()) playSegment(event.data); };
        ws.onclose = () => {
            if (socket !== ws) return;  // 古い接続 (OFF→ON 直後など)
            socket = null;
            if (enabled) {
                speechStatus.textContent = '接続が切れました。再接続しています…';
                setTimeout(() => { if (enabled && !socket) connectSpeech(); }, 2000);
            }
        };
    }

    function audioReady() {
        return audioCtx !== null && audioCtx.state === 'running';
    }

    function playSegment(data) {
        // ヘッダ: サンプリング周波数 (uint32), 人物ID (int32), 以降 float32 のサンプル列
        const view = new DataView(data);
        const sampleRate = view.getUint32(0, true);
        const personId = view.getInt32(4, true);
        const samples = new Float32Array(data, 8);
        if (samples.length === 0) return;
        const buffer = audioCtx.createBuffer(1, samples.length, sampleRate);
        buffer.copyToChannel(samples, 0);
        const source = audioCtx.createBufferSource();
        source.buffer = buffer;
        source.connect(audioCtx.destination);
        const startTime = Math.max(audioCtx.currentTime, nextStartTime);
        source.start(startTime);
        nextStartTime = startTime + buffer.duration;
        speechStatus.textContent = `再生中：人物ID ${personId} の発話（${buffer.duration.toFixed(1)}秒）`;
    }

    const STORAGE_KEY = 'speechPlayback';
    const speechState = speechToggle.querySelector('.switch__state');

    function setSwitch(on) {
        speechToggle.setAttribute('aria-checked', String(on));
        speechState.textContent = on ? 'ON' : 'OFF';
        try { localStorage.setItem(STORAGE_KEY, on ? 'on' : 'off'); } catch (e) {}
    }

    // ブラウザの自動再生制限で音を出せないときは, 最初のクリック等で再開する
    function resumeOnGesture() {
        if (!audioCtx || audioCtx.state === 'running') return;
        speechStatus.textContent = 'ページのどこかをクリックすると再生を始めます';
        const resume = async () => {
            if (audioCtx && audioCtx.state !== 'closed') {
                await audioCtx.resume();
                if (socket && socket.readyState === WebSocket.OPEN) {
                    speechStatus.textContent = '再生中（発話を待っています）';
                }
            }
        };
        document.addEventListener('pointerdown', resume, { once: true });
        document.addEventListener('keydown', resume, { once: true });
    }

    async function startSpeech(byUser) {
        enabled = true;
        setSwitch(true);
        audioCtx = new AudioContext();
        audioCtx.onstatechange = () => {
            if (audioReady() && socket && socket.readyState === WebSocket.OPEN) {
                speechStatus.textContent = '再生中（発話を待っています）';
            }
        };
        nextStartTime = 0;
        speechStatus.textContent = '接続しています…';
        connectSpeech();
        if (byUser) {
            await audioCtx.resume();  // クリック操作中なので再開できる
        } else {
            // 自動再開: 操作なしでは resume() が完了しないことがあるので待たない
            audioCtx.resume().catch(() => {});
            resumeOnGesture();
        }
    }

    async function stopSpeech() {
        enabled = false;
        setSwitch(false);
        if (socket) socket.close();
        if (audioCtx) {
            // 再生待ちの音声も破棄する
            await audioCtx.close();
            audioCtx = null;
        }
        speechStatus.textContent = '停止中';
    }

    speechToggle.addEventListener('click', () => (enabled ? stopSpeech() : startSpeech(true)));

    // 前回 ON にしていたら自動で再開する
    let saved = null;
    try { saved = localStorage.getItem(STORAGE_KEY); } catch (e) {}
    if (saved === 'on') startSpeech(false);
}

const notification = document.getElementById('notification');
let notificationTimer;

function showNotification(message, isError = false) {
    notification.textContent = message;
    notification.classList.toggle('notification--error', isError);
    notification.hidden = false;
    clearTimeout(notificationTimer);
    notificationTimer = setTimeout(() => { notification.hidden = true; }, 3000);
}

const postJson = url => fetchJson(url, { method: 'POST' });

document.querySelectorAll('[data-command]').forEach(btn => {
    btn.addEventListener('click', async () => {
        try {
            await postJson('/control/' + btn.dataset.command);
        } catch (error) {
            console.error('Control error:', error);
            showNotification(`ロボットの操作に失敗しました：${error.message}`, true);
        }
    });
});

// ---- 部屋を見に行く (行き先は DB から読む. 変更はページを開き直さなくても反映される) ----
(() => {
    const panel = document.getElementById('rooms');
    const list = document.getElementById('rooms-list');
    if (!panel) return;
    let last = '';

    async function update() {
        try {
            const { destinations } = await fetchJson('/destinations');
            const key = JSON.stringify(destinations);
            if (key === last) return;
            last = key;
            list.replaceChildren(...destinations.map(d => {
                const btn = el('button', 'button button--primary', d.label);
                btn.type = 'button';
                btn.dataset.destination = d.id;
                btn.title = d.text;
                return btn;
            }));
            panel.hidden = destinations.length === 0;
        } catch (error) {
            console.error('Destinations error:', error);
        }
    }

    list.addEventListener('click', async event => {
        const btn = event.target.closest('[data-destination]');
        if (!btn) return;
        try {
            const result = await postJson('/destinations/' + encodeURIComponent(btn.dataset.destination) + '/visit');
            showNotification(result.message);
        } catch (error) {
            console.error('Request error:', error);
            showNotification(`エラーが発生しました：${error.message}`, true);
            update();
        }
    });
    poll(update, DESTINATIONS_INTERVAL_MS);
})();
