() => {
  // Blocos de texto visíveis do render inicial (mesma ideia do Design2Code, mas lida do DOM):
  // um bloco por nó de texto, com caixa em px do viewport, cor computada e tamanho da fonte.
  const SKIP_TAGS = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'HEAD', 'TITLE']);
  const vw = window.innerWidth, vh = window.innerHeight;

  const visible = (el) => {
    if (el.checkVisibility) {
      return el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true });
    }
    const cs = getComputedStyle(el);
    return cs.display !== 'none' && cs.visibility !== 'hidden' && parseFloat(cs.opacity) > 0;
  };
  // Qualquer formato de cor (rgb, hex, oklch, oklab, lab...) vira sRGB pintando 1 pixel num canvas:
  // o Tailwind 4 calcula as cores em oklch, que um parser de rgb() não entende.
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 1;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  const parseColor = (value) => {
    if (!value || value === 'transparent') return null;
    ctx.clearRect(0, 0, 1, 1);
    ctx.fillStyle = 'rgba(0, 0, 0, 0)';
    ctx.fillStyle = value;
    ctx.fillRect(0, 0, 1, 1);
    const d = ctx.getImageData(0, 0, 1, 1).data;
    return d[3] === 0 ? null : [d[0], d[1], d[2]];
  };
  const clip = (r) => {
    const x0 = Math.max(0, r.left), y0 = Math.max(0, r.top);
    const x1 = Math.min(vw, r.right), y1 = Math.min(vh, r.bottom);
    if (x1 - x0 < 1 || y1 - y0 < 1) return null;
    return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
  };
  const round = (n) => Math.round(n * 100) / 100;
  const blocks = [];
  const push = (text, rect, el, extra) => {
    const norm = text.replace(/\s+/g, ' ').trim();
    if (!norm) return;
    const box = clip(rect);
    if (!box) return;
    const cs = getComputedStyle(el);
    blocks.push({
      text: norm, x: round(box.x), y: round(box.y), w: round(box.w), h: round(box.h),
      color: parseColor(cs.color), font_size: parseFloat(cs.fontSize),
      font_weight: cs.fontWeight, font_family: cs.fontFamily.split(',')[0].replace(/["']/g, '').trim(),
      tag: el.tagName.toLowerCase(), is_input: !!(extra && extra.is_input),
    });
  };

  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const range = document.createRange();
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const el = node.parentElement;
    if (!el || SKIP_TAGS.has(el.tagName) || el.closest('svg') || !visible(el)) continue;
    if (!node.textContent.trim()) continue;
    range.selectNodeContents(node);
    push(node.textContent, range.getBoundingClientRect(), el);
  }

  // Campos de formulário: o valor (ou placeholder) conta como texto, na caixa do campo.
  const SKIP_INPUT = new Set(['checkbox', 'radio', 'hidden', 'file', 'range', 'color', 'image']);
  for (const el of document.querySelectorAll('input, textarea, select')) {
    if (!visible(el)) continue;
    let text = '';
    if (el.tagName === 'SELECT') {
      text = el.selectedOptions && el.selectedOptions[0] ? el.selectedOptions[0].textContent : '';
    } else if (el.tagName === 'INPUT' && SKIP_INPUT.has(el.type)) {
      continue;
    } else if (el.tagName === 'INPUT' && ['button', 'submit', 'reset'].includes(el.type)) {
      text = el.value;
    } else {
      text = el.value || el.placeholder || '';
    }
    push(text, el.getBoundingClientRect(), el, { is_input: true });
  }

  blocks.sort((a, b) => a.y - b.y || a.x - b.x);
  return blocks;
}
