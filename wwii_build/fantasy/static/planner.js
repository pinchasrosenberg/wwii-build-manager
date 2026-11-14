import { upgradeScene } from './exterior.js';
import { drawProjectMap, fitView, toWorld } from './projectmap.js';

const toHex = (c) => `#${c.map((v) => Math.round(v).toString(16).padStart(2, '0')).join('')}`;

const kmeans = (pixels, k) => {
  const centers = Array.from({ length: k }, (_, i) => pixels[Math.floor((i + 0.5) * (pixels.length / k))].slice());
  const assign = new Array(pixels.length).fill(0);
  Array.from({ length: 10 }).forEach(() => {
    pixels.forEach((p, i) => {
      assign[i] = centers.reduce((best, c, j) => {
        const d = (p[0] - c[0]) ** 2 + (p[1] - c[1]) ** 2 + (p[2] - c[2]) ** 2;
        return d < best[1] ? [j, d] : best;
      }, [0, Infinity])[0];
    });
    centers.forEach((c, j) => {
      const members = pixels.filter((_, i) => assign[i] === j);
      members.length && c.splice(0, 3, ...[0, 1, 2].map((q) => members.reduce((s, m) => s + m[q], 0) / members.length));
    });
  });
  return centers.map((c, j) => [c, assign.filter((a) => a === j).length]).sort((a, b) => b[1] - a[1]).map(([c]) => toHex(c));
};

const readImage = (file) =>
  new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = reject;
    reader.onload = () => {
      const img = new Image();
      img.onerror = reject;
      img.onload = () => {
        const scale = Math.min(1, 1280 / Math.max(img.width, img.height));
        const canvas = document.createElement('canvas');
        canvas.width = Math.round(img.width * scale);
        canvas.height = Math.round(img.height * scale);
        canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
        const small = document.createElement('canvas');
        small.width = 48;
        small.height = 48;
        const sctx = small.getContext('2d');
        sctx.drawImage(img, 0, 0, 48, 48);
        const data = sctx.getImageData(0, 0, 48, 48).data;
        const pixels = Array.from({ length: 48 * 48 }, (_, i) => [data[i * 4], data[i * 4 + 1], data[i * 4 + 2]]);
        resolve({ dataUrl: canvas.toDataURL('image/jpeg', 0.86), palette: kmeans(pixels, 7) });
      };
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  });

export const initPlanner = ({ state, api, loadWorld, teleport, $ }) => {
  const local = { image: null, palette: [], editImage: null, view: null, proposal: null, drag: null, open: false };
  const mapCanvas = $('pm-canvas');

  const swatches = (el, colors) => {
    el.innerHTML = '';
    colors.forEach((c) => {
      const s = document.createElement('span');
      s.className = 'swatch';
      s.style.background = c;
      s.title = c;
      el.appendChild(s);
    });
  };

  const refreshModels = async () => {
    const st = await api.models().catch(() => null);
    const line = st ? `מודל ראייה: ${st.vision.name} — ${st.vision.up ? 'פעיל' : st.vision.installed ? 'מותקן, כבוי' : 'לא מותקן'} · מודל טקסט: ${st.text.name} — ${st.text.up ? 'פעיל' : 'כבוי'}` : 'לא ניתן לבדוק את המודלים';
    $('models-status').textContent = line;
    $('models-start').style.display = st && !st.vision.up && st.vision.can_start ? 'inline-block' : 'none';
    return st;
  };

  const startModels = async () => {
    $('models-start').disabled = true;
    $('models-status').textContent = 'מפעיל את מודל הראייה המקומי… (כחצי דקה)';
    await api.startModels();
    const poll = async (n) => {
      const st = await refreshModels();
      return st && st.vision.up ? st : n > 0 ? new Promise((r) => setTimeout(() => r(poll(n - 1)), 3000)) : st;
    };
    await poll(25);
    $('models-start').disabled = false;
  };

  const pickImage = async (input, target) => {
    const file = input.files && input.files[0];
    if (file) {
      const { dataUrl, palette } = await readImage(file);
      target.image = dataUrl;
      target.palette = palette;
      return { dataUrl, palette };
    }
    return null;
  };

  const createExtras = () => ({ image: local.image, palette: local.palette, basemap: $('wbase').value || undefined });

  const draw = () => {
    if (local.open && state.data) {
      mapCanvas.width = mapCanvas.clientWidth * (window.devicePixelRatio || 1);
      mapCanvas.height = mapCanvas.clientHeight * (window.devicePixelRatio || 1);
      local.view = local.view || fitView(mapCanvas, state.data);
      drawProjectMap(mapCanvas, state.data, local.view, state.mode === 'world' ? state.player : { ...state.player, x: state.data.palace.x, z: state.data.palace.z });
    }
  };

  const fillSidebar = async () => {
    const bm = state.data.basemap || {};
    $('pm-title').textContent = bm.name || 'מפת הפרויקט';
    $('pm-summary').innerHTML = '';
    (state.payload.plan_summary || []).forEach((line) => {
      const li = document.createElement('li');
      li.textContent = line;
      $('pm-summary').appendChild(li);
    });
    $('pm-sources').innerHTML = '';
    (bm.sources || []).forEach((src) => {
      const li = document.createElement('li');
      li.textContent = src;
      $('pm-sources').appendChild(li);
    });
    const stats = state.data.stats || {};
    $('pm-stats').textContent = `בתים: ${stats.houses ?? state.data.houses.length} · מבנים מרכזיים: ${(state.data.landmarks || []).length} · גשרים: ${(state.data.bridges || []).length} · עצים: ${state.data.trees.length} · הריסות: ${stats.ruins ?? 0}`;
    const { versions } = await api.worldVersions(state.worldId);
    $('pm-versions').innerHTML = '';
    versions.slice(0, 10).forEach((v) => {
      const row = document.createElement('div');
      row.className = 'hist';
      row.innerHTML = '<span></span><button>חזור לגרסה</button>';
      row.querySelector('span').textContent = `גרסה ${v.version}: ${v.summary}`;
      row.querySelector('button').onclick = async () => {
        await api.revertWorld(state.worldId, v.version);
        await reload();
      };
      $('pm-versions').appendChild(row);
    });
  };

  const openMap = () => {
    if (state.data) {
      local.open = true;
      state.panelOpen = true;
      $('projmap').classList.add('on');
      local.view = null;
      draw();
      fillSidebar();
    }
  };

  const closeMap = () => {
    local.open = false;
    state.panelOpen = false;
    $('projmap').classList.remove('on');
    $('view').focus();
  };

  const toggleMap = () => (local.open ? closeMap() : openMap());

  const reload = async () => {
    const keep = { ...state.player, mode: state.mode, room: state.roomId };
    await loadWorld(state.worldId);
    if (keep.mode === 'world') teleport(keep.x, keep.z);
    local.view = null;
    draw();
    fillSidebar();
  };

  const previewMaps = (prop) => {
    const before = $('pm-before');
    const after = $('pm-after');
    const next = upgradeScene(prop.scene);
    [[before, state.data], [after, next]].forEach(([c, data]) => {
      c.width = c.clientWidth * 2;
      c.height = c.clientHeight * 2;
      drawProjectMap(c, data, fitView(c, data), null);
    });
  };

  const proposeEdit = async () => {
    const text = $('pm-text').value.trim();
    if (!text && !local.editImage) return;
    $('pm-propose').disabled = true;
    $('pm-status').textContent = 'מתכנן את השינוי עם המודל ובונה תצוגה מקדימה…';
    try {
      const prop = await api.proposePlan(state.worldId, text, local.editImage, $('pm-llm').checked);
      local.proposal = prop;
      $('pm-proposal').style.display = 'block';
      $('pm-changes').innerHTML = '';
      (prop.changes.length ? prop.changes : ['לא זוהה שינוי בתוכנית']).forEach((c) => {
        const li = document.createElement('li');
        li.textContent = c;
        $('pm-changes').appendChild(li);
      });
      $('pm-status').textContent = `פורש באמצעות: ${prop.source}${prop.notes.length ? ' · ' + prop.notes.join(' · ') : ''}`;
      previewMaps(prop);
    } catch (err) {
      $('pm-status').textContent = `שגיאה: ${err.message}`;
    }
    $('pm-propose').disabled = false;
  };

  const resolveEdit = async (action) => {
    $('pm-status').textContent = action === 'apply' ? 'בונה את העולם החדש…' : 'ההצעה נדחתה.';
    await api.resolvePlan(local.proposal.id, action);
    $('pm-proposal').style.display = 'none';
    local.proposal = null;
    if (action === 'apply') {
      await reload();
      $('pm-status').textContent = 'העולם עודכן ונשמר כגרסה חדשה.';
    }
  };

  const wire = () => {
    $('wimage').onchange = async () => {
      const got = await pickImage($('wimage'), local);
      if (got) {
        $('wimage-preview').src = got.dataUrl;
        $('wimage-preview').style.display = 'block';
        swatches($('wpalette'), got.palette);
        const st = await refreshModels();
        st && !st.vision.up && st.vision.can_start && startModels();
      }
    };
    $('pm-image').onchange = async () => {
      const holder = {};
      const got = await pickImage($('pm-image'), holder);
      local.editImage = got ? got.dataUrl : null;
      $('pm-image-preview').src = got ? got.dataUrl : '';
      $('pm-image-preview').style.display = got ? 'block' : 'none';
    };
    $('models-start').onclick = startModels;
    $('map-open').onclick = openMap;
    $('pm-close').onclick = closeMap;
    $('pm-propose').onclick = proposeEdit;
    $('pm-apply').onclick = () => resolveEdit('apply');
    $('pm-reject').onclick = () => resolveEdit('reject');
    mapCanvas.addEventListener('wheel', (e) => {
      e.preventDefault();
      const r = mapCanvas.getBoundingClientRect();
      const px = (e.clientX - r.left) * (mapCanvas.width / r.width);
      const py = (e.clientY - r.top) * (mapCanvas.height / r.height);
      const [wx, wz] = toWorld(mapCanvas, local.view, px, py);
      const f = e.deltaY < 0 ? 1.2 : 1 / 1.2;
      local.view = { scale: local.view.scale * f, cx: wx - (wx - local.view.cx) / f, cz: wz - (wz - local.view.cz) / f };
      draw();
    }, { passive: false });
    mapCanvas.addEventListener('mousedown', (e) => {
      local.drag = { x: e.clientX, y: e.clientY };
    });
    window.addEventListener('mouseup', () => {
      local.drag = null;
    });
    mapCanvas.addEventListener('mousemove', (e) => {
      if (local.drag) {
        const r = mapCanvas.getBoundingClientRect();
        const k = mapCanvas.width / r.width / local.view.scale;
        local.view = { ...local.view, cx: local.view.cx - (e.clientX - local.drag.x) * k, cz: local.view.cz - (e.clientY - local.drag.y) * k };
        local.drag = { x: e.clientX, y: e.clientY };
        draw();
      }
    });
    mapCanvas.addEventListener('dblclick', (e) => {
      const r = mapCanvas.getBoundingClientRect();
      const [wx, wz] = toWorld(mapCanvas, local.view, (e.clientX - r.left) * (mapCanvas.width / r.width), (e.clientY - r.top) * (mapCanvas.height / r.height));
      teleport(wx, wz);
      draw();
    });
    window.addEventListener('resize', draw);
    refreshModels();
  };

  wire();
  return { createExtras, toggleMap, openMap, closeMap, proposeEdit, resolveEdit, draw, local, refreshModels };
};
