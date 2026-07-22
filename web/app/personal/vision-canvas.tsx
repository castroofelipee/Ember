"use client";
/* eslint-disable @next/next/no-img-element -- Cloudinary supplies optimized image URLs. */

import { useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { Link2, X } from "lucide-react";
import type { PersonalItem } from "@/lib/types";

type Point = { x: number; y: number };
type Size = { w: number; h: number };
type Connection = { from: string; to: string };
type VisionCanvasProps = {
  wall: PersonalItem;
  images: PersonalItem[];
  onAdd: () => void;
  onRemove: (image: PersonalItem) => void;
  onUpdate: (item: PersonalItem, data: Record<string, unknown>) => Promise<void>;
};

const NODE_WIDTH = 190;
const MIN_NODE_SIZE = 70;

function nodeWidth(image: PersonalItem): number {
  return typeof image.data.w === "number" ? image.data.w : NODE_WIDTH;
}

function nodeHeight(image: PersonalItem): number {
  if (typeof image.data.h === "number") return image.data.h;
  const width = typeof image.data.width === "number" ? image.data.width : 4;
  const height = typeof image.data.height === "number" ? image.data.height : 3;
  return Math.max(110, Math.min(260, NODE_WIDTH * (height / width)));
}

function nodeSize(image: PersonalItem): Size {
  return { w: nodeWidth(image), h: nodeHeight(image) };
}

function initialPoint(image: PersonalItem, index: number): Point {
  return {
    x: typeof image.data.x === "number" ? image.data.x : 30 + (index % 4) * 220,
    y: typeof image.data.y === "number" ? image.data.y : 30 + Math.floor(index / 4) * 230,
  };
}

export function VisionCanvas({ wall, images, onAdd, onRemove, onUpdate }: VisionCanvasProps) {
  const canvasRef = useRef<HTMLDivElement>(null);
  const [positions, setPositions] = useState<Record<string, Point>>({});
  const positionsRef = useRef<Record<string, Point>>({});
  const [sizes, setSizes] = useState<Record<string, Size>>({});
  const sizesRef = useRef<Record<string, Size>>({});
  const [drag, setDrag] = useState<{ id: string; offset: Point } | null>(null);
  const [resize, setResize] = useState<{ id: string; start: Point; from: Size } | null>(null);
  const [link, setLink] = useState<{ from: string; pointer: Point } | null>(null);
  const [linkTarget, setLinkTarget] = useState<string | null>(null);
  const connections = useMemo(
    () => (Array.isArray(wall.data.connections) ? wall.data.connections : []) as Connection[],
    [wall.data.connections],
  );
  const pointFor = (image: PersonalItem, index: number) => positions[image.id] ?? initialPoint(image, index);
  const sizeFor = (image: PersonalItem) => sizes[image.id] ?? nodeSize(image);
  const relativePointer = (event: { clientX: number; clientY: number }): Point => {
    const rect = canvasRef.current?.getBoundingClientRect();
    return { x: event.clientX - (rect?.left ?? 0), y: event.clientY - (rect?.top ?? 0) };
  };

  function startMove(event: ReactPointerEvent, image: PersonalItem, index: number) {
    if ((event.target as HTMLElement).closest("button")) return;
    const pointer = relativePointer(event);
    const point = pointFor(image, index);
    event.currentTarget.setPointerCapture(event.pointerId);
    setDrag({ id: image.id, offset: { x: pointer.x - point.x, y: pointer.y - point.y } });
  }

  function startResize(event: ReactPointerEvent, image: PersonalItem) {
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    setResize({ id: image.id, start: relativePointer(event), from: sizeFor(image) });
  }

  function move(event: ReactPointerEvent) {
    const pointer = relativePointer(event);
    if (resize) {
      const next: Size = {
        w: Math.max(MIN_NODE_SIZE, resize.from.w + (pointer.x - resize.start.x)),
        h: Math.max(MIN_NODE_SIZE, resize.from.h + (pointer.y - resize.start.y)),
      };
      sizesRef.current = { ...sizesRef.current, [resize.id]: next };
      setSizes((current) => ({ ...current, [resize.id]: next }));
    }
    if (drag) {
      const image = images.find((candidate) => candidate.id === drag.id);
      const size = image ? sizeFor(image) : { w: NODE_WIDTH, h: 142 };
      const maxX = Math.max(0, (canvasRef.current?.clientWidth ?? size.w) - size.w);
      const maxY = Math.max(0, (canvasRef.current?.clientHeight ?? size.h) - size.h);
      const nextPoint = {
        x: Math.max(0, Math.min(maxX, pointer.x - drag.offset.x)),
        y: Math.max(0, Math.min(maxY, pointer.y - drag.offset.y)),
      };
      positionsRef.current = { ...positionsRef.current, [drag.id]: nextPoint };
      setPositions((current) => ({ ...current, [drag.id]: nextPoint }));
    }
    if (link) {
      setLink({ ...link, pointer });
      const target = (event.target as HTMLElement | null)
        ?.closest<HTMLElement>("[data-vision-image]")?.dataset.visionImage;
      setLinkTarget(target && target !== link.from ? target : null);
    }
  }

  async function finishResize() {
    if (!resize) return;
    const image = images.find((candidate) => candidate.id === resize.id);
    const size = sizesRef.current[resize.id];
    setResize(null);
    if (image && size) await onUpdate(image, { ...image.data, w: size.w, h: size.h });
  }

  async function finishMove(event: ReactPointerEvent) {
    if (!drag) return;
    const image = images.find((candidate) => candidate.id === drag.id);
    const pointer = relativePointer(event);
    const size = image ? sizeFor(image) : { w: NODE_WIDTH, h: 142 };
    const maxX = Math.max(0, (canvasRef.current?.clientWidth ?? size.w) - size.w);
    const maxY = Math.max(0, (canvasRef.current?.clientHeight ?? size.h) - size.h);
    const point = {
      x: Math.max(0, Math.min(maxX, pointer.x - drag.offset.x)),
      y: Math.max(0, Math.min(maxY, pointer.y - drag.offset.y)),
    };
    positionsRef.current = { ...positionsRef.current, [drag.id]: point };
    setPositions((current) => ({ ...current, [drag.id]: point }));
    setDrag(null);
    if (image) await onUpdate(image, { ...image.data, ...point });
  }

  function finishInteraction(event: ReactPointerEvent) {
    if (resize) { void finishResize(); return; }
    if (drag) { void finishMove(event); }
  }

  async function connectTo(target: string) {
    if (!link || target === link.from) return;
      const exists = connections.some((connection) =>
        (connection.from === link.from && connection.to === target) ||
        (connection.from === target && connection.to === link.from));
      if (!exists) await onUpdate(wall, { ...wall.data, connections: [...connections, { from: link.from, to: target }] });
    setLink(null);
    setLinkTarget(null);
  }

  const center = (id: string): Point | null => {
    const index = images.findIndex((image) => image.id === id);
    if (index < 0) return null;
    const point = pointFor(images[index], index);
    const size = sizeFor(images[index]);
    return { x: point.x + size.w / 2, y: point.y + size.h / 2 };
  };

  return <div
    ref={canvasRef}
    className={`vision-canvas${drag ? " vision-canvas--dragging" : ""}`}
    onPointerMove={move}
    onPointerUp={finishInteraction}
    onPointerCancel={() => { setDrag(null); setResize(null); setLink(null); setLinkTarget(null); }}
  >
    {link && <div className="vision-link-hint"><Link2 size={14}/>Click another image to connect</div>}
    <svg className="vision-connections" aria-hidden="true">
      {connections.map((connection) => { const from = center(connection.from); const to = center(connection.to); if (!from || !to) return null; return <g key={`${connection.from}-${connection.to}`}><line x1={from.x} y1={from.y} x2={to.x} y2={to.y}/><circle cx={from.x} cy={from.y} r="4"/><circle cx={to.x} cy={to.y} r="4"/></g>; })}
      {link && (() => { const from = center(link.from); return from ? <g><line className="vision-connection-preview" x1={from.x} y1={from.y} x2={link.pointer.x} y2={link.pointer.y}/><circle cx={from.x} cy={from.y} r="4"/><circle cx={link.pointer.x} cy={link.pointer.y} r="4"/></g> : null; })()}
    </svg>
    {images.map((image, index) => { const point = pointFor(image, index); const size = sizeFor(image); return <figure
      className={`vision-node${drag?.id === image.id ? " vision-node--moving" : ""}${resize?.id === image.id ? " vision-node--resizing" : ""}${linkTarget === image.id ? " vision-node--link-target" : ""}`}
      data-vision-image={image.id}
      key={image.id}
      style={{ transform: `translate(${point.x}px, ${point.y}px)`, width: size.w, height: size.h }}
      onPointerDown={(event) => startMove(event, image, index)}
      onClick={(event) => {
        if (link && link.from !== image.id) {
          event.stopPropagation();
          void connectTo(image.id);
        }
      }}
    >
      <img src={String(image.data.image_url)} alt={image.title}/>
      <button className="vision-node-delete" aria-label="Remove image" onClick={() => onRemove(image)}><X size={14}/></button>
      <button
        className={`vision-node-link${link?.from === image.id ? " vision-node-link--active" : ""}`}
        aria-label={`Connect ${image.title}`}
        title="Click, then choose another image"
        onPointerDown={(event) => event.stopPropagation()}
        onClick={(event) => {
          event.preventDefault(); event.stopPropagation();
          setLink(link?.from === image.id ? null : { from: image.id, pointer: center(image.id) ?? relativePointer(event) });
          setLinkTarget(null);
        }}
      ><Link2 size={13}/></button>
      <button
        className="vision-node-resize"
        aria-label={`Resize ${image.title}`}
        title="Drag to resize"
        onPointerDown={(event) => startResize(event, image)}
      />
    </figure>; })}
    {!images.length && <button className="vision-wall-empty" onClick={onAdd}><ImageIcon/><span>Add the first image</span></button>}
  </div>;
}

function ImageIcon() { return <span className="vision-empty-symbol">＋</span>; }
