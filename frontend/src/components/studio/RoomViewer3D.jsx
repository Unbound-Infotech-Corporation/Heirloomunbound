import { useEffect, useRef } from "react";
import { parseRoomGltf } from "../../lib/rooms";

function project(x, y, z, yaw, pitch, w, h) {
  const cy = Math.cos(yaw);
  const sy = Math.sin(yaw);
  const cp = Math.cos(pitch);
  const sp = Math.sin(pitch);
  const x1 = x * cy - z * sy;
  const z1 = x * sy + z * cy;
  const y1 = y * cp - z1 * sp;
  const z2 = y * sp + z1 * cp;
  const dist = 7;
  const scale = (Math.min(w, h) * 0.55) / (dist + z2);
  return {
    x: w / 2 + x1 * scale * 1.15,
    y: h / 2 - y1 * scale,
    z: z2,
  };
}

function drawRoom(ctx, w, h, yaw, pitch, title) {
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "rgba(18, 17, 16, 1)";
  ctx.fillRect(0, 0, w, h);

  const corners = [
    [-2, 0, -2],
    [2, 0, -2],
    [2, 0, 2],
    [-2, 0, 2],
    [-2, 2.4, -2],
    [2, 2.4, -2],
    [2, 2.4, 2],
    [-2, 2.4, 2],
  ].map(([x, y, z]) => project(x, y - 1.1, z, yaw, pitch, w, h));

  const faces = [
    { idx: [0, 1, 2, 3], fill: "rgba(212, 163, 115, 0.18)", name: "floor" },
    { idx: [0, 1, 5, 4], fill: "rgba(80, 72, 64, 0.55)", name: "back" },
    { idx: [1, 2, 6, 5], fill: "rgba(90, 82, 72, 0.5)", name: "right" },
    { idx: [3, 0, 4, 7], fill: "rgba(70, 64, 56, 0.5)", name: "left" },
    { idx: [2, 3, 7, 6], fill: "rgba(60, 54, 48, 0.35)", name: "front" },
  ];

  const withDepth = faces.map((f) => {
    const pts = f.idx.map((i) => corners[i]);
    const z = pts.reduce((s, p) => s + p.z, 0) / pts.length;
    return { ...f, pts, z };
  });
  withDepth.sort((a, b) => b.z - a.z);

  for (const face of withDepth) {
    ctx.beginPath();
    face.pts.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
    ctx.closePath();
    ctx.fillStyle = face.fill;
    ctx.fill();
    ctx.strokeStyle = "rgba(212, 163, 115, 0.45)";
    ctx.lineWidth = 1;
    ctx.stroke();
  }

  const twin = project(0, 0.4, 0, yaw, pitch, w, h);
  ctx.beginPath();
  ctx.arc(twin.x, twin.y, 10, 0, Math.PI * 2);
  ctx.fillStyle = "rgba(212, 163, 115, 0.9)";
  ctx.fill();

  ctx.fillStyle = "rgba(232, 220, 204, 0.7)";
  ctx.font = "12px Manrope, sans-serif";
  ctx.fillText(title || "placeholder room", 16, h - 16);
}

/**
 * Phase 1 placeholder viewer. Loads the mock glTF extras (inline positions)
 * and draws an enclosed volume. WebXR is offered when the browser supports it.
 */
export default function RoomViewer3D({ gltf, title, testid = "room-viewer-3d" }) {
  const canvasRef = useRef(null);
  const state = useRef({ yaw: 0.55, pitch: 0.28, dragging: false, lastX: 0, lastY: 0 });

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    const ctx = canvas.getContext("2d");
    parseRoomGltf(gltf); // validated even when we use the built-in volume
    let raf = 0;

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.max(320, rect.width) * dpr;
      canvas.height = Math.max(240, rect.height) * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();

    const tick = () => {
      const rect = canvas.getBoundingClientRect();
      if (!state.current.dragging) state.current.yaw += 0.003;
      drawRoom(ctx, rect.width, rect.height, state.current.yaw, state.current.pitch, title);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);

    const onDown = (e) => {
      state.current.dragging = true;
      state.current.lastX = e.clientX;
      state.current.lastY = e.clientY;
    };
    const onMove = (e) => {
      if (!state.current.dragging) return;
      const dx = e.clientX - state.current.lastX;
      const dy = e.clientY - state.current.lastY;
      state.current.lastX = e.clientX;
      state.current.lastY = e.clientY;
      state.current.yaw += dx * 0.01;
      state.current.pitch = Math.max(-0.6, Math.min(0.9, state.current.pitch + dy * 0.01));
    };
    const onUp = () => {
      state.current.dragging = false;
    };

    canvas.addEventListener("pointerdown", onDown);
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("resize", resize);
    return () => {
      cancelAnimationFrame(raf);
      canvas.removeEventListener("pointerdown", onDown);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("resize", resize);
    };
  }, [gltf, title]);

  return (
    <canvas
      ref={canvasRef}
      data-testid={testid}
      className="w-full h-full block cursor-grab active:cursor-grabbing"
      style={{ background: "var(--bg-base)" }}
    />
  );
}

export async function tryEnterWebXR(canvas) {
  if (!navigator.xr || !navigator.xr.isSessionSupported) {
    return { ok: false, reason: "This browser does not expose WebXR." };
  }
  const ok = await navigator.xr.isSessionSupported("immersive-vr").catch(() => false);
  if (!ok) {
    return { ok: false, reason: "No immersive VR headset is available on this computer." };
  }
  try {
    const gl = canvas?.getContext?.("webgl", { xrCompatible: true }) || canvas;
    const session = await navigator.xr.requestSession("immersive-vr", { optionalFeatures: ["local-floor"] });
    if (gl && gl.makeXRCompatible) await gl.makeXRCompatible();
    return { ok: true, session };
  } catch (err) {
    return { ok: false, reason: err?.message || "WebXR session was refused." };
  }
}
