// DM-01: Expandable hierarchy tree (Style > Style-Color > SKU). Click navigates.

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import type { ProductTree, TreeNode } from "../api/types";
import { LEVEL_LABEL } from "../lib/format";

export function TreePanel({ tree, currentId }: { tree: ProductTree; currentId: string }) {
  return (
    <div className="tree">
      <ul>
        <Node node={{ row: tree.root, children: tree.nodes }} currentId={currentId} depth={0} />
      </ul>
    </div>
  );
}

function Node({ node, currentId, depth }: { node: TreeNode; currentId: string; depth: number }) {
  const navigate = useNavigate();
  const containsCurrent = (n: TreeNode): boolean => n.row.entity_id === currentId || n.children.some(containsCurrent);
  const [open, setOpen] = useState(depth < 1 || containsCurrent(node));
  const hasChildren = node.children.length > 0;
  const r = node.row;
  const isCurrent = r.entity_id === currentId;
  const text =
    r.level === "style" ? r.style_number : r.level === "style_color" ? (r.color_code ?? r.label) : (r.size ?? r.sku ?? r.label);
  return (
    <li>
      <div
        className={`node${isCurrent ? " current" : ""}`}
        title={`${LEVEL_LABEL[r.level]}: ${r.label}`}
        onClick={() => {
          if (!isCurrent) navigate(`/products/${encodeURIComponent(r.entity_id)}`);
        }}
      >
        <span
          className="toggle"
          onClick={(e) => {
            e.stopPropagation();
            if (hasChildren) setOpen((o) => !o);
          }}
        >
          {hasChildren ? (open ? "▾" : "▸") : ""}
        </span>
        <span className={r.level === "style" ? "mono" : ""}>{text}</span>
        {r.level !== "style" && <span className="faint small">{r.label !== text ? r.label : ""}</span>}
        {r.lifecycle_status === "discontinued" && <span className="badge red">disc.</span>}
        {r.entity_type === "prepack" && <span className="badge">prepack</span>}
      </div>
      {hasChildren && open && (
        <ul>
          {node.children.map((c) => (
            <Node key={c.row.entity_id} node={c} currentId={currentId} depth={depth + 1} />
          ))}
        </ul>
      )}
    </li>
  );
}
