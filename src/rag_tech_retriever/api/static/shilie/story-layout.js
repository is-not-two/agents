/* Pure layout: main branches grow right, side branches grow down. */
export const geometry = {
  width: 256,
  height: 136,
  column: 352,
  row: 184,
  pad: 64,
  indent: 24,
};
export function layoutStory(root, nodes, folded = []) {
  const g = geometry,
    hidden = new Set(folded),
    children = new Map(),
    placed = [],
    edges = [];
  for (const n of nodes) {
    const p = n.parent_id || root.id;
    if (!children.has(p)) children.set(p, []);
    children.get(p).push(n);
  }
  function visit(n, x, y) {
    const card = { ...n, x, y };
    placed.push(card);
    let bottom = y + g.row,
      right = x + g.width;
    if (hidden.has(n.id)) return { bottom, right };
    const kids = children.get(n.id) || [];
    for (const child of kids.filter((k) => k.kind !== "main")) {
      const pos = { x: x + g.indent, y: bottom };
      edges.push({ from: card, to: { ...child, ...pos }, kind: "side" });
      const size = visit(child, pos.x, pos.y);
      bottom = size.bottom;
      right = Math.max(right, size.right);
    }
    let nextY = y;
    // Leave room for deeply indented side branches before the next main column.
    const mainX = Math.max(x + g.column, right + 72);
    for (const child of kids.filter((k) => k.kind === "main")) {
      const pos = { x: mainX, y: nextY };
      edges.push({ from: card, to: { ...child, ...pos }, kind: "main" });
      const size = visit(child, pos.x, pos.y);
      nextY = size.bottom;
      right = Math.max(right, size.right);
    }
    return { bottom: Math.max(bottom, nextY), right };
  }
  const size = visit(root, g.pad, g.pad);
  return {
    cards: placed,
    edges,
    width: size.right + g.pad,
    height: size.bottom + g.pad,
  };
}
